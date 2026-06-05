"""
Sincronização — importação de um snapshot JSON com merge seguro por invariante (tronco).

Espelha a barreira em dois tempos do `redefinir`:
  1. `planejar_importacao(snapshot, bancos)` — DRY-RUN, não grava: valida envelope (formato,
     versão de schema, hash), resolve chaves naturais → rowids locais e classifica cada item
     em **novo / idêntico / conflito**, com o diff campo-a-campo dos conflitos.
  2. `aplicar_importacao(snapshot, bancos, resolucoes)` — grava só o aprovado; ANTES de tocar
     qualquer banco, faz um backup pessoal automático (desfazer é sempre possível — I-6).

Merge por entidade (00_PRINCIPIOS) — declarado antes de codar:
- I-1 (ledger) → UNIÃO append-only: só adiciona chaves exportadas, nunca remove. Marcar uma
  chave como já exportada só impede um pagamento, nunca causa um — por isso unir é seguro.
- I-2 (extração fiel) → a nota entra com o `dados` transcrito; nunca re-extrai XML.
- I-4 (rastreabilidade) → marcações/validações entram por append idempotente PRESERVANDO
  autor e timestamp originais; o histórico nunca é truncado. Quem importou não vira autor.
- I-6 (ambiguidade visível) → nada de last-write-wins: todo conflito é exibido e só muda por
  escolha humana; schema/hash incompatível BARRA a importação inteira, nunca adivinha.
- Vínculo sempre por chave natural (NPP→contrato por (doc,num,ano); nota→NPP por `numero`):
  os rowids locais são recriados aqui, nunca importados.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from tronco import backup
from tronco.backup import Bancos

# Campos de auditoria ignorados ao comparar "idêntico vs conflito": diferem entre máquinas
# por construção (cada uma carimba seu relógio) e não são conteúdo de configuração.
_AUDITORIA = {"criado_em", "atualizado_em", "criado_por",
              "criada_em", "atualizada_em", "criada_por", "cadastrado_em"}

# Entidades cujo merge é por append idempotente (nunca geram conflito — I-1/I-4).
_APPEND = {"marcacoes", "validacoes", "exportacoes"}


@dataclass
class ItemPlano:
    entidade: str                       # "contratos" | "regras_federais" | "npps" | ...
    rotulo: str                         # chave natural legível (p/ a tela)
    situacao: str                       # "novo" | "identico" | "conflito" | "barrado"
    motivo: str = ""                    # explicação do conflito/barramento (I-6)
    diffs: list = field(default_factory=list)  # [(campo, local, snapshot)]
    dado: dict | None = None            # payload do snapshot (para aplicar)

    @property
    def id(self) -> str:
        """Identidade estável do item, usada para casar a escolha humana de resolução."""
        return f"{self.entidade}:{self.rotulo}"


@dataclass
class Plano:
    escopo: str
    gerado_por: dict
    valido: bool
    erro: str = ""                      # barramento de envelope (schema/hash) — I-6
    itens: list[ItemPlano] = field(default_factory=list)

    def por_situacao(self, situacao: str) -> list[ItemPlano]:
        return [i for i in self.itens if i.situacao == situacao]

    def resumo(self) -> dict:
        r = {"novo": 0, "identico": 0, "conflito": 0}
        for i in self.itens:
            r[i.situacao] = r.get(i.situacao, 0) + 1
        return r

    @property
    def conflitos(self) -> list[ItemPlano]:
        return self.por_situacao("conflito")


@dataclass
class Resumo:
    aplicados: int = 0
    ignorados: int = 0                  # idênticos + pulados
    conflitos_pendentes: int = 0        # conflitos sem resolução (não tocados)
    backup_previo: str | None = None    # caminho do snapshot automático pré-importação
    detalhes: list = field(default_factory=list)


# ---------- validação de envelope (I-6) ----------

def validar_envelope(snapshot: dict) -> str:
    """Devolve string de erro se o envelope deve BARRAR a importação inteira, ou '' se ok.
    Schema/versão/hash incompatível nunca é adivinhado — barra com mensagem."""
    if not isinstance(snapshot, dict):
        return "Arquivo não é um snapshot válido (esperado um objeto JSON)."
    if snapshot.get("formato") != backup.FORMATO:
        return f"Formato desconhecido: {snapshot.get('formato')!r} (esperado {backup.FORMATO!r})."
    versao = snapshot.get("schema_versao")
    if versao != backup.SCHEMA_VERSAO:
        return (f"Versão de schema incompatível: {versao!r} "
                f"(este sistema lê a versão {backup.SCHEMA_VERSAO}).")
    dados = snapshot.get("dados")
    if not isinstance(dados, dict):
        return "Snapshot sem bloco 'dados'."
    esperado = snapshot.get("hash_conteudo")
    if esperado and esperado != backup.hash_conteudo(dados):
        return "Hash de conteúdo não confere — arquivo truncado ou corrompido."
    return ""


# ---------- comparação campo-a-campo ----------

def _norm(d: dict) -> dict:
    """Normaliza pelo mesmo caminho que o snapshot percorreu (JSON): tuplas viram listas
    etc. Sem isto, `naturezas` (tupla no objeto local via asdict) compararia diferente da
    lista que volta do arquivo — um falso conflito a cada round-trip."""
    return json.loads(json.dumps(d, ensure_ascii=False))


def _diff(local: dict, snap: dict, ignorar: set) -> list:
    """Campos em que `local` e `snap` divergem (fora os de auditoria). Cada item é
    (campo, valor_local, valor_snapshot). Ambos os lados são normalizados via JSON para
    não acusar diferença só por tupla×lista."""
    local, snap = _norm(local), _norm(snap)
    campos = (set(local) | set(snap)) - ignorar
    out = []
    for c in sorted(campos):
        if local.get(c) != snap.get(c):
            out.append((c, local.get(c), snap.get(c)))
    return out


# ---------- classificação por entidade ----------

def _classificar_chave_natural(entidade, snap_item, local_payload, rotulo) -> ItemPlano:
    """Padrão comum a contratos/regras: ausente=novo; presente e igual=idêntico;
    presente e divergente=conflito com diff."""
    if local_payload is None:
        return ItemPlano(entidade, rotulo, "novo", dado=snap_item)
    diffs = _diff(local_payload, snap_item, _AUDITORIA)
    if not diffs:
        return ItemPlano(entidade, rotulo, "identico", dado=snap_item)
    return ItemPlano(entidade, rotulo, "conflito",
                     motivo="conteúdo difere do local", diffs=diffs, dado=snap_item)


def _plano_contratos(bancos: Bancos, itens: list) -> list[ItemPlano]:
    out = []
    for it in itens:
        rotulo = f"{it['prest_documento']}/{it['numero']}/{it['ano']}"
        local = bancos.contratos.obter_por_chave_natural(
            it["prest_documento"], it["numero"], it["ano"])
        local_payload = backup._contrato_payload(local) if local else None
        out.append(_classificar_chave_natural("contratos", it, local_payload, rotulo))
    return out


def _plano_regras(bancos: Bancos, itens: list, entidade: str, store) -> list[ItemPlano]:
    out = []
    for it in itens:
        rotulo = it["codigo"]
        local = store.obter_por_codigo(it["codigo"])
        local_payload = backup._regra_payload(local) if local else None
        out.append(_classificar_chave_natural(entidade, it, local_payload, rotulo))
    return out


def _plano_npps(bancos: Bancos, itens: list, dados: dict) -> list[ItemPlano]:
    """NPP por `numero`. Resolve o contrato por chave natural: se faltar local E não vier
    embutido no snapshot, é conflito (vínculo órfão não entra em silêncio — I-6)."""
    refs_embutidos = {(c["prest_documento"], c["numero"], c["ano"])
                      for c in dados.get("contratos", [])}
    out = []
    for it in itens:
        rotulo = it["numero"]
        ref = tuple(it["contrato_ref"])
        local_contrato = bancos.contratos.obter_por_chave_natural(*ref)
        if local_contrato is None and ref not in refs_embutidos:
            out.append(ItemPlano("npps", rotulo, "conflito",
                                 motivo=f"contrato {'/'.join(ref)} ausente (importe a config antes)",
                                 dado=it))
            continue
        local_npp = bancos.npps.obter_por_numero(it["numero"])
        if local_npp is None:
            out.append(ItemPlano("npps", rotulo, "novo", dado=it))
            continue
        local_payload = {"numero": local_npp.numero, "competencia": local_npp.competencia,
                         "rotulo": local_npp.rotulo, "observacoes": local_npp.observacoes,
                         "contrato_ref": backup._npp_payload(
                             local_npp, bancos.contratos.obter(local_npp.contrato_id))["contrato_ref"]}
        snap_cmp = {"numero": it["numero"], "competencia": it["competencia"],
                    "rotulo": it["rotulo"], "observacoes": it["observacoes"],
                    "contrato_ref": it["contrato_ref"]}
        diffs = _diff(local_payload, snap_cmp, _AUDITORIA)
        situacao = "identico" if not diffs else "conflito"
        out.append(ItemPlano("npps", rotulo, situacao,
                             motivo="" if not diffs else "NPP local difere do snapshot",
                             diffs=diffs, dado=it))
    return out


def _plano_notas(bancos: Bancos, itens: list) -> list[ItemPlano]:
    """Nota por `chave`. Mesma chave em OUTRA NPP, ou `dados` divergente, é conflito
    (nunca sobrescreve nem move em silêncio — I-1/I-6)."""
    por_chave = {n["chave"]: n for n in bancos.notas.listar()}
    numero_por_id = {npp.id: npp.numero for npp in bancos.npps.listar()}
    out = []
    for it in itens:
        rotulo = it["chave"]
        local = por_chave.get(it["chave"])
        if local is None:
            out.append(ItemPlano("notas", rotulo, "novo", dado=it))
            continue
        npp_local = numero_por_id.get(local["npp_id"])
        if npp_local is not None and it.get("npp_ref") and npp_local != it["npp_ref"]:
            out.append(ItemPlano("notas", rotulo, "conflito",
                                 motivo=f"a mesma nota já consta na NPP {npp_local}", dado=it))
            continue
        if local["dados"] != it["dados"]:
            out.append(ItemPlano("notas", rotulo, "conflito",
                                 motivo="dados da nota divergem do local", dado=it))
            continue
        out.append(ItemPlano("notas", rotulo, "identico", dado=it))
    return out


def _plano_append(entidade: str, itens: list, ja_presente) -> list[ItemPlano]:
    """marcações/validações/ledger: append idempotente. Item já presente (mesma tupla) é
    idêntico; o resto é novo. Nunca há conflito (histórico não se sobrescreve)."""
    out = []
    for it in itens:
        rot = it.get("chave", "?")
        if entidade == "validacoes":
            rot = f"{it['chave']}/{it['tributo']}"
        situacao = "identico" if ja_presente(it) else "novo"
        out.append(ItemPlano(entidade, rot, situacao, dado=it))
    return out


def planejar_importacao(snapshot: dict, bancos: Bancos) -> Plano:
    """Dry-run: valida o envelope e classifica cada item. Não grava nada."""
    erro = validar_envelope(snapshot)
    escopo = snapshot.get("escopo", "?") if isinstance(snapshot, dict) else "?"
    gerado_por = snapshot.get("gerado_por", {}) if isinstance(snapshot, dict) else {}
    if erro:
        return Plano(escopo=escopo, gerado_por=gerado_por, valido=False, erro=erro)

    dados = snapshot["dados"]
    itens: list[ItemPlano] = []
    itens += _plano_contratos(bancos, dados.get("contratos", []))
    itens += _plano_regras(bancos, dados.get("regras_federais", []),
                           "regras_federais", bancos.federais)
    itens += _plano_regras(bancos, dados.get("regras_inss", []),
                           "regras_inss", bancos.inss)
    itens += _plano_npps(bancos, dados.get("npps", []), dados)
    itens += _plano_notas(bancos, dados.get("notas", []))

    marc_hist = {_chave_marc(m) for m in bancos.marcacoes.historico()}
    itens += _plano_append("marcacoes", dados.get("marcacoes", []),
                           lambda it: _chave_marc(it) in marc_hist)
    val_hist = {_chave_val(v) for v in bancos.validacoes.historico()}
    itens += _plano_append("validacoes", dados.get("validacoes", []),
                           lambda it: _chave_val(it) in val_hist)
    led_hist = {e["chave"] for e in bancos.exportacoes.listar()}
    itens += _plano_append("exportacoes", dados.get("exportacoes", []),
                           lambda it: it["chave"] in led_hist)

    return Plano(escopo=escopo, gerado_por=gerado_por, valido=True, itens=itens)


def _chave_marc(m: dict) -> tuple:
    return (m["chave"], m["valor"], m.get("valor_material"), m["autor"], m["marcado_em"])


def _chave_val(v: dict) -> tuple:
    return (v["chave"], v["tributo"], v["acao"], v["valor"], v["autor"], v["validado_em"])


# ---------- aplicação ----------

def aplicar_importacao(snapshot: dict, bancos: Bancos,
                       resolucoes: dict | None = None,
                       backup_previo: bool = True) -> Resumo:
    """Aplica o que foi aprovado. Reclassifica internamente (evita TOCTOU) e grava só:
    novos; conflitos resolvidos como 'usar_snapshot'; idênticos e conflitos sem resolução
    (ou 'pular'/'manter_local') não são tocados. Antes de tudo, salva um backup pessoal
    automático — desfazer é sempre possível (I-6)."""
    resolucoes = resolucoes or {}
    plano = planejar_importacao(snapshot, bancos)
    if not plano.valido:
        return Resumo(detalhes=[("barrado", plano.erro)])

    resumo = Resumo()
    if backup_previo:
        env = backup.exportar_pessoal(bancos)
        resumo.backup_previo = str(backup.gravar_snapshot(env))

    dados = snapshot["dados"]
    for item in plano.itens:
        if item.situacao == "identico":
            resumo.ignorados += 1
            continue
        if item.situacao == "conflito":
            escolha = resolucoes.get(item.id, "pular")
            if escolha != "usar_snapshot":
                resumo.ignorados += 1
                if escolha == "pular":
                    resumo.conflitos_pendentes += 1
                continue
        # novo, ou conflito resolvido como usar_snapshot
        try:
            _aplicar_item(bancos, item, sobrescrever=(item.situacao == "conflito"))
            resumo.aplicados += 1
        except Exception as e:                      # falha visível, nunca engolida (I-6)
            resumo.detalhes.append((item.id, f"falhou: {e}"))

    # operador só de um backup pessoal, na própria máquina (decisão do humano)
    op = dados.get("operador")
    if op and snapshot.get("escopo") == "pessoal":
        bancos.operador.salvar(op["iniciais"], op["nome"])
        resumo.detalhes.append(("operador", f"identidade restaurada: {op['iniciais']}"))

    return resumo


def _aplicar_item(bancos: Bancos, item: ItemPlano, *, sobrescrever: bool) -> None:
    ent, d = item.entidade, item.dado
    if ent == "contratos":
        _aplicar_contrato(bancos, d, sobrescrever)
    elif ent == "regras_federais":
        _aplicar_regra(bancos.federais, _regra_fed_de_payload, d, sobrescrever)
    elif ent == "regras_inss":
        _aplicar_regra(bancos.inss, _regra_inss_de_payload, d, sobrescrever)
    elif ent == "npps":
        _aplicar_npp(bancos, d)
    elif ent == "notas":
        _aplicar_nota(bancos, d)
    elif ent == "marcacoes":
        bancos.marcacoes.importar(d["chave"], d["valor"], d["autor"], d["marcado_em"],
                                  valor_material=d.get("valor_material"))
    elif ent == "validacoes":
        bancos.validacoes.importar(d["chave"], d["tributo"], d["acao"], d["valor"],
                                   d["autor"], d["validado_em"])
    elif ent == "exportacoes":
        bancos.exportacoes.importar([d])


def _aplicar_contrato(bancos: Bancos, d: dict, sobrescrever: bool) -> None:
    from tronco.contratos import Contrato, MunicipioIss
    d = dict(d)
    muns = d.pop("municipios", [])
    c = Contrato(**d)
    c.municipios = [MunicipioIss(**m) for m in muns]
    if sobrescrever:
        local = bancos.contratos.obter_por_chave_natural(
            c.prest_documento, c.numero, c.ano)
        c.id = local.id if local else None
        c.criado_em = local.criado_em if local else None
    bancos.contratos.salvar(c)


def _aplicar_regra(store, construir, d: dict, sobrescrever: bool) -> None:
    r = construir(d)
    if sobrescrever:
        local = store.obter_por_codigo(r.codigo)
        r.id = local.id if local else None
        r.criado_em = local.criado_em if local else None
    store.salvar(r)


def _regra_fed_de_payload(d: dict):
    from galho_nfse.enquadramento import RegraEnquadramento
    d = dict(d)
    d.pop("id", None)
    return RegraEnquadramento(**d)


def _regra_inss_de_payload(d: dict):
    from galho_nfse.inss import RegraInss
    d = dict(d)
    d.pop("id", None)
    return RegraInss(**d)


def _aplicar_npp(bancos: Bancos, d: dict) -> None:
    from tronco.npp import NPP
    ref = tuple(d["contrato_ref"])
    contrato = bancos.contratos.obter_por_chave_natural(*ref)
    if contrato is None:                            # config tem que ter entrado antes
        raise ValueError(f"contrato {'/'.join(ref)} ausente ao aplicar a NPP {d['numero']}")
    if bancos.npps.obter_por_numero(d["numero"]) is not None:
        return                                      # idempotente por numero
    npp = NPP(numero=d["numero"], contrato_id=contrato.id, competencia=d["competencia"],
              rotulo=d.get("rotulo"), observacoes=d.get("observacoes"),
              criada_por=d.get("criada_por", "operador"),
              criada_em=d.get("criada_em"), atualizada_em=d.get("atualizada_em"))
    bancos.npps.importar(npp)


def _aplicar_nota(bancos: Bancos, d: dict) -> None:
    npp_ref = d.get("npp_ref")
    local_npp = bancos.npps.obter_por_numero(npp_ref) if npp_ref else None
    npp_id = local_npp.id if local_npp else None
    bancos.notas.salvar(d["chave"], d["tipo"], d["dados"], d.get("origem", ""), npp_id)
