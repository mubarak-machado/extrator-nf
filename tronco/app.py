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
from tronco.notas import StoreNotas, reconstruir
from tronco.contratos import (StoreContratos, Contrato,
                              NATUREZAS, CATEGORIAS, MATERIAL_PREVISAO, BASES_MINIMAS,
                              IR_PERCENTUAIS, INSS_ADICIONAL, ISS_LOCAL)
from tronco.exportador import ExportadorCsvLocal, novo_lote_id
from tronco import formato, redefinicao, config
from galho_nfse.modelo import RegistroNFSe
from galho_nfse.material import sugerir_material
from galho_nfse import retencao, enquadramento
from galho_nfse.enquadramento import RegraEnquadramento
from galho_nfse.catalogo_federal import StoreRegrasFederais

# Recursos (templates/static/exemplos) são só-leitura e vivem junto do código; as
# exportações precisam de lugar gravável e persistente. Empacotado (PyInstaller),
# esses lugares divergem — ver tronco/config.py.
RECURSOS = config.raiz_recursos()
PASTA_EXEMPLOS = RECURSOS / "exemplos"
PASTA_SAIDA = config.diretorio_dados() / "exportacoes"

app = Flask(__name__,
            template_folder=str(RECURSOS / "templates"),
            static_folder=str(RECURSOS / "static"))
app.secret_key = config.chave_secreta()

for nome in ("moeda", "numero", "data", "datahora", "competencia",
             "cnpj", "percent", "chave", "simnao"):
    app.jinja_env.filters[nome] = getattr(formato, nome)

# Teste Jinja: `{{ valor is ezero }}` atenua (não esconde) valores zerados.
app.jinja_env.tests["ezero"] = formato.ezero


def _soma(regs, attr):
    """Soma um atributo numérico (apresentação). NÃO é apuração: é só o
    somatório dos valores transcritos do XML."""
    total = Decimal("0"); achou = False
    for r in regs:
        v = getattr(r, attr, None)
        if v in (None, ""):
            continue
        try:
            total += Decimal(str(v)); achou = True
        except (InvalidOperation, ValueError):
            continue
    return f"{total:.2f}" if achou else None


def _com_atencao(item) -> bool:
    r = item["reg"]
    if not r:
        return bool(item["erro"])
    if getattr(r, "campos_faltantes", None):
        return True
    if item["tipo"] == "NFSE" and not item["marcacao"]:
        return True
    return False


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
                "ja_exportada": registro.ja_exportada(reg.chave),
                "marcacao": None,
                "valor": reg.valor_total if n["tipo"] == "NFE" else reg.valor_servicos}
        if n["tipo"] == "NFSE":
            item["marcacao"] = marc.atual(reg.chave)
        linhas.append(item)
    registro.fechar(); marc.fechar()
    return linhas


def _grupos(linhas):
    """Agrupa NFS-e por (prestador, competência). Grupos com >1 nota são
    'consolidações sugeridas' (serviço continuado em vários municípios).

    ATENÇÃO: o vínculo real é o CONTRATO, que não vem no XML. Isto é uma
    heurística (mesmo prestador + mesma competência) exibida para o humano
    conferir — nunca tratada como verdade contratual."""
    g = defaultdict(list)
    for it in linhas:
        r = it["reg"]
        if it["tipo"] == "NFSE" and r and r.prest_cnpj and r.competencia:
            g[(r.prest_cnpj, r.competencia)].append(it)
    return g


def _chaves_consolidadas(linhas):
    """Chaves das notas que caem num grupo de consolidação (>1 nota). Tudo que
    não está aqui é tratado como nota individual/avulsa. Nunca misturamos
    contratos diferentes: cada grupo é um pagamento; as avulsas são lançadas
    uma a uma."""
    chaves = set()
    for its in _grupos(linhas).values():
        if len(its) > 1:
            chaves.update(it["reg"].chave for it in its)
    return chaves


def _bruto(itens):
    total = Decimal("0")
    for it in itens:
        try:
            total += Decimal(str(it["valor"])) if it["valor"] else Decimal("0")
        except (InvalidOperation, ValueError):
            pass
    return f"{total:.2f}"


def _resumo_consolidacoes(linhas, so_pendentes=True):
    """Cartões de consolidação (1 por contrato sugerido). Por padrão lista só os
    grupos que ainda têm nota inédita — o que já foi exportado vive no Histórico."""
    out = []
    for (cnpj, comp), its in _grupos(linhas).items():
        if len(its) <= 1:
            continue
        novas = sum(1 for i in its if not i["ja_exportada"])
        if so_pendentes and not novas:
            continue
        out.append({"prest_cnpj": cnpj, "competencia": comp,
                    "prest_nome": its[0]["reg"].prest_nome, "n": len(its),
                    "novas": novas,
                    "total": _soma([i["reg"] for i in its], "valor_servicos")})
    out.sort(key=lambda c: (c["prest_nome"] or "", c["competencia"] or ""))
    return out


@app.route("/")
def hub():
    """Entrada: hub com os três módulos. Não despeja a lista de notas —
    mostra contagem e valor pendente de cada módulo, e o usuário entra no que
    for trabalhar (avulsa ou consolidado) ou consulta o histórico."""
    linhas = _carregar()
    cons_chaves = _chaves_consolidadas(linhas)
    individuais = [it for it in linhas
                   if it["erro"] or (it["reg"] and it["reg"].chave not in cons_chaves)]
    ind_pend = [it for it in individuais if it["reg"] and not it["ja_exportada"]]
    consolidacoes = _resumo_consolidacoes(linhas)
    registro = RegistroDeExportacao()
    exportadas = registro.listar()
    registro.fechar()
    cards = {
        "ind_pend": len(ind_pend),
        "ind_atencao": sum(1 for it in individuais if _com_atencao(it)),
        "ind_valor": _bruto(ind_pend),
        "cons_contratos": len(consolidacoes),
        "cons_novas": sum(c["novas"] for c in consolidacoes),
        "cons_valor": _soma([i["reg"] for c in consolidacoes
                             for i in _grupos(linhas)[(c["prest_cnpj"], c["competencia"])]
                             if not i["ja_exportada"]], "valor_servicos"),
        "hist_total": len(exportadas),
        "sem_notas": not linhas,
    }
    return render_template("hub.html", cards=cards)


@app.route("/individuais")
def individuais():
    """Notas avulsas pendentes (NF-e + NFS-e fora de consolidação). Triagem por
    atenção, busca e ordenação. As já exportadas saem daqui e vão ao Histórico."""
    linhas = _carregar()
    cons_chaves = _chaves_consolidadas(linhas)
    itens = [it for it in linhas
             if it["erro"] or (it["reg"] and it["reg"].chave not in cons_chaves
                               and not it["ja_exportada"])]
    pendentes = [it for it in itens if it["reg"]]
    kpis = {
        "ineditas": len(pendentes),
        "prontas": sum(1 for it in pendentes if not _com_atencao(it)),
        "atencao": sum(1 for it in itens if _com_atencao(it)),
        "valor_inedito": _bruto(pendentes),
    }
    return render_template("individuais.html", linhas=itens, kpis=kpis)


@app.route("/consolidados")
def consolidados():
    """Lista de pagamentos consolidados pendentes (1 cartão por contrato sugerido)."""
    linhas = _carregar()
    consolidacoes = _resumo_consolidacoes(linhas)
    total = _soma([i["reg"] for c in consolidacoes
                   for i in _grupos(linhas)[(c["prest_cnpj"], c["competencia"])]
                   if not i["ja_exportada"]], "valor_servicos")
    return render_template("consolidados.html", consolidacoes=consolidacoes,
                           total_pendente=total)


@app.route("/historico")
def historico():
    """Notas já exportadas (registro de idempotência), agrupadas por lote. É o
    'feito': consulta, não some, e impede pagamento em duplicidade (I-1)."""
    linhas = _carregar()
    por_chave = {it["reg"].chave: it for it in linhas if it["reg"]}
    registro = RegistroDeExportacao()
    exportadas = registro.listar()
    registro.fechar()
    lotes = defaultdict(list)
    for e in exportadas:
        it = por_chave.get(e["chave"])
        r = it["reg"] if it else None
        lotes[e["lote_id"]].append({
            "chave": e["chave"], "tipo": e["tipo"], "exportado_em": e["exportado_em"],
            "numero": getattr(r, "numero", None),
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


@app.route("/consolidado/<prest_cnpj>/<competencia>")
def consolidado(prest_cnpj, competencia):
    linhas = _carregar()
    itens = _grupos(linhas).get((prest_cnpj, competencia), [])
    if not itens:
        flash("Consolidação não encontrada.", "erro")
        return redirect(url_for("consolidados"))
    regs = [it["reg"] for it in itens]
    totais = {a: _soma(regs, a) for a in (
        "valor_servicos", "iss_valor_destaque_emitente", "ir_destaque_emitente",
        "pis_destaque_emitente", "cofins_destaque_emitente",
        "csll_destaque_emitente", "inss_destaque_emitente", "valor_liquido")}
    novas = sum(1 for it in itens if not it["ja_exportada"])
    return render_template("consolidado.html", itens=itens, regs=regs,
                           prest_cnpj=prest_cnpj, competencia=competencia,
                           prest_nome=regs[0].prest_nome, totais=totais, novas=novas)
    # nota: a navegação "voltar" deste detalhe é o módulo Consolidados.


@app.route("/nota/<chave>")
def detalhe(chave):
    for item in _carregar():
        if item["reg"] and item["reg"].chave == chave:
            # Sugestão de material a partir do texto livre — apenas SUGESTÃO, que
            # o operador vê ao lado do texto original e valida/edita (I-2/I-3).
            sugestao = (sugerir_material(item["reg"].discriminacao)
                        if item["tipo"] == "NFSE" else None)
            conf = _conferencia(item) if item["tipo"] == "NFSE" else None
            return render_template("detalhe.html", item=item, sugestao=sugestao, conf=conf)
    flash("Nota não encontrada.", "erro")
    return redirect(url_for("hub"))


def _conferencia(item):
    """Confere a NFS-e contra a regra do contrato casado por CNPJ (Fase 2 — sugestão,
    nunca decisão; I-3). Devolve o estado para a tela tratar 0/1/vários contratos
    (I-6). Read-only: não grava nada."""
    store = StoreContratos()
    casados = retencao.casar_contratos(item["reg"], store.listar())
    store.fechar()
    if not casados:
        return {"estado": "sem_contrato"}
    if len(casados) > 1:
        return {"estado": "varios",
                "rotulos": [retencao.rotulo_contrato(c) for c in casados]}
    marcado = item["marcacao"].valor if item["marcacao"] else None
    contrato = casados[0]
    resultado = retencao.conferir_retencao(item["reg"], contrato, marcado)
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


def _linha_consolidada(reg, marc) -> dict:
    """Dict de uma NFS-e para o CSV consolidado (espelha a tabela da tela) + o
    valor de material validado pelo operador injetado."""
    d = reg.to_dict()
    _, d["valor_material"] = _material_validado(reg, marc)
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


@app.route("/exportar", methods=["POST"])
def exportar():
    """Padrão INDIVIDUAL: notas avulsas inéditas (não as de consolidação — cada
    contrato é exportado pelo seu próprio botão, para nunca misturar contratos)."""
    linhas = _carregar()
    cons_chaves = _chaves_consolidadas(linhas)
    cands = [it["reg"] for it in linhas
             if it["reg"] and not it["ja_exportada"] and not it["erro"]
             and it["reg"].chave not in cons_chaves]
    flash(*_exportar_com_spec(cands, SPEC_INDIVIDUAL, "individual", _linha_individual))
    return redirect(url_for("individuais"))


@app.route("/exportar_grupo/<prest_cnpj>/<competencia>", methods=["POST"])
def exportar_grupo(prest_cnpj, competencia):
    """Padrão CONSOLIDADO: uma linha por NFS-e do contrato, espelhando a tabela da
    tela + o valor de material validado."""
    linhas = _carregar()
    itens = _grupos(linhas).get((prest_cnpj, competencia), [])
    cands = [it["reg"] for it in itens if not it["ja_exportada"] and not it["erro"]]
    flash(*_exportar_com_spec(cands, RegistroNFSe.EXPORT_SPEC_CONSOLIDADO,
                              "consolidado", _linha_consolidada))
    return redirect(url_for("consolidado", prest_cnpj=prest_cnpj, competencia=competencia))


def _persistir(resultados):
    """Grava no banco os resultados de ingestão que viraram registro com chave.
    Devolve (importadas, [origens com erro]). Não decide nada: só transcreve o
    que a ingestão extraiu (I-2). Reimportar não duplica — chave é PK (I-1)."""
    notas = StoreNotas()
    importadas, erros = 0, []
    for r in resultados:
        if r.registro and r.registro.chave and not r.erro:
            notas.salvar(r.registro.chave, r.tipo, r.registro.to_dict(), r.origem)
            importadas += 1
        else:
            erros.append(r.origem or "(sem nome)")
    notas.fechar()
    return importadas, erros


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


@app.route("/importar", methods=["GET"])
def importar():
    """Tela de importação manual, com duas opções: uma nota (upload de um XML) ou
    uma pasta inteira. O app nunca importa sozinho — a leitura de XML só acontece
    quando o usuário aciona aqui."""
    notas = StoreNotas(); n = notas.contar(); notas.fechar()
    return render_template("importar.html", n_notas=n,
                           pasta_padrao=str(PASTA_EXEMPLOS))


@app.route("/importar/arquivo", methods=["POST"])
def importar_arquivo():
    """Importação individual: recebe um XML enviado pelo usuário, lê uma vez e
    grava. Falha de reconhecimento é exibida com a mensagem da ingestão (I-6)."""
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo XML para importar. Nada foi importado.", "erro")
        return redirect(url_for("importar"))
    nome = secure_filename(Path(arquivo.filename).name) or "nota.xml"
    if not nome.lower().endswith(".xml"):
        flash(f"'{arquivo.filename}' não é um arquivo .xml. Nada foi importado.", "erro")
        return redirect(url_for("importar"))
    with tempfile.TemporaryDirectory() as d:
        caminho = Path(d) / nome
        arquivo.save(str(caminho))
        resultado = ingerir(caminho)          # leitura única, como na pasta
    importadas, _ = _persistir([resultado])
    if importadas:
        flash(f"Nota '{nome}' importada e gravada no banco.", "ok")
    else:
        flash(f"'{nome}' não foi importada: {resultado.erro or 'não reconhecida'}.", "erro")
    return redirect(url_for("hub"))


@app.route("/importar/pasta", methods=["POST"])
def importar_pasta():
    """Importação em lote: recebe os arquivos da pasta escolhida no seletor do
    navegador, lê cada XML uma vez e grava. Não-XML e arquivos não reconhecidos
    são reportados, não engolidos (I-6)."""
    arquivos = [f for f in request.files.getlist("arquivos") if f and f.filename]
    if not arquivos:
        flash("Selecione uma pasta com arquivos XML. Nada foi importado.", "erro")
        return redirect(url_for("importar"))
    resultados = _ingerir_uploads(arquivos)
    if not resultados:
        flash("A pasta selecionada não tem arquivos .xml. Nada foi importado.", "erro")
        return redirect(url_for("importar"))
    importadas, erros = _persistir(resultados)
    msg = f"Importação concluída: {importadas} nota(s) gravada(s) no banco."
    if erros:
        msg += (f" {len(erros)} arquivo(s) não reconhecido(s), ignorado(s): "
                f"{', '.join(erros)}.")
    flash(msg, "ok" if importadas else "erro")
    return redirect(url_for("hub"))


@app.route("/importar/exemplos", methods=["POST"])
def importar_exemplos():
    """Atalho de demonstração: importa a pasta de exemplos que acompanha o
    projeto (caminho conhecido no servidor), sem o usuário ter de localizá-la."""
    importadas, erros = _persistir(ingerir_pasta(PASTA_EXEMPLOS))
    flash(f"Exemplos do projeto importados: {importadas} nota(s) gravada(s).",
          "ok" if importadas else "erro")
    return redirect(url_for("hub"))


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
    n_artefatos = len([f for f in PASTA_SAIDA.glob("*.csv")]) if PASTA_SAIDA.is_dir() else 0
    return render_template("redefinir.html", n_export=n_export, n_notas=n_notas,
                           n_artefatos=n_artefatos, frase=redefinicao.FRASE_CONFIRMACAO)


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
              "A lista está vazia — use Importar para carregar as notas de novo.", "ok")
    else:
        flash("Não havia dados a redefinir — o banco já estava vazio.", "info")
    return redirect(url_for("hub"))


# ---------- Configuração de contrato (entrada do especialista; não apura — I-3) ----------

_VOCAB_CONTRATO = {"naturezas": NATUREZAS, "categorias": CATEGORIAS,
                   "materiais": MATERIAL_PREVISAO, "bases": BASES_MINIMAS,
                   "ir_percentuais": IR_PERCENTUAIS, "inss_adicional": INSS_ADICIONAL,
                   "iss_local": ISS_LOCAL, "anexos": ["I", "II", "III", "IV", "V"]}


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
    """Renderiza o form já com a regra federal derivada das características de `c`
    (catálogo cadastrado na tela Regras). A derivação é pura e só sugere — a gravação
    é da rota (I-3)."""
    sug = enquadramento.aplicar_catalogo_federal(c, _catalogo_federal())
    return render_template("contrato_form.html", contrato=c, vocab=_VOCAB_CONTRATO,
                           novo=novo, sugestao_federal=sug)


def _aplicar_enquadramento_federal(c, form):
    """Resolve o grupo federal de `c` antes de salvar. Sem ajuste manual: grava o
    enquadramento da regra casada no catálogo (origem 'derivado', código da regra). Com
    ajuste manual: mantém o que o operador preencheu, exige justificativa e registra
    autor/data (I-4). Indefinido sem ajuste é barrado, não chutado (I-6).
    Devolve (ok, erro)."""
    ajustar = form.get("ret_federal_ajustar") == "on"
    sug = enquadramento.aplicar_catalogo_federal(c, _catalogo_federal())
    if not ajustar and sug.regra is not None:
        r = sug.regra
        c.ret_federal_regra_codigo = r.codigo
        c.ret_federal_origem = "derivado"
        c.ret_federal_sujeito = r.sujeito
        c.ret_federal_ir_pct = r.ir_pct
        c.ret_federal_codigo_receita = r.codigo_receita
        c.ret_federal_csll, c.ret_federal_cofins, c.ret_federal_pis = r.csll, r.cofins, r.pis
        c.ret_federal_justificativa = None
        c.ret_federal_ajustado_por = c.ret_federal_ajustado_em = None
        return True, None
    # Ajuste manual (ou indefinido que o operador precisa resolver): exige justificativa.
    if not (c.ret_federal_justificativa or "").strip():
        motivo = sug.indefinido_motivo or "o enquadramento federal foi ajustado à mão"
        return False, ("Justifique o ajuste do enquadramento federal — " + motivo +
                       " Nada foi salvo.")
    c.ret_federal_origem = "ajustado"
    c.ret_federal_regra_codigo = sug.regra.codigo if sug.regra else None
    c.ret_federal_ajustado_por = "operador"
    c.ret_federal_ajustado_em = datetime.now(timezone.utc).isoformat()
    return True, None


@app.route("/contratos")
def contratos():
    store = StoreContratos(); lista = store.listar(); store.fechar()
    return render_template("contratos.html", contratos=lista, vocab=_VOCAB_CONTRATO)


def _regra_do_form(form, id_=None) -> RegraEnquadramento:
    """Monta uma RegraEnquadramento a partir do formulário. Condições são multi-seleção
    (getlist); checkbox ausente = False. O sistema só guarda o que o especialista dita."""
    def s(campo):
        v = (form.get(campo) or "").strip()
        return v or None
    try:
        ordem = int(form.get("ordem") or 0)
    except ValueError:
        ordem = 0
    return RegraEnquadramento(
        id=id_,
        codigo=(form.get("codigo") or "").strip(),
        descricao=(form.get("descricao") or "").strip(),
        fundamento=(form.get("fundamento") or "").strip(),
        naturezas=tuple(form.getlist("naturezas")),
        categorias=tuple(form.getlist("categorias")),
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
    store = StoreRegrasFederais(); ordem = store.proxima_ordem(); store.fechar()
    nova = RegraEnquadramento(codigo="", descricao="", fundamento="", ordem=ordem)
    return render_template("regra_form.html", regra=nova, vocab=_VOCAB_CONTRATO, novo=True)


@app.route("/regras/<int:id_>/editar")
def regra_editar(id_):
    store = StoreRegrasFederais(); r = store.obter(id_); store.fechar()
    if not r:
        flash("Regra não encontrada.", "erro")
        return redirect(url_for("regras"))
    return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO, novo=False)


@app.route("/regras", methods=["POST"])
@app.route("/regras/<int:id_>", methods=["POST"])
def regra_salvar(id_=None):
    r = _regra_do_form(request.form, id_)
    if not r.codigo or not r.descricao:
        flash("Informe ao menos o código e a descrição da regra. Nada foi salvo.", "erro")
        return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO, novo=(id_ is None))
    if r.sujeito and not r.ir_pct:
        flash("Como os tributos federais incidem nesta regra, defina o percentual de IR. "
              "Nada foi salvo.", "erro")
        return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO, novo=(id_ is None))
    store = StoreRegrasFederais()
    try:
        store.salvar(r)
    except Exception as exc:
        store.fechar()
        flash(f"Não foi possível salvar: já existe regra com o código “{r.codigo}”? "
              f"({type(exc).__name__}).", "erro")
        return render_template("regra_form.html", regra=r, vocab=_VOCAB_CONTRATO, novo=(id_ is None))
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


if __name__ == "__main__":
    # Debug desligado por padrão (o debugger do Werkzeug executa código); ligue só
    # via EXTRATOR_NF_DEBUG=1 em desenvolvimento. Para o app distribuído, o ponto de
    # entrada é run_app.py (abre o navegador e serve via waitress).
    app.run(debug=config.debug_ativo(), host="127.0.0.1", port=5000)
