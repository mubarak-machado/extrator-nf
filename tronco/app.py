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
        flash("Consolidação não encontrada.")
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
            return render_template("detalhe.html", item=item)
    flash("Nota não encontrada.")
    return redirect(url_for("hub"))


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
    """Exporta as notas avulsas inéditas (não as de consolidação — cada contrato
    é exportado pelo seu próprio botão, para nunca misturar contratos)."""
    linhas = _carregar()
    cons_chaves = _chaves_consolidadas(linhas)
    cands = [it["reg"] for it in linhas
             if it["reg"] and not it["ja_exportada"] and not it["erro"]
             and it["reg"].chave not in cons_chaves]
    flash(_exportar(cands))
    return redirect(url_for("individuais"))


@app.route("/exportar_grupo/<prest_cnpj>/<competencia>", methods=["POST"])
def exportar_grupo(prest_cnpj, competencia):
    linhas = _carregar()
    itens = _grupos(linhas).get((prest_cnpj, competencia), [])
    cands = [it["reg"] for it in itens if not it["ja_exportada"] and not it["erro"]]
    flash(_exportar(cands))
    return redirect(url_for("consolidado", prest_cnpj=prest_cnpj, competencia=competencia))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
