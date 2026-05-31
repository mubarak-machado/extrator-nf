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

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash

from tronco.ingestao import ingerir_pasta
from tronco.idempotencia import RegistroDeExportacao
from tronco.marcacoes import StoreMarcacoes
from tronco.exportador import ExportadorCsvLocal, novo_lote_id
from tronco import formato

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
    resultados = ingerir_pasta(PASTA_EXEMPLOS)
    registro = RegistroDeExportacao()
    marc = StoreMarcacoes()
    linhas = []
    for r in resultados:
        item = {"origem": r.origem, "tipo": r.tipo, "erro": r.erro, "reg": None,
                "ja_exportada": False, "marcacao": None, "valor": None}
        if r.registro:
            item["reg"] = r.registro
            item["ja_exportada"] = registro.ja_exportada(r.registro.chave)
            item["valor"] = (r.registro.valor_total if r.tipo == "NFE"
                             else r.registro.valor_servicos)
            if r.tipo == "NFSE":
                item["marcacao"] = marc.atual(r.registro.chave)
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


@app.route("/")
def lista():
    linhas = _carregar()
    grupos = _grupos(linhas)
    consolidacoes = [
        {"prest_cnpj": k[0], "competencia": k[1],
         "prest_nome": its[0]["reg"].prest_nome, "n": len(its),
         "novas": sum(1 for i in its if not i["ja_exportada"]),
         "total": _soma([i["reg"] for i in its], "valor_servicos")}
        for k, its in grupos.items() if len(its) > 1
    ]
    validos = [it for it in linhas if it["reg"]]
    ineditas = [it for it in validos if not it["ja_exportada"]]
    bruto = Decimal("0")
    for it in ineditas:
        try:
            bruto += Decimal(str(it["valor"])) if it["valor"] else Decimal("0")
        except (InvalidOperation, ValueError):
            pass
    kpis = {
        "total": len(validos),
        "ineditas": len(ineditas),
        "ja": sum(1 for it in validos if it["ja_exportada"]),
        "atencao": sum(1 for it in linhas if _com_atencao(it)),
        "valor_inedito": f"{bruto:.2f}",
        "consolidacoes": len(consolidacoes),
    }
    return render_template("lista.html", linhas=linhas, kpis=kpis,
                           consolidacoes=consolidacoes)


@app.route("/consolidado/<prest_cnpj>/<competencia>")
def consolidado(prest_cnpj, competencia):
    linhas = _carregar()
    itens = _grupos(linhas).get((prest_cnpj, competencia), [])
    if not itens:
        flash("Consolidação não encontrada.")
        return redirect(url_for("lista"))
    regs = [it["reg"] for it in itens]
    totais = {a: _soma(regs, a) for a in (
        "valor_servicos", "iss_valor_destaque_emitente", "ir_destaque_emitente",
        "pis_destaque_emitente", "cofins_destaque_emitente",
        "csll_destaque_emitente", "inss_destaque_emitente", "valor_liquido")}
    novas = sum(1 for it in itens if not it["ja_exportada"])
    return render_template("consolidado.html", itens=itens, regs=regs,
                           prest_cnpj=prest_cnpj, competencia=competencia,
                           prest_nome=regs[0].prest_nome, totais=totais, novas=novas)


@app.route("/nota/<chave>")
def detalhe(chave):
    for item in _carregar():
        if item["reg"] and item["reg"].chave == chave:
            return render_template("detalhe.html", item=item)
    flash("Nota não encontrada.")
    return redirect(url_for("lista"))


@app.route("/marcar/<chave>", methods=["POST"])
def marcar(chave):
    valor = request.form.get("material")
    autor = request.form.get("autor", "").strip() or "usuário do POC"
    if valor not in ("sim", "nao"):
        flash("Selecione 'sim' ou 'não' para material aplicado.")
        return redirect(url_for("detalhe", chave=chave))
    marc = StoreMarcacoes(); marc.marcar(chave, valor, autor); marc.fechar()
    flash(f"Marcacao registrada: material aplicado = {valor.upper()} (por {autor}).")
    return redirect(url_for("detalhe", chave=chave))


def _exportar(candidatos):
    if not candidatos:
        return "Nada a exportar: as notas selecionadas ja foram exportadas."
    registro = RegistroDeExportacao()
    novas, _ = registro.filtrar_novas([r.chave for r in candidatos])
    candidatos = [r for r in candidatos if r.chave in set(novas)]
    if not candidatos:
        registro.fechar()
        return "Nada a exportar: as notas selecionadas ja foram exportadas."
    lote = novo_lote_id()
    try:
        artefato = ExportadorCsvLocal(PASTA_SAIDA).exportar(candidatos, lote)
    except Exception as exc:
        registro.fechar()
        return f"Exportacao falhou ({type(exc).__name__}): {exc}. Nada foi registrado."
    registro.registrar_lote([(r.chave, r.tipo) for r in candidatos], lote)
    registro.fechar()
    return f"Lote {lote} exportado: {len(candidatos)} nota(s). Artefato: {artefato}"


@app.route("/exportar", methods=["POST"])
def exportar():
    linhas = _carregar()
    cands = [it["reg"] for it in linhas if it["reg"] and not it["ja_exportada"] and not it["erro"]]
    flash(_exportar(cands))
    return redirect(url_for("lista"))


@app.route("/exportar_grupo/<prest_cnpj>/<competencia>", methods=["POST"])
def exportar_grupo(prest_cnpj, competencia):
    linhas = _carregar()
    itens = _grupos(linhas).get((prest_cnpj, competencia), [])
    cands = [it["reg"] for it in itens if not it["ja_exportada"] and not it["erro"]]
    flash(_exportar(cands))
    return redirect(url_for("consolidado", prest_cnpj=prest_cnpj, competencia=competencia))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
