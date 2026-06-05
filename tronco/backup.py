"""
Backup — snapshot JSON autocontido e versionado (tronco, infraestrutura).

Lê os bancos (pela API pública dos stores, nunca SQL cru) e produz um envelope JSON que
pode ser guardado/transportado manualmente (pasta do Google Drive da equipe, Fase A) e
reimportado por `tronco/sincronizacao.py`. Este módulo só **lê e traduz**; não decide nada.

Fronteira de invariante (00_PRINCIPIOS) — declarado antes de codar:
- Infra/Fase 1: move dado já gravado; não relê XML, não apura nada tributário, não cria
  modelo unificado. Tronco puro (os catálogos de regra, embora morem em galho_nfse, são
  persistência de configuração — importados de forma tardia para não acoplar o topo).
- I-1: o ledger de exportação viaja junto da NPP; a UNIÃO append-only vive na importação
  (`RegistroDeExportacao.importar`). Aqui só o transcrevemos fielmente.
- I-2: o `dados` de cada nota é transcrito como está (sem reinterpretar nem normalizar
  valor); a importação não re-extrai XML.
- I-4: marcações e validações vão com **autor e timestamp originais**; quem gerou o
  snapshot fica em metadado (`gerado_por`), nunca sobre a autoria do fato.
- I-5: o snapshot NÃO é o artefato de exportação (o "lote"); ainda assim, cada arquivo é
  novo, imutável e carimbado — nunca reescreve um anterior.
- I-6: a regra de ouro contra corrupção silenciosa — **FK nunca por rowid**. Todo vínculo
  vai por chave natural (NPP→contrato por (doc,num,ano); nota→NPP por `numero`), e o
  `hash_conteudo` permite a importação barrar truncamento/corrupção.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tronco.util import agora as agora_maquina

FORMATO = "extrator-nf/snapshot"
SCHEMA_VERSAO = 1

_RAIZ = Path(__file__).resolve().parent.parent
PASTA_PADRAO = _RAIZ / "backups"

# Nome de arquivo de cada banco (usado por `Bancos.abrir` para apontar a um diretório
# alternativo nos testes; em produção cada store usa seu CAMINHO_PADRAO).
_ARQUIVOS = {
    "contratos": "contratos.sqlite",
    "federais": "catalogo_federal.sqlite",
    "inss": "catalogo_inss.sqlite",
    "npps": "npps.sqlite",
    "notas": "notas.sqlite",
    "marcacoes": "marcacoes.sqlite",
    "validacoes": "validacoes_retencao.sqlite",
    "exportacoes": "registro_exportacao.sqlite",
    "operador": "operador.sqlite",
}


@dataclass
class Bancos:
    """Feixe dos nove stores do sistema, aberto de uma vez para as rotinas de backup e
    sincronização (que precisam de quase todos juntos). Os catálogos de regra são
    importados de forma tardia em `abrir` para o topo do módulo não acoplar galho."""
    contratos: object
    federais: object
    inss: object
    npps: object
    notas: object
    marcacoes: object
    validacoes: object
    exportacoes: object
    operador: object

    @classmethod
    def abrir(cls, base: str | Path | None = None) -> "Bancos":
        """Abre todos os stores. `base` (diretório) é injetável nos testes; em produção
        (None) cada store usa seu CAMINHO_PADRAO na raiz do repo."""
        from galho_nfse.catalogo_federal import StoreRegrasFederais
        from galho_nfse.catalogo_inss import StoreRegrasInss
        from tronco.contratos import StoreContratos
        from tronco.idempotencia import RegistroDeExportacao
        from tronco.marcacoes import StoreMarcacoes
        from tronco.notas import StoreNotas
        from tronco.npp import StoreNPP
        from tronco.operador import StoreOperador
        from tronco.validacao_retencao import StoreValidacaoRetencao

        if base is not None:
            Path(base).mkdir(parents=True, exist_ok=True)

        def caminho(chave: str):
            return Path(base) / _ARQUIVOS[chave] if base else None

        def _c(store_cls, chave):
            c = caminho(chave)
            return store_cls(c) if c is not None else store_cls()

        return cls(
            contratos=_c(StoreContratos, "contratos"),
            federais=_c(StoreRegrasFederais, "federais"),
            inss=_c(StoreRegrasInss, "inss"),
            npps=_c(StoreNPP, "npps"),
            notas=_c(StoreNotas, "notas"),
            marcacoes=_c(StoreMarcacoes, "marcacoes"),
            validacoes=_c(StoreValidacaoRetencao, "validacoes"),
            exportacoes=_c(RegistroDeExportacao, "exportacoes"),
            operador=_c(StoreOperador, "operador"),
        )

    def fechar(self) -> None:
        for s in (self.contratos, self.federais, self.inss, self.npps, self.notas,
                  self.marcacoes, self.validacoes, self.exportacoes, self.operador):
            try:
                s.fechar()
            except Exception:
                pass


# ---------- montagem do envelope ----------

def _canon(dados: dict) -> bytes:
    """Serialização canônica do bloco `dados` para o hash: chaves ordenadas, sem espaços,
    utf-8. Duas máquinas produzem o mesmo hash para o mesmo conteúdo."""
    return json.dumps(dados, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def hash_conteudo(dados: dict) -> str:
    return "sha256:" + hashlib.sha256(_canon(dados)).hexdigest()


def _contagem(dados: dict) -> dict:
    return {k: (len(v) if isinstance(v, list) else 1) for k, v in dados.items()}


def _gerado_por(bancos: Bancos) -> dict:
    op = bancos.operador.atual()
    return {"iniciais": op.iniciais, "nome": op.nome} if op else {}


def _envelope(escopo: str, dados: dict, *, gerado_por: dict) -> dict:
    """Embrulha `dados` num envelope versionado com integridade (I-6) e procedência (I-4)."""
    return {
        "formato": FORMATO,
        "schema_versao": SCHEMA_VERSAO,
        "escopo": escopo,
        "gerado_em": agora_maquina().isoformat(),
        "gerado_por": gerado_por,
        "hash_conteudo": hash_conteudo(dados),
        "contagem": _contagem(dados),
        "dados": dados,
    }


# ---------- payloads por entidade (FK→chave natural, rowid removido) ----------

def _contrato_payload(c) -> dict:
    """Contrato + municípios, sem rowid (não portátil). A chave natural
    (prest_documento, numero, ano) já está nos próprios campos."""
    d = c.to_dict()
    d.pop("id", None)
    for m in d.get("municipios", []):
        m.pop("id", None)
        m.pop("contrato_id", None)
    return d


def _regra_payload(r) -> dict:
    """Regra de catálogo sem rowid. O `codigo` (UNIQUE) é a chave natural e permanece."""
    d = asdict(r)
    d.pop("id", None)
    return d


def _npp_payload(npp, contrato) -> dict:
    """NPP sem rowid; o contrato vai por chave natural (`contrato_ref`), nunca por id."""
    return {
        "numero": npp.numero,
        "competencia": npp.competencia,
        "rotulo": npp.rotulo,
        "observacoes": npp.observacoes,
        "criada_por": npp.criada_por,
        "criada_em": npp.criada_em,
        "atualizada_em": npp.atualizada_em,
        "contrato_ref": [contrato.prest_documento, contrato.numero, contrato.ano],
    }


def _nota_payload(nota: dict, npp_numero: str | None) -> dict:
    """Nota com o `dados` transcrito fielmente (I-2) e a NPP por `numero` (nunca rowid)."""
    return {
        "chave": nota["chave"],
        "tipo": nota["tipo"],
        "origem": nota["origem"],
        "npp_ref": npp_numero,
        "dados": nota["dados"],
    }


def _operador_payload(op) -> dict:
    return {"iniciais": op.iniciais, "nome": op.nome, "cadastrado_em": op.cadastrado_em}


# ---------- blocos reutilizados pelos pacotes ----------

def _dados_configuracao(bancos: Bancos) -> dict:
    """Configuração compartilhável da equipe: contratos + as duas famílias de regra."""
    return {
        "contratos": [_contrato_payload(c) for c in bancos.contratos.listar()],
        "regras_federais": [_regra_payload(r) for r in bancos.federais.listar()],
        "regras_inss": [_regra_payload(r) for r in bancos.inss.listar()],
    }


def _dados_trabalho(bancos: Bancos) -> dict:
    """Dados de trabalho (sensíveis a I-1): NPPs, notas, marcações, validações, ledger.
    Resolve os vínculos por chave natural; NPP/nota órfã de contrato é erro visível (I-6)."""
    contratos_por_id = {c.id: c for c in bancos.contratos.listar()}
    npps = bancos.npps.listar()
    numero_por_id = {npp.id: npp.numero for npp in npps}

    npp_payloads = []
    for npp in npps:
        contrato = contratos_por_id.get(npp.contrato_id)
        if contrato is None:
            raise ValueError(
                f"NPP {npp.numero} sem contrato local — vínculo órfão não é exportado (I-6)")
        npp_payloads.append(_npp_payload(npp, contrato))

    notas = bancos.notas.listar()
    nota_payloads = [_nota_payload(n, numero_por_id.get(n["npp_id"])) for n in notas]

    return {
        "npps": npp_payloads,
        "notas": nota_payloads,
        "marcacoes": bancos.marcacoes.historico(),
        "validacoes": bancos.validacoes.historico(),
        "exportacoes": bancos.exportacoes.listar(),
    }


# ---------- exportações individuais (item-a-item) ----------

def exportar_contrato(bancos: Bancos, contrato_id: int) -> dict:
    c = bancos.contratos.obter(contrato_id)
    if c is None:
        raise ValueError(f"contrato {contrato_id} não encontrado")
    dados = {"contratos": [_contrato_payload(c)]}
    return _envelope("contrato", dados, gerado_por=_gerado_por(bancos))


def exportar_regra_federal(bancos: Bancos, id_: int) -> dict:
    r = bancos.federais.obter(id_)
    if r is None:
        raise ValueError(f"regra federal {id_} não encontrada")
    dados = {"regras_federais": [_regra_payload(r)]}
    return _envelope("regra_federal", dados, gerado_por=_gerado_por(bancos))


def exportar_regra_inss(bancos: Bancos, id_: int) -> dict:
    r = bancos.inss.obter(id_)
    if r is None:
        raise ValueError(f"regra INSS {id_} não encontrada")
    dados = {"regras_inss": [_regra_payload(r)]}
    return _envelope("regra_inss", dados, gerado_por=_gerado_por(bancos))


def exportar_npp(bancos: Bancos, npp_id: int) -> dict:
    """Uma NPP autocontida: contrato EMBUTIDO (decisão do humano), notas, marcações,
    validações e as entradas de ledger das suas notas. Tudo por chave natural; o ledger
    viaja junto para travar duplicidade no destino (I-1)."""
    npp = bancos.npps.obter(npp_id)
    if npp is None:
        raise ValueError(f"NPP {npp_id} não encontrada")
    contrato = bancos.contratos.obter(npp.contrato_id) if npp.contrato_id else None
    if contrato is None:
        raise ValueError("NPP sem contrato — não se exporta vínculo órfão (I-6)")

    notas = bancos.notas.listar_por_npp(npp_id)
    chaves = {n["chave"] for n in notas}
    dados = {
        "contratos": [_contrato_payload(contrato)],
        "npps": [_npp_payload(npp, contrato)],
        "notas": [_nota_payload(n, npp.numero) for n in notas],
        "marcacoes": [m for m in bancos.marcacoes.historico() if m["chave"] in chaves],
        "validacoes": [v for v in bancos.validacoes.historico() if v["chave"] in chaves],
        "exportacoes": [e for e in bancos.exportacoes.listar() if e["chave"] in chaves],
    }
    return _envelope("npp", dados, gerado_por=_gerado_por(bancos))


# ---------- pacotes em bloco ----------

def exportar_configuracao(bancos: Bancos) -> dict:
    """Toda a configuração da equipe num arquivo (semear uma máquina nova)."""
    return _envelope("configuracao", _dados_configuracao(bancos),
                     gerado_por=_gerado_por(bancos))


def exportar_completo(bancos: Bancos) -> dict:
    """Configuração + todo o trabalho (sem a identidade do operador)."""
    dados = {**_dados_configuracao(bancos), **_dados_trabalho(bancos)}
    return _envelope("completo", dados, gerado_por=_gerado_por(bancos))


def exportar_pessoal(bancos: Bancos) -> dict:
    """Backup da própria máquina: completo + identidade do operador (não vai no pacote
    da equipe — só restaurável na própria máquina)."""
    dados = {**_dados_configuracao(bancos), **_dados_trabalho(bancos)}
    op = bancos.operador.atual()
    if op is not None:
        dados["operador"] = _operador_payload(op)
    return _envelope("pessoal", dados, gerado_por=_gerado_por(bancos))


# ---------- gravação em disco / nome de arquivo ----------

def nome_arquivo(envelope: dict) -> str:
    """Nome do `.json`. Para uma NPP, herda o `numero` (que já traz as iniciais do
    operador) — a pedido do humano, para os arquivos de NPP de operadores diferentes não
    se confundirem na pasta do Drive. Os demais escopos levam carimbo de tempo + escopo."""
    escopo = envelope.get("escopo", "snapshot")
    npps = envelope.get("dados", {}).get("npps")
    if escopo == "npp" and npps:
        return f"{npps[0]['numero']}.json"
    carimbo = agora_maquina().strftime("%Y%m%d-%H%M%S")
    return f"snapshot_{carimbo}_{escopo}.json"


def gravar_snapshot(envelope: dict, pasta: str | Path | None = None) -> Path:
    """Grava o envelope como arquivo NOVO em `backups/` (imutável, append-only —
    espírito I-5). Devolve o caminho gravado."""
    destino = Path(pasta) if pasta is not None else PASTA_PADRAO
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / nome_arquivo(envelope)
    caminho.write_text(json.dumps(envelope, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return caminho
