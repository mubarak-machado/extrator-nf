"""
Tela do tronco (etapa 3) — app Flask local, com:
- formatação humana (filtros pt-BR de moeda/data/CNPJ/percentual);
- painel com KPIs e consolidações sugeridas;
- tabela consolidada por contrato (prestador + competência) para serviços
  continuados pagos de forma agregada (visão do operador do Siafi);
- detalhe orientado ao lançamento;
- marcação de material (I-4), idempotência (I-1) e exportação imutável (I-5).

Rodar:  uv run python -m tronco.app
"""
from __future__ import annotations

import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

from tronco.ingestao import ingerir, ingerir_pasta
from tronco.idempotencia import RegistroDeExportacao
from tronco.marcacoes import StoreMarcacoes
from tronco.notas import StoreNotas, reconstruir, ConflitoDeChave
from tronco.operador import StoreOperador, Operador
from tronco.npp import StoreNPP, NPP
from tronco.validacao_retencao import StoreValidacaoRetencao, TRIBUTOS, ACOES
from tronco.contratos import (StoreContratos, Contrato,
                              NATUREZAS, CATEGORIAS, MATERIAL_PREVISAO, BASES_MINIMAS,
                              IR_PERCENTUAIS, INSS_ADICIONAL, ISS_LOCAL)
from tronco.exportador import ExportadorCsvLocal, novo_lote_id
from tronco import formato, redefinicao
from galho_nfse.material import sugerir_material
from galho_nfse import retencao, enquadramento, tabela_in1234
from galho_nfse.enquadramento import RegraEnquadramento
from galho_nfse.catalogo_federal import StoreRegrasFederais

RAIZ = Path(__file__).resolve().parent.parent
PASTA_EXEMPLOS = RAIZ / "exemplos"
PASTA_SAIDA = RAIZ / "exportacoes"

app = Flask(__name__,
            template_folder=str(RAIZ / "templates"),
            static_folder=str(RAIZ / "static"))
app.secret_key = "mvp-poc-extrator-nf"

for nome in ("moeda", "numero", "data", "datahora", "competencia",
             "cnpj", "percent", "chave", "simnao"):
    app.jinja_env.filters[nome] = getattr(formato, nome)

# Teste Jinja: `{{ valor is ezero }}` atenua (não esconde) valores zerados.
app.jinja_env.tests["ezero"] = formato.ezero


# ---------- Identidade do operador (bootstrap; I-4) ----------
# A app roda local, sem autenticação, mas o I-4 exige autoria rastreável. Na 1ª
# execução, sem cadastro local, toda navegação é desviada para a tela de cadastro.

def _operador_atual():
    op = StoreOperador(); atual = op.atual(); op.fechar()
    return atual


@app.before_request
def _exige_operador():
    """Sem operador cadastrado, só as rotas de cadastro (e estáticos) respondem —
    o resto é desviado. Garante que nada seja criado sem autoria (I-4)."""
    if request.endpoint in {"operador_cadastro", "operador_salvar", "static"}:
        return
    if _operador_atual() is None:
        return redirect(url_for("operador_cadastro"))


@app.context_processor
def _ctx_operador():
    """Disponibiliza a identidade vigente para o rodapé (transparência de quem
    assina os registros) em todas as telas."""
    return {"operador_atual": _operador_atual()}


def _carregar():
    """Carrega as notas JÁ IMPORTADAS do banco (nunca lê XML ao vivo). A pasta de
    exemplos só é lida na importação manual (rota /importar). Lista vazia = nada
    importado ainda — não é erro, é o estado inicial após redefinir."""
    notas = StoreNotas()
    persistidas = notas.listar()
    notas.fechar()
    registro = RegistroDeExportacao()
    marc = StoreMarcacoes()
    linhas = []
    for n in persistidas:
        reg = reconstruir(n["tipo"], n["dados"])
        item = {"origem": n["origem"], "tipo": n["tipo"], "erro": None, "reg": reg,
                "npp_id": n["npp_id"],
                "ja_exportada": registro.ja_exportada(reg.chave),
                "marcacao": None,
                "valor": reg.valor_total if n["tipo"] == "NFE" else reg.valor_servicos}
        if n["tipo"] == "NFSE":
            item["marcacao"] = marc.atual(reg.chave)
        linhas.append(item)
    registro.fechar(); marc.fechar()
    return linhas


def _bruto(itens):
    total = Decimal("0")
    for it in itens:
        try:
            total += Decimal(str(it["valor"])) if it["valor"] else Decimal("0")
        except (InvalidOperation, ValueError):
            pass
    return f"{total:.2f}"


@app.route("/")
def hub():
    """Entrada: hub orientado às NPPs. Mostra as NPPs abertas (com nota inédita) e
    seu valor pendente, e o Histórico do que já foi exportado. Sem NPP nenhuma,
    convida a criar a primeira."""
    store = StoreNPP(); npps_lista = store.listar(); store.fechar()
    abertas = vazias = 0
    total_aberto = Decimal("0")
    for npp in npps_lista:
        itens = _itens_da_npp(npp.id)
        st = _npp_status(itens)
        if st == "aberta":
            abertas += 1
            total_aberto += Decimal(_bruto([i for i in itens if not i["ja_exportada"]]))
        elif st == "vazia":
            vazias += 1
    registro = RegistroDeExportacao(); exportadas = registro.listar(); registro.fechar()
    cards = {
        "npp_total": len(npps_lista),
        "npp_abertas": abertas,
        "npp_vazias": vazias,
        "npp_valor": f"{total_aberto:.2f}",
        "hist_total": len(exportadas),
        "sem_npps": not npps_lista,
    }
    return render_template("hub.html", cards=cards)


@app.route("/historico")
def historico():
    """Notas já exportadas (registro de idempotência), agrupadas por lote. É o
    'feito': consulta, não some, e impede pagamento em duplicidade (I-1)."""
    por_chave = {it["reg"].chave: it for it in _carregar() if it["reg"]}
    npps_store = StoreNPP(); npp_por_id = {n.id: n for n in npps_store.listar()}
    npps_store.fechar()
    registro = RegistroDeExportacao()
    exportadas = registro.listar()
    registro.fechar()
    lotes = defaultdict(list)
    for e in exportadas:
        it = por_chave.get(e["chave"])
        r = it["reg"] if it else None
        npp = npp_por_id.get(it["npp_id"]) if it and it.get("npp_id") else None
        lotes[e["lote_id"]].append({
            "chave": e["chave"], "tipo": e["tipo"], "exportado_em": e["exportado_em"],
            "numero": getattr(r, "numero", None),
            "npp_id": npp.id if npp else None,
            "npp_numero": npp.numero if npp else None,
            "nome": (getattr(r, "emit_nome", None) if e["tipo"] == "NFE"
                     else getattr(r, "prest_nome", None)) if r else None,
            "valor": (getattr(r, "valor_total", None) if e["tipo"] == "NFE"
                      else getattr(r, "valor_servicos", None)) if r else None,
            "disponivel": it is not None,
        })
    blocos = [{"lote_id": lid, "exportado_em": its[0]["exportado_em"],
               "n": len(its), "itens": its} for lid, its in lotes.items()]
    blocos.sort(key=lambda b: b["exportado_em"], reverse=True)
    return render_template("historico.html", blocos=blocos, total=len(exportadas))


@app.route("/nota/<chave>")
def detalhe(chave):
    for item in _carregar():
        if item["reg"] and item["reg"].chave == chave:
            # Sugestão de material a partir do texto livre — apenas SUGESTÃO, que
            # o operador vê ao lado do texto original e valida/edita (I-2/I-3).
            sugestao = (sugerir_material(item["reg"].discriminacao)
                        if item["tipo"] == "NFSE" else None)
            conf = _conferencia(item) if item["tipo"] == "NFSE" else None
            npp = _obter_npp(item["npp_id"]) if item.get("npp_id") else None
            return render_template("detalhe.html", item=item, sugestao=sugestao,
                                   conf=conf, npp=npp)
    flash("Nota não encontrada.", "erro")
    return redirect(url_for("hub"))


def _conferencia(item):
    """Confere a nota contra a regra do contrato da SUA NPP (vínculo explícito, não
    mais heurística por CNPJ). Read-only, sugestão (I-3); o contrato é sempre único
    (some o estado 'varios'). Despacha por tipo (galhos independentes)."""
    npp_id = item.get("npp_id")
    if not npp_id:
        return {"estado": "sem_npp"}
    npp = _obter_npp(npp_id)
    if not npp:
        return {"estado": "sem_npp"}
    store = StoreContratos(); contrato = store.obter(npp.contrato_id); store.fechar()
    if not contrato:
        return {"estado": "sem_contrato"}
    marc = item["marcacao"]
    marcado = marc.get("valor") if marc else None
    resultado = _conferir_por_tipo(item["reg"], item["tipo"], contrato, marcado)
    return {"estado": "ok", "resultado": resultado,
            "federal_origem": contrato.ret_federal_origem,
            "federal_codigo": contrato.ret_federal_regra_codigo,
            "federal_justificativa": contrato.ret_federal_justificativa}


@app.route("/marcar/<chave>", methods=["POST"])
def marcar(chave):
    valor = request.form.get("material")
    if valor not in ("sim", "nao"):
        flash("Selecione 'sim' ou 'não' para material aplicado.", "erro")
        return redirect(url_for("detalhe", chave=chave))
    # valor do material: só quando houve material; é o valor VALIDADO pelo
    # operador (campo livre), normalizado. Vazio/invalez vira None (não chuta).
    valor_material = None
    if valor == "sim":
        bruto = request.form.get("valor_material", "").strip()
        valor_material = formato.parse_valor(bruto) if bruto else None
    marc = StoreMarcacoes()
    marc.marcar(chave, valor, "operador", valor_material)
    marc.fechar()
    extra = (f" Valor do material: {formato.moeda(valor_material)}."
             if valor_material else "")
    flash(f"Marcação registrada: material aplicado = {valor.upper()}.{extra}", "ok")
    return redirect(url_for("detalhe", chave=chave))


def _exportar(candidatos, escritor):
    """Núcleo de exportação: idempotência (I-1) + grava o lote SÓ após sucesso.
    `escritor(regs, lote_id) -> artefato` decide o FORMATO (individual ou
    consolidado). Devolve (mensagem, categoria) para a modal de feedback."""
    if not candidatos:
        return "Nada a exportar: as notas selecionadas já foram exportadas.", "info"
    registro = RegistroDeExportacao()
    novas, _ = registro.filtrar_novas([r.chave for r in candidatos])
    candidatos = [r for r in candidatos if r.chave in set(novas)]
    if not candidatos:
        registro.fechar()
        return "Nada a exportar: as notas selecionadas já foram exportadas.", "info"
    lote = novo_lote_id()
    try:
        artefato = escritor(candidatos, lote)
    except Exception as exc:
        registro.fechar()
        return f"Exportação falhou ({type(exc).__name__}): {exc}. Nada foi registrado.", "erro"
    registro.registrar_lote([(r.chave, r.tipo) for r in candidatos], lote)
    registro.fechar()
    return f"Lote {lote} exportado: {len(candidatos)} nota(s). Artefato: {artefato}", "ok"


# Padrão INDIVIDUAL de exportação — ESPELHA a tabela da tela (individuais.html):
# arquivo único com NF-e e NFS-e juntas, mesmas colunas/ordem da tela (Tipo,
# Número, Fornecedor, CNPJ, Valor, Situação), MAIS retenções, líquido e o "Valor
# dos materiais" validado (o que o usuário pediu e não aparece na tela). NF-e usa
# ICMS/IPI; NFS-e usa ISS/IR/CSLL/INSS; colunas sem valor saem "—". Retenções
# rotuladas "(destaque do emitente)" (I-2).
SPEC_INDIVIDUAL = [
    ("tipo", "Tipo", "texto"),
    ("numero", "Número", "texto"),
    ("fornecedor", "Fornecedor", "texto"),
    ("cnpj", "CNPJ", "cnpj"),
    ("valor", "Valor", "moeda"),
    ("situacao", "Situação", "texto"),
    ("valor_material", "Valor dos materiais (validado pelo operador)", "moeda"),
    ("icms_destaque_emitente", "ICMS (destaque do emitente)", "moeda"),
    ("ipi_destaque_emitente", "IPI (destaque do emitente)", "moeda"),
    ("iss_valor_destaque_emitente", "ISS (destaque do emitente)", "moeda"),
    ("ir_destaque_emitente", "IR (destaque do emitente)", "moeda"),
    ("pis_destaque_emitente", "PIS (destaque do emitente)", "moeda"),
    ("cofins_destaque_emitente", "COFINS (destaque do emitente)", "moeda"),
    ("csll_destaque_emitente", "CSLL (destaque do emitente)", "moeda"),
    ("inss_destaque_emitente", "INSS (destaque do emitente)", "moeda"),
    ("valor_liquido", "Líquido", "moeda"),
]


def _material_validado(reg, marc):
    """Valor de material VALIDADO pelo operador (da marcação, I-4) — só quando
    houve material ('sim'). Nunca a sugestão crua da máquina."""
    if reg.tipo != "NFSE":
        return None, None
    m = marc.atual(reg.chave) or {}
    return m, (m.get("valor_material") if m.get("valor") == "sim" else None)


def _linha_individual(reg, marc) -> dict:
    """Dict de uma nota para o CSV individual (espelha a lista da tela)."""
    nfse = reg.tipo == "NFSE"
    d = reg.to_dict()
    m, valor_material = _material_validado(reg, marc)
    d["fornecedor"] = reg.prest_nome if nfse else reg.emit_nome
    d["cnpj"] = reg.prest_cnpj if nfse else reg.emit_cnpj
    d["valor"] = reg.valor_servicos if nfse else reg.valor_total
    d["valor_material"] = valor_material
    partes = []
    if reg.campos_faltantes:
        partes.append("conferir: " + ", ".join(reg.campos_faltantes))
    if nfse:
        partes.append(f"material: {m['valor']}" if m else "material não conferido")
    d["situacao"] = " · ".join(partes) if partes else "pronta"
    return d


def _exportar_com_spec(cands, spec, sufixo, builder):
    """Escritor genérico: monta os dicts (builder) e grava o CSV com a `spec`."""
    def escritor(regs, lote):
        marc = StoreMarcacoes()
        try:
            dicts = [builder(r, marc) for r in regs]
        finally:
            marc.fechar()
        return ExportadorCsvLocal(PASTA_SAIDA).exportar(dicts, spec, lote, sufixo)
    return _exportar(cands, escritor)


def _persistir(resultados, npp_id=None):
    """Grava no banco os resultados de ingestão que viraram registro com chave,
    vinculando-os à NPP `npp_id` (ou soltos, no fluxo antigo). Devolve
    (importadas, [origens com erro], [(origem, npp_id_existente) em conflito]).
    Não decide nada: só transcreve o que a ingestão extraiu (I-2). Reimportar a
    mesma chave na MESMA NPP não duplica — chave é PK (I-1); em OUTRA NPP é
    conflito exibido, nunca sobrescrito em silêncio (I-1/I-6)."""
    notas = StoreNotas()
    importadas, erros, conflitos = 0, [], []
    for r in resultados:
        if r.registro and r.registro.chave and not r.erro:
            try:
                notas.salvar(r.registro.chave, r.tipo, r.registro.to_dict(),
                             r.origem, npp_id)
                importadas += 1
            except ConflitoDeChave as c:
                conflitos.append((r.origem or "(sem nome)", c.npp_id_existente))
        else:
            erros.append(r.origem or "(sem nome)")
    notas.fechar()
    return importadas, erros, conflitos


def _ingerir_uploads(arquivos):
    """Ingere uma lista de arquivos enviados pelo navegador (upload individual ou
    pasta inteira via seletor). Cada XML é salvo em área temporária e lido uma vez;
    não-XML são ignorados. Não persiste nada no disco do servidor."""
    resultados = []
    with tempfile.TemporaryDirectory() as d:
        for fs in arquivos:
            nome = secure_filename(Path(fs.filename or "").name)
            if not nome.lower().endswith(".xml"):
                continue
            caminho = Path(d) / nome
            fs.save(str(caminho))
            resultados.append(ingerir(caminho))
    return resultados


@app.route("/redefinir", methods=["GET"])
def redefinir():
    """Tela de confirmação da redefinição de dados (reset de demonstração).

    Página dedicada + frase digitada + POST são três barreiras deliberadas contra
    deleção acidental. Aqui só mostramos o que será apagado e o estado atual; nada
    é tocado num GET."""
    registro = RegistroDeExportacao()
    n_export = len(registro.listar())
    registro.fechar()
    notas = StoreNotas(); n_notas = notas.contar(); notas.fechar()
    store = StoreNPP(); n_npps = len(store.listar()); store.fechar()
    n_artefatos = len([f for f in PASTA_SAIDA.glob("*.csv")]) if PASTA_SAIDA.is_dir() else 0
    return render_template("redefinir.html", n_export=n_export, n_notas=n_notas,
                           n_npps=n_npps, n_artefatos=n_artefatos,
                           frase=redefinicao.FRASE_CONFIRMACAO)


@app.route("/redefinir", methods=["POST"])
def redefinir_executar():
    """Executa a redefinição — só se a frase de confirmação bater exatamente.

    Apaga as memórias do tronco (idempotência I-1 e marcações I-4) após copiá-las
    para um backup datado: a memória é recuperável, não some em silêncio (I-6). As
    notas dos exemplos não são tocadas — são relidas do XML e voltam a aparecer
    como pendentes."""
    confirmacao = request.form.get("confirmacao", "").strip()
    if confirmacao != redefinicao.FRASE_CONFIRMACAO:
        flash(f'Redefinição cancelada: digite exatamente "{redefinicao.FRASE_CONFIRMACAO}" '
              "para confirmar. Nada foi apagado.", "erro")
        return redirect(url_for("redefinir"))
    resumo = redefinicao.redefinir_dados()
    if resumo["apagados"] or resumo["artefatos_limpos"]:
        artef = (f" {resumo['artefatos_limpos']} artefato(s) de exportação arquivado(s)."
                 if resumo["artefatos_limpos"] else "")
        flash("Dados redefinidos: notas, memória de exportação e marcações apagadas "
              f"({', '.join(resumo['apagados'])}).{artef} Backup salvo em {resumo['backup']}. "
              "A lista está vazia — crie uma NPP e importe as notas dentro dela.", "ok")
    else:
        flash("Não havia dados a redefinir — o banco já estava vazio.", "info")
    return redirect(url_for("hub"))


# ---------- Configuração de contrato (entrada do especialista; não apura — I-3) ----------

_VOCAB_CONTRATO = {"naturezas": NATUREZAS, "categorias": CATEGORIAS,
                   "materiais": MATERIAL_PREVISAO, "bases": BASES_MINIMAS,
                   "ir_percentuais": IR_PERCENTUAIS, "inss_adicional": INSS_ADICIONAL,
                   "iss_local": ISS_LOCAL, "anexos": ["I", "II", "III", "IV", "V"],
                   # IN 1234/2012: valores de IR p/ a lista e os códigos agregados (autopreenchimento)
                   "ir_valores": tabela_in1234.IR_VALORES,
                   "codigos_in": tabela_in1234.opcoes_agregadas()}


def _contrato_do_form(form, id_=None) -> Contrato:
    """Monta um Contrato a partir do formulário. Checkbox ausente = False; o
    sistema só transcreve a configuração do especialista (não decide nada)."""
    def s(campo):
        v = (form.get(campo) or "").strip()
        return v or None
    return Contrato(
        id=id_,
        prest_identificacao=(form.get("prest_identificacao") or "").strip(),
        prest_tipo_pessoa=form.get("prest_tipo_pessoa", "PJ"),
        prest_documento=formato._digitos(form.get("prest_documento")),
        prest_natureza=form.get("prest_natureza", "nao_optante"),
        prest_simples_anexo=s("prest_simples_anexo"),
        prest_endereco=s("prest_endereco"),
        prest_municipio=s("prest_municipio"),
        prest_uf=s("prest_uf"),
        prest_im=s("prest_im"),
        numero=(form.get("numero") or "").strip(),
        ano=(form.get("ano") or "").strip(),
        vigencia_inicio=s("vigencia_inicio"),
        vigencia_fim=s("vigencia_fim"),
        objeto=s("objeto"),
        categoria_servico=form.get("categoria_servico", "geral"),
        material_previsao=form.get("material_previsao", "nao"),
        ret_federal_sujeito=form.get("ret_federal_sujeito") == "on",
        ret_federal_codigo_receita=s("ret_federal_codigo_receita"),
        ret_federal_ir_pct=s("ret_federal_ir_pct"),
        ret_federal_csll=form.get("ret_federal_csll") == "on",
        ret_federal_cofins=form.get("ret_federal_cofins") == "on",
        ret_federal_pis=form.get("ret_federal_pis") == "on",
        ret_federal_justificativa=s("ret_federal_justificativa"),
        inss_cessao_mao_obra=form.get("inss_cessao_mao_obra") == "on",
        inss_aliquota=s("inss_aliquota"),
        inss_base_minima_pct=s("inss_base_minima_pct"),
        inss_adicional_pct=s("inss_adicional_pct"),
        iss_retido_tomador=form.get("iss_retido_tomador") == "on",
        iss_aliquota=s("iss_aliquota"),
        iss_subitem_lista=s("iss_subitem_lista"),
        iss_local_incidencia=form.get("iss_local_incidencia", "estabelecimento_prestador"),
        iss_municipio=s("iss_municipio"),
        iss_deduz_material=form.get("iss_deduz_material") == "on",
        observacoes=s("observacoes"),
    )


def _catalogo_federal():
    """Carrega o catálogo de regras federais do banco (ordenado). O motor é puro: quem
    faz I/O e passa a lista é a camada de aplicação."""
    store = StoreRegrasFederais(); regras = store.listar(); store.fechar()
    return regras


def _render_contrato_form(c, novo):
    """Renderiza o form com o catálogo de regras federais para o operador SELECIONAR
    (sem sugestão automática — decisão do humano). A gravação copia o efeito da regra
    escolhida para o contrato (I-3: o sistema estrutura, não decide)."""
    return render_template("contrato_form.html", contrato=c, vocab=_VOCAB_CONTRATO,
                           novo=novo, regras_federais=_catalogo_federal())


def _aplicar_enquadramento_federal(c, form):
    """Resolve o grupo federal de `c` antes de salvar. **Seleção de regra** (padrão): copia
    o efeito da regra escolhida no catálogo (origem 'derivado', código da regra). **Ajuste
    manual**: usa as alíquotas que o operador digitou, exige justificativa e registra
    autor/data (I-4). Sem regra escolhida e sem ajuste → barrado, não chutado (I-6).
    Devolve (ok, erro)."""
    if form.get("ret_federal_ajustar") == "on":
        if not (c.ret_federal_justificativa or "").strip():
            return False, ("Justifique o ajuste manual do enquadramento federal. "
                           "Nada foi salvo.")
        c.ret_federal_origem = "ajustado"
        c.ret_federal_ajustado_por = "operador"
        c.ret_federal_ajustado_em = datetime.now(timezone.utc).isoformat()
        return True, None  # ret_federal_* já vieram do form via _contrato_do_form
    # Seleção de regra do catálogo (a tela Regras é a fonte; aqui só se escolhe).
    regra_id = (form.get("ret_federal_regra_id") or "").strip()
    if not regra_id:
        return False, ("Selecione a regra federal do catálogo (ou marque ajuste manual). "
                       "Nada foi salvo.")
    store = StoreRegrasFederais()
    try:
        regra = store.obter(int(regra_id))
    except (ValueError, TypeError):
        regra = None
    finally:
        store.fechar()
    if not regra:
        return False, "Regra federal não encontrada no catálogo. Nada foi salvo."
    c.ret_federal_regra_codigo = regra.codigo
    c.ret_federal_origem = "derivado"
    c.ret_federal_sujeito = regra.sujeito
    c.ret_federal_ir_pct = regra.ir_pct
    c.ret_federal_codigo_receita = regra.codigo_receita
    c.ret_federal_csll, c.ret_federal_cofins, c.ret_federal_pis = regra.csll, regra.cofins, regra.pis
    c.ret_federal_justificativa = None
    c.ret_federal_ajustado_por = c.ret_federal_ajustado_em = None
    return True, None


@app.route("/contratos")
def contratos():
    store = StoreContratos(); lista = store.listar(); store.fechar()
    return render_template("contratos.html", contratos=lista, vocab=_VOCAB_CONTRATO)


def _regra_do_form(form, id_=None) -> RegraEnquadramento:
    """Monta uma RegraEnquadramento a partir do formulário. A natureza do prestador é
    seleção ÚNICA (radio); categoria saiu (não é mais condição). O `codigo` é controlado
    pelo sistema (sequencial) — não vem do form em regra nova. Só guarda o que o
    especialista dita (I-3)."""
    def s(campo):
        v = (form.get(campo) or "").strip()
        return v or None
    try:
        ordem = int(form.get("ordem") or 0)
    except ValueError:
        ordem = 0
    natureza = (form.get("natureza") or "").strip()
    return RegraEnquadramento(
        id=id_,
        codigo=(form.get("codigo") or "").strip(),   # preservado em edição; em nova é gerado na rota
        descricao=(form.get("descricao") or "").strip(),
        fundamento=(form.get("fundamento") or "").strip(),
        naturezas=(natureza,) if natureza else (),
        categorias=(),                                # categoria removida das condições
        materiais=tuple(form.getlist("materiais")),
        sujeito=form.get("sujeito") == "on",
        ir_pct=s("ir_pct"),
        csll=form.get("csll") == "on",
        cofins=form.get("cofins") == "on",
        pis=form.get("pis") == "on",
        codigo_receita=s("codigo_receita"),
        ordem=ordem,
    )


@app.route("/regras")
def regras():
    """Catálogo de regras de tratamento tributário — cadastrado pelo especialista. A
    primeira regra cuja condição casar um contrato sugere o enquadramento (I-3)."""
    store = StoreRegrasFederais(); catalogo = store.listar(); store.fechar()
    return render_template("regras.html", catalogo=catalogo, vocab=_VOCAB_CONTRATO)


@app.route("/regras/nova")
def regra_nova():
    store = StoreRegrasFederais()
    ordem = store.proxima_ordem()
    codigo_previsto = store.proximo_codigo("TF")   # federal; INSS-/ISS- quando houver grupos
    store.fechar()
    nova = RegraEnquadramento(codigo="", descricao="", fundamento="", ordem=ordem)
    return render_template("regra_form.html", regra=nova, vocab=_VOCAB_CONTRATO, novo=True,
                           codigo_previsto=codigo_previsto)


@app.route("/regras/<int:id_>/editar")
def regra_editar(id_):
    store = StoreRegrasFederais(); r = store.obter(id_); store.fechar()
    if not r:
        flash("Regra não encontrada.", "erro")
        return redirect(url_for("regras"))
    return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO, novo=False,
                           codigo_previsto=r.codigo)


@app.route("/regras", methods=["POST"])
@app.route("/regras/<int:id_>", methods=["POST"])
def regra_salvar(id_=None):
    r = _regra_do_form(request.form, id_)
    store = StoreRegrasFederais()
    if id_ is None:
        r.codigo = store.proximo_codigo("TF")      # código sequencial, controlado pelo sistema
    if not r.descricao:
        store.fechar()
        flash("Informe ao menos a descrição da regra. Nada foi salvo.", "erro")
        return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO,
                               novo=(id_ is None), codigo_previsto=r.codigo)
    if r.sujeito and not r.ir_pct:
        store.fechar()
        flash("Como os tributos federais incidem nesta regra, defina o percentual de IR. "
              "Nada foi salvo.", "erro")
        return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO,
                               novo=(id_ is None), codigo_previsto=r.codigo)
    try:
        store.salvar(r)
    except Exception as exc:
        store.fechar()
        flash(f"Não foi possível salvar a regra ({type(exc).__name__}).", "erro")
        return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO,
                               novo=(id_ is None), codigo_previsto=r.codigo)
    store.fechar()
    flash(f"Regra {r.codigo} salva.", "ok")
    return redirect(url_for("regras"))


@app.route("/regras/<int:id_>/remover", methods=["POST"])
def regra_remover(id_):
    store = StoreRegrasFederais(); store.remover(id_); store.fechar()
    flash("Regra removida.", "ok")
    return redirect(url_for("regras"))


@app.route("/contratos/novo")
def contrato_novo():
    return _render_contrato_form(Contrato(), novo=True)


@app.route("/contratos/<int:id_>/editar")
def contrato_editar(id_):
    store = StoreContratos(); c = store.obter(id_); store.fechar()
    if not c:
        flash("Contrato não encontrado.", "erro")
        return redirect(url_for("contratos"))
    return _render_contrato_form(c, novo=False)


@app.route("/contratos", methods=["POST"])
@app.route("/contratos/<int:id_>", methods=["POST"])
def contrato_salvar(id_=None):
    c = _contrato_do_form(request.form, id_)
    if not c.prest_identificacao or not c.numero:
        flash("Informe ao menos a identificação do prestador e o número do contrato. "
              "Nada foi salvo.", "erro")
        return _render_contrato_form(c, novo=(id_ is None))
    ok, erro = _aplicar_enquadramento_federal(c, request.form)
    if not ok:
        flash(erro, "erro")
        return _render_contrato_form(c, novo=(id_ is None))
    store = StoreContratos()
    try:
        store.salvar(c)
    except Exception as exc:
        store.fechar()
        flash(f"Não foi possível salvar: já existe contrato com este prestador, número "
              f"e ano? ({type(exc).__name__}).", "erro")
        return _render_contrato_form(c, novo=(id_ is None))
    store.fechar()
    flash(f"Contrato {c.numero}/{c.ano} de {c.prest_identificacao} salvo.", "ok")
    return redirect(url_for("contratos"))


@app.route("/contratos/<int:id_>/remover", methods=["POST"])
def contrato_remover(id_):
    store = StoreContratos(); store.remover(id_); store.fechar()
    flash("Contrato removido.", "ok")
    return redirect(url_for("contratos"))


# ---------- Cadastro do operador (bootstrap; I-4) ----------

@app.route("/operador", methods=["GET"])
def operador_cadastro():
    """Tela de identidade do operador. Na 1ª execução é o destino do desvio; depois,
    acessível pelo rodapé para reidentificar a máquina."""
    return render_template("operador_form.html", operador=_operador_atual())


@app.route("/operador", methods=["POST"])
def operador_salvar():
    """Grava a identidade (iniciais + nome). Entradas inválidas são barradas com
    mensagem (I-6) — nunca se inventa identidade."""
    iniciais = request.form.get("iniciais", "")
    nome = request.form.get("nome", "")
    op = StoreOperador()
    try:
        salvo = op.salvar(iniciais, nome)
    except ValueError as exc:
        op.fechar()
        flash(f"Não foi possível salvar a identidade: {exc}. Nada foi gravado.", "erro")
        return render_template("operador_form.html",
                               operador=Operador(iniciais=iniciais, nome=nome))
    op.fechar()
    flash(f"Identidade registrada: {salvo.nome} ({salvo.iniciais}).", "ok")
    return redirect(url_for("hub"))


# ---------- NPP — Nota de Pré-Pagamento (jornada nova) ----------
# Cada pagamento é uma NPP (um contrato, uma competência, 1+ notas). A importação
# acontece DENTRO da NPP; não existe nota solta neste fluxo. O fluxo antigo
# (individual/consolidado) segue de pé até a etapa 7c.

def _itens_da_npp(npp_id):
    """Notas vinculadas à NPP, já reconstruídas, com valor (por tipo) e situação de
    exportação. Base das seções da tela e dos totais derivados."""
    notas = StoreNotas(); persistidas = notas.listar_por_npp(npp_id); notas.fechar()
    registro = RegistroDeExportacao()
    itens = []
    for n in persistidas:
        reg = reconstruir(n["tipo"], n["dados"])
        itens.append({"reg": reg, "tipo": n["tipo"], "origem": n["origem"],
                      "ja_exportada": registro.ja_exportada(reg.chave),
                      "valor": reg.valor_total if n["tipo"] == "NFE" else reg.valor_servicos})
    registro.fechar()
    return itens


def _npp_status(itens):
    """Status derivado das notas (não armazenado): vazia / aberta (tem inédita) /
    exportada (todas já saíram em lote)."""
    if not itens:
        return "vazia"
    return "exportada" if all(i["ja_exportada"] for i in itens) else "aberta"


def _competencia_valida(s):
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", (s or "").strip()))


# ---- Seção 2 (Grupos de impostos): a fronteira I-2/I-3/I-4 ----
# Três camadas explicitamente separadas: destaque do emitente (Fase 1, fiel),
# sugestão da regra (Fase 2, só exibição) e validação humana (Fase 2, a única gravada).
_CATEGORIA = {"INSS": "prev", "IR": "federal", "CSLL": "federal",
              "COFINS": "federal", "PIS": "federal", "ISS": "iss"}
_GRUPOS_META = [("Contribuição previdenciária", "prev"),
                ("Tributos federais", "federal"),
                ("ISS", "iss")]


def _conferir_por_tipo(reg, tipo, contrato, material_marcado=None):
    """Despacha a conferência pelo tipo da nota (galhos independentes), com o contrato
    vindo da NPP — sem heurística de CNPJ. Só sugestão (I-3); não grava nada."""
    if tipo == "NFE":
        from galho_nfe import retencao as ret_nfe
        return ret_nfe.conferir_retencao(reg, contrato, material_marcado)
    return retencao.conferir_retencao(reg, contrato, material_marcado)


def _material_marcado(chave, tipo, marc):
    return (marc.atual(chave) or {}).get("valor") if tipo == "NFSE" else None


def _pendente_validacao(achado, validacao) -> bool:
    """Tributo aplicável que ainda falta validar e que pode render retenção > 0 — deixa
    o líquido provisório (I-6). Já validado, ou sugestão zero (não incide/dispensado),
    não pendura o líquido."""
    if validacao is not None:
        return False
    if achado.esperado is None:        # indefinido (ex.: material/regime) → atenção
        return True
    try:
        return Decimal(achado.esperado) != 0
    except (InvalidOperation, ValueError):
        return True


def _grupos_impostos(itens, contrato, val_store=None, marc=None):
    """Monta as 3 categorias da Seção 2 (linha por nota×tributo aplicável), o total
    retido (Σ validados) e se o líquido é provisório (há tributo a validar). Stores
    injetáveis para teste; abertos/fechados aqui por padrão."""
    fechar_v, fechar_m = val_store is None, marc is None
    val_store = val_store or StoreValidacaoRetencao()
    marc = marc or StoreMarcacoes()
    try:
        cats = {"prev": [], "federal": [], "iss": []}
        total_retido = Decimal("0")
        ha_pendente = False
        for it in itens:
            reg, tipo = it["reg"], it["tipo"]
            if not contrato:
                continue
            material = _material_marcado(reg.chave, tipo, marc)
            achados = _conferir_por_tipo(reg, tipo, contrato, material).achados
            vals = val_store.atuais(reg.chave)
            for a in achados:
                v = vals.get(a.tributo)
                if v is not None:
                    try:
                        total_retido += Decimal(v["valor"])
                    except (InvalidOperation, ValueError):
                        pass
                pendente = _pendente_validacao(a, v)
                ha_pendente = ha_pendente or pendente
                cats[_CATEGORIA[a.tributo]].append({
                    "nota_numero": reg.numero, "chave": reg.chave, "tipo": tipo,
                    "tributo": a.tributo, "regra": a.regra,
                    "destaque": a.destaque_emitente, "esperado": a.esperado,
                    "validacao": v, "pendente": pendente,
                })
        grupos = []
        for label, key in _GRUPOS_META:
            rows = cats[key]
            tot = Decimal("0")
            for r in rows:
                if r["validacao"] is not None:
                    try:
                        tot += Decimal(r["validacao"]["valor"])
                    except (InvalidOperation, ValueError):
                        pass
            grupos.append({"label": label, "rows": rows, "total_validado": f"{tot:.2f}"})
        return grupos, f"{total_retido:.2f}", ha_pendente
    finally:
        if fechar_v:
            val_store.fechar()
        if fechar_m:
            marc.fechar()


def _rotulos_contratos(contratos):
    return {c.id: retencao.rotulo_contrato(c) for c in contratos}


@app.route("/npps")
def npps():
    """Lista de NPPs (abertas, vazias e exportadas), com contrato, competência,
    contagem e valor bruto."""
    store = StoreNPP(); lista = store.listar(); store.fechar()
    cstore = StoreContratos()
    por_id = {c.id: c for c in cstore.listar()}
    cstore.fechar()
    cards = []
    for npp in lista:
        itens = _itens_da_npp(npp.id)
        c = por_id.get(npp.contrato_id)
        cards.append({
            "npp": npp,
            "contrato_rotulo": retencao.rotulo_contrato(c) if c else "(contrato removido)",
            "n": len(itens),
            "novas": sum(1 for i in itens if not i["ja_exportada"]),
            "total": _bruto(itens),
            "status": _npp_status(itens),
        })
    return render_template("npps.html", cards=cards)


@app.route("/npps/nova")
def npp_nova():
    cstore = StoreContratos(); contratos = cstore.listar(); cstore.fechar()
    return render_template("npp_form.html", npp=NPP(), contratos=contratos,
                           rotulos=_rotulos_contratos(contratos), novo=True)


@app.route("/npps", methods=["POST"])
def npp_criar():
    """Cria a NPP (contrato + competência + rótulo/observações). O `numero` é gerado
    com as iniciais do operador (I-4). Sem contrato ou competência válida → barrado (I-6)."""
    try:
        contrato_id = int(request.form.get("contrato_id") or 0)
    except ValueError:
        contrato_id = 0
    competencia = (request.form.get("competencia") or "").strip()
    rotulo = (request.form.get("rotulo") or "").strip() or None
    observacoes = (request.form.get("observacoes") or "").strip() or None
    cstore = StoreContratos()
    contrato = cstore.obter(contrato_id) if contrato_id else None
    erro = None
    if not contrato:
        erro = "Escolha um contrato para a NPP."
    elif not _competencia_valida(competencia):
        erro = "Informe a competência no formato AAAA-MM."
    if erro:
        contratos = cstore.listar(); cstore.fechar()
        flash(erro + " Nada foi criado.", "erro")
        return render_template("npp_form.html",
                               npp=NPP(contrato_id=contrato_id, competencia=competencia,
                                       rotulo=rotulo, observacoes=observacoes),
                               contratos=contratos,
                               rotulos=_rotulos_contratos(contratos), novo=True)
    cstore.fechar()
    op = _operador_atual()
    store = StoreNPP()
    try:
        npp = store.criar(contrato_id=contrato.id, competencia=competencia,
                          iniciais=op.iniciais, autor=op.nome,
                          rotulo=rotulo, observacoes=observacoes)
    finally:
        store.fechar()
    flash(f"NPP {npp.numero} criada. Importe as notas dentro dela.", "ok")
    return redirect(url_for("npp_detalhe", id_=npp.id))


def _obter_npp(id_):
    store = StoreNPP(); npp = store.obter(id_); store.fechar()
    return npp


def _liquido_npp(total_bruto, total_retido):
    """Líquido = bruto − retido validado (decimal canônico). Aritmética de apresentação
    sobre valores já existentes — não é apuração de retenção (a retenção é a validada
    pelo operador, I-3/I-4)."""
    try:
        return f"{Decimal(total_bruto or '0') - Decimal(total_retido or '0'):.2f}"
    except (InvalidOperation, ValueError):
        return None


@app.route("/npp/<int:id_>")
def npp_detalhe(id_):
    """Detalhe da NPP: cabeçalho derivado + Documentos de origem (Seção 1) + Grupos de
    impostos (Seção 2: destaque fiel I-2 + sugestão I-3 + validação humana I-4)."""
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    cstore = StoreContratos(); contrato = cstore.obter(npp.contrato_id); cstore.fechar()
    itens = _itens_da_npp(id_)
    total_bruto = _bruto(itens)
    grupos, total_retido, liquido_provisorio = _grupos_impostos(itens, contrato)
    return render_template(
        "npp.html", npp=npp, contrato=contrato,
        contrato_rotulo=retencao.rotulo_contrato(contrato) if contrato else "(contrato removido)",
        itens=itens, total_bruto=total_bruto, status=_npp_status(itens),
        n_novas=sum(1 for i in itens if not i["ja_exportada"]),
        grupos=grupos, total_retido=total_retido,
        liquido=_liquido_npp(total_bruto, total_retido),
        liquido_provisorio=liquido_provisorio)


@app.route("/npp/<int:id_>/editar")
def npp_editar(id_):
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    cstore = StoreContratos(); contratos = cstore.listar(); cstore.fechar()
    return render_template("npp_form.html", npp=npp, contratos=contratos,
                           rotulos=_rotulos_contratos(contratos), novo=False)


@app.route("/npp/<int:id_>", methods=["POST"])
def npp_salvar(id_):
    """Atualiza competência/rótulo/observações. O `numero` e o contrato são imutáveis
    após a criação (identidade da NPP)."""
    store = StoreNPP(); npp = store.obter(id_)
    if not npp:
        store.fechar()
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    competencia = (request.form.get("competencia") or "").strip()
    if not _competencia_valida(competencia):
        store.fechar()
        flash("Informe a competência no formato AAAA-MM. Nada foi salvo.", "erro")
        return redirect(url_for("npp_editar", id_=id_))
    npp.competencia = competencia
    npp.rotulo = (request.form.get("rotulo") or "").strip() or None
    npp.observacoes = (request.form.get("observacoes") or "").strip() or None
    store.salvar(npp); store.fechar()
    flash(f"NPP {npp.numero} atualizada.", "ok")
    return redirect(url_for("npp_detalhe", id_=id_))


@app.route("/npp/<int:id_>/remover", methods=["POST"])
def npp_remover(id_):
    """Remove a NPP — só se estiver vazia. Com notas vinculadas, barra com mensagem
    (I-6): não deixa nota órfã nem apaga nota em silêncio."""
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    itens = _itens_da_npp(id_)
    if itens:
        flash(f"A NPP {npp.numero} tem {len(itens)} nota(s) vinculada(s); ela não pode "
              "ser removida com notas dentro. Nada foi removido.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    store = StoreNPP(); store.remover(id_); store.fechar()
    flash(f"NPP {npp.numero} removida.", "ok")
    return redirect(url_for("npps"))


def _divergencias_cnpj(resultados, contrato):
    """Origens cujo CNPJ (prestador da NFS-e / emitente da NF-e) diverge do prestador
    do contrato da NPP. Heads-up visível (I-6) — não bloqueia a importação."""
    if not contrato:
        return []
    doc_c = formato._digitos(contrato.prest_documento)
    if not doc_c:
        return []
    out = []
    for r in resultados:
        reg = r.registro
        if not reg or r.erro:
            continue
        doc_n = formato._digitos(reg.prest_cnpj if r.tipo == "NFSE" else reg.emit_cnpj)
        if doc_n and doc_n != doc_c:
            out.append(r.origem or getattr(reg, "numero", None) or "(sem nome)")
    return out


def _persistir_na_npp(resultados, npp):
    """Grava os resultados na NPP e monta o feedback: importadas, conflitos de chave
    com outra NPP (I-1/I-6), divergências de CNPJ (I-6) e arquivos não reconhecidos."""
    cstore = StoreContratos(); contrato = cstore.obter(npp.contrato_id); cstore.fechar()
    importadas, erros, conflitos = _persistir(resultados, npp.id)
    divergentes = _divergencias_cnpj(resultados, contrato)
    partes = []
    if importadas:
        partes.append(f"{importadas} nota(s) importada(s) na NPP {npp.numero}.")
    if conflitos:
        det = "; ".join(f"{o} (já consta na NPP nº {nid})" for o, nid in conflitos)
        partes.append(f"{len(conflitos)} nota(s) já constam em outra NPP, não movidas: {det}.")
    if divergentes:
        partes.append("Atenção — CNPJ diverge do prestador do contrato em: "
                      + ", ".join(divergentes) + " (confira o vínculo).")
    if erros:
        partes.append(f"{len(erros)} arquivo(s) não reconhecido(s): {', '.join(erros)}.")
    if not partes:
        flash("Nada foi importado.", "erro")
        return
    cat = "erro" if (conflitos or erros) else ("ok" if importadas else "info")
    flash(" ".join(partes), cat)


@app.route("/npp/<int:id_>/importar/arquivo", methods=["POST"])
def npp_importar_arquivo(id_):
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo XML para importar. Nada foi importado.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    nome = secure_filename(Path(arquivo.filename).name) or "nota.xml"
    if not nome.lower().endswith(".xml"):
        flash(f"'{arquivo.filename}' não é um arquivo .xml. Nada foi importado.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    with tempfile.TemporaryDirectory() as d:
        caminho = Path(d) / nome
        arquivo.save(str(caminho))
        resultado = ingerir(caminho)
    _persistir_na_npp([resultado], npp)
    return redirect(url_for("npp_detalhe", id_=id_))


@app.route("/npp/<int:id_>/importar/pasta", methods=["POST"])
def npp_importar_pasta(id_):
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    arquivos = [f for f in request.files.getlist("arquivos") if f and f.filename]
    if not arquivos:
        flash("Selecione uma pasta com arquivos XML. Nada foi importado.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    resultados = _ingerir_uploads(arquivos)
    if not resultados:
        flash("A pasta selecionada não tem arquivos .xml. Nada foi importado.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    _persistir_na_npp(resultados, npp)
    return redirect(url_for("npp_detalhe", id_=id_))


def _nota_item_da_npp(id_, chave):
    for it in _itens_da_npp(id_):
        if it["reg"].chave == chave:
            return it
    return None


@app.route("/npp/<int:id_>/validar/<chave>/<tributo>", methods=["POST"])
def npp_validar(id_, chave, tributo):
    """Grava a validação de retenção do operador para um tributo de uma nota (Fase 2,
    validação humana; I-3/I-4). *Confirmar* atesta o destaque do emitente (recomputado
    no servidor, nunca o valor da tela). *Retificar* usa o valor digitado pelo operador —
    o sistema NUNCA pré-preenche esse campo com a sugestão da regra (linha vermelha I-3)."""
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    item = _nota_item_da_npp(id_, chave)
    if not item:
        flash("Nota não encontrada nesta NPP.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    cstore = StoreContratos(); contrato = cstore.obter(npp.contrato_id); cstore.fechar()
    if not contrato:
        flash("A NPP não tem contrato — não há regra para validar.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    marc = StoreMarcacoes()
    material = _material_marcado(chave, item["tipo"], marc)
    marc.fechar()
    achados = {a.tributo: a
               for a in _conferir_por_tipo(item["reg"], item["tipo"], contrato, material).achados}
    achado = achados.get(tributo)
    if achado is None:
        flash(f"O tributo {tributo} não se aplica a esta nota — nada a validar (I-6).", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    acao = request.form.get("acao")
    if acao == "confirmado":
        valor = achado.destaque_emitente
        if valor is None:
            flash(f"{tributo}: a nota não traz destaque para confirmar — use Retificar e "
                  "informe o valor.", "erro")
            return redirect(url_for("npp_detalhe", id_=id_))
    elif acao == "retificado":
        valor = request.form.get("valor")
    else:
        flash("Ação inválida (use confirmar ou retificar).", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    op = _operador_atual()
    store = StoreValidacaoRetencao()
    try:
        reg_val = store.validar(chave, tributo, acao, valor, op.nome)
    except ValueError as exc:
        store.fechar()
        flash(f"Não foi possível validar {tributo}: {exc}. Nada foi gravado.", "erro")
        return redirect(url_for("npp_detalhe", id_=id_))
    store.fechar()
    flash(f"{tributo} {acao}: {formato.moeda(reg_val['valor'])} (por {op.nome}).", "ok")
    return redirect(url_for("npp_detalhe", id_=id_))


@app.route("/npp/<int:id_>/importar/exemplos", methods=["POST"])
def npp_importar_exemplos(id_):
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    _persistir_na_npp(list(ingerir_pasta(PASTA_EXEMPLOS)), npp)
    return redirect(url_for("npp_detalhe", id_=id_))


@app.route("/npp/<int:id_>/exportar", methods=["POST"])
def npp_exportar(id_):
    """Exporta as notas INÉDITAS da NPP num lote (I-1: idempotência por chave via
    RegistroDeExportacao; I-5: artefato novo append-only). Reusa o SPEC_INDIVIDUAL,
    que já cobre NF-e e NFS-e na mesma tabela — uma NPP mista exporta os dois tipos
    no mesmo artefato, cada nota com as colunas do seu tipo. Valores rotulados
    'destaque do emitente' (I-2); a validação humana é exibida na tela da NPP."""
    npp = _obter_npp(id_)
    if not npp:
        flash("NPP não encontrada.", "erro")
        return redirect(url_for("npps"))
    cands = [it["reg"] for it in _itens_da_npp(id_) if not it["ja_exportada"]]
    flash(*_exportar_com_spec(cands, SPEC_INDIVIDUAL, npp.numero, _linha_individual))
    return redirect(url_for("npp_detalhe", id_=id_))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
