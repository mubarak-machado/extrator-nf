"""
Testes do MVP — organizados pelos invariantes que exercitam.

Não testam regra de retenção (Fase 2, fora do escopo). Testam que a Fase 1 é
fiel, que a idempotência segura duplicata, que a exportação é imutável por lote
e que a marcação de material é persistida com autoria.
"""
import os
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "exemplos"

from tronco.ingestao import ingerir, identificar_tipo
from tronco.idempotencia import RegistroDeExportacao
from tronco.exportador import ExportadorCsvLocal
from tronco.marcacoes import StoreMarcacoes
from tronco import redefinicao


def _reg(nome):
    return ingerir(EXEMPLOS / nome).registro


# ---------- Tronco: identificação de tipo ----------

def test_identifica_nfe_e_nfse():
    assert identificar_tipo(EXEMPLOS / "nfe_exemplo.xml") == "NFE"
    assert identificar_tipo(EXEMPLOS / "nfse_com_material.xml") == "NFSE"


# ---------- I-2: extração fiel ----------

def test_nfe_extracao_fiel():
    r = _reg("nfe_exemplo.xml")
    assert len(r.chave) == 44
    assert r.emit_nome == "Fornos LTDA"
    assert r.emit_optante_simples is False        # CRT=3 -> não optante
    assert r.valor_total == "95700.68"
    assert r.icms_destaque_emitente == "16726.76"  # destaque, não apuração


def test_nfse_extracao_fiel_e_discriminacao_preservada():
    r = _reg("nfse_com_material.xml")
    assert r.tipo == "NFSE"
    assert r.prest_optante_simples is False
    assert r.codigo_servico == "070201"
    assert r.ir_destaque_emitente == "240.00"
    # discriminação transcrita ao pé da letra, sem interpretação
    assert "empregados materiais" in r.discriminacao
    # o sistema NÃO extrai o valor do material do texto livre (I-2)
    assert not hasattr(r, "valor_material")


def test_nfse_optante_simples_lido():
    assert _reg("nfse_simples.xml").prest_optante_simples is True


# ---------- I-6: falha/ausência visível ----------

def test_campo_faltante_e_sinalizado_nao_quebra():
    r = _reg("nfe_exemplo.xml")               # dest sem CNPJ (comprador estrangeiro)
    assert r.dest_cnpj is None
    assert "CNPJ do destinatário" in r.campos_faltantes


def test_xml_irreconhecivel_vira_erro_visivel():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lixo.xml"
        p.write_text("<algo><coisa/></algo>", encoding="utf-8")
        res = ingerir(p)
        assert res.tipo is None and res.erro is not None


# ---------- I-1: idempotência ----------

def test_idempotencia_recusa_duplicata():
    with tempfile.TemporaryDirectory() as d:
        reg = RegistroDeExportacao(Path(d) / "r.sqlite")
        chave = "1" * 44
        assert reg.ja_exportada(chave) is False
        reg.registrar_lote([(chave, "NFE")], "lote1")
        assert reg.ja_exportada(chave) is True
        novas, repetidas = reg.filtrar_novas([chave, "2" * 44])
        assert novas == ["2" * 44] and repetidas == [chave]
        reg.fechar()


# ---------- I-5: exportação cria artefato novo, imutável ----------

def _linha(reg):
    """Monta o dict individual (como a rota faz) usando um store de marcação vazio."""
    from tronco.app import _linha_individual
    with tempfile.TemporaryDirectory() as d:
        m = StoreMarcacoes(Path(d) / "m.sqlite")
        try:
            return _linha_individual(reg, m)
        finally:
            m.fechar()


def test_exportador_cria_artefato_e_recusa_sobrescrever():
    from tronco.app import SPEC_INDIVIDUAL
    with tempfile.TemporaryDirectory() as d:
        exp = ExportadorCsvLocal(d)
        item = _linha(_reg("nfe_exemplo.xml"))
        caminho = exp.exportar([item], SPEC_INDIVIDUAL, "loteX", "individual")
        assert os.path.exists(caminho)
        with pytest.raises(FileExistsError):       # imutável por lote
            exp.exportar([item], SPEC_INDIVIDUAL, "loteX", "individual")


def test_export_individual_espelha_tela_e_formata():
    """Padrão individual espelha a lista da tela (Tipo, Número, Fornecedor, CNPJ,
    Valor, Situação) + retenções/materiais; pt-BR, ; e BOM."""
    from tronco.app import SPEC_INDIVIDUAL
    with tempfile.TemporaryDirectory() as d:
        caminho = ExportadorCsvLocal(d).exportar(
            [_linha(_reg("nfe_exemplo.xml"))], SPEC_INDIVIDUAL, "loteFmt", "individual")
        assert caminho.endswith("_individual.csv")
        bruto = Path(caminho).read_bytes()
        assert bruto.startswith(b"\xef\xbb\xbf")          # BOM (Excel pt-BR)
        linhas = bruto.decode("utf-8-sig").splitlines()
        cab, primeira = linhas[0], linhas[1]
        assert cab.split(";")[:6] == ["Tipo", "Número", "Fornecedor", "CNPJ", "Valor", "Situação"]
        assert any("(destaque do emitente)" in c for c in cab.split(";"))   # I-2
        assert "R$ 95.700,68" in primeira                 # vNF do exemplo
        assert "75.277.525/0001-78" in primeira           # CNPJ pontuado
        assert primeira.startswith("NFE;")                # Tipo


def test_formato_formatar_dispatch():
    from tronco import formato
    assert formato.formatar("95700.68", "moeda") == "R$ 95.700,68"
    assert formato.formatar("75277525000178", "cnpj") == "75.277.525/0001-78"
    assert formato.formatar(None, "texto") == "—"
    assert formato.formatar(["falta A", "falta B"], "faltantes") == "falta A; falta B"
    assert formato.formatar("4242", "cru") == "4242"
    with pytest.raises(ValueError):
        formato.formatar("x", "inexistente")


def test_npp_curto_e_so_apresentacao():
    """O rótulo curto da NPP deriva do `numero` imutável (data/mês + sequencial),
    some prefixo 'NPP' e iniciais (autoria fica no criada_por/arquivo). Fora do
    padrão, devolve o que veio — nunca inventa (I-6)."""
    from tronco import formato
    assert formato.npp_curto("NPP_MN_20260603_0001") == "03/06 · 0001"
    assert formato.npp_curto("NPP_ABC_20251231_0042") == "31/12 · 0042"
    assert formato.npp_curto("") == "—"
    assert formato.npp_curto("fora_do_padrao") == "fora_do_padrao"


def test_competencia_aceita_ano_mes():
    """A NPP guarda competência como 'AAAA-MM' (sem dia); o filtro formata os dois
    casos (com e sem dia) para 'MM/AAAA'."""
    from tronco import formato
    assert formato.competencia("2026-05") == "05/2026"
    assert formato.competencia("2026-05-01") == "05/2026"
    assert formato.competencia("") == "—"


# ---------- I-4: marcação persistida com autoria ----------

def test_marcacao_persistida_com_autor():
    with tempfile.TemporaryDirectory() as d:
        store = StoreMarcacoes(Path(d) / "m.sqlite")
        chave = "3" * 50
        assert store.atual(chave) is None
        store.marcar(chave, "sim", "Mubarak")
        atual = store.atual(chave)
        assert atual["valor"] == "sim" and atual["autor"] == "Mubarak"
        assert atual["marcado_em"]                  # carimbo de data presente
        store.fechar()


def test_marcacao_guarda_valor_material_validado():
    """O valor de material validado pelo operador é persistido — só quando houve
    material ('sim'); marcado 'nao' não guarda valor."""
    with tempfile.TemporaryDirectory() as d:
        store = StoreMarcacoes(Path(d) / "m.sqlite")
        store.marcar("a" * 50, "sim", "operador", "1200.00")
        assert store.atual("a" * 50)["valor_material"] == "1200.00"
        store.marcar("b" * 50, "nao", "operador", "1200.00")   # 'nao' ignora o valor
        assert store.atual("b" * 50)["valor_material"] is None
        store.fechar()


# ---------- Material: sugestão a partir do texto livre (operador valida) ----------

def test_sugestao_material_captura_valor_amarrado():
    from galho_nfse.material import sugerir_material
    s = sugerir_material("Foram empregados materiais (tubos) no valor de R$ 1.200,00 alem da mao de obra.")
    assert s["presenca"] == "sim" and s["valor"] == "1200.00"


def test_sugestao_material_negacao_e_sem_falso_positivo():
    """Crítico (I-2): texto com valores que NÃO são material (bruto/líquido, como
    nas notas reais) NÃO pode render sugestão de valor — senão erra a base de INSS."""
    from galho_nfse.material import sugerir_material
    assert sugerir_material("Servico continuado sem emprego de material.")["presenca"] == "nao"
    real = sugerir_material("Prestacao de servicos de Recepcao - Valor RS 11597.60 "
                            "VALOR LIQUIDO DA NOTA FISCAL RS 9109.92 VENCIMENTO 25/6/2026")
    assert real["presenca"] is None and real["valor"] is None


def test_export_consolidado_colunas_e_material():
    """Padrão consolidado: uma linha por NFS-e, colunas do lançamento no SIAFI,
    com o valor de material validado pelo operador injetado."""
    from galho_nfse.modelo import RegistroNFSe
    with tempfile.TemporaryDirectory() as d:
        reg = _reg("nfse_com_material.xml")
        item = reg.to_dict(); item["valor_material"] = "1200.00"
        caminho = ExportadorCsvLocal(d).exportar(
            [item], RegistroNFSe.EXPORT_SPEC_CONSOLIDADO, "loteCons", "consolidado")
        assert caminho.endswith("_consolidado.csv")
        bruto = Path(caminho).read_bytes()
        assert bruto.startswith(b"\xef\xbb\xbf")                 # BOM
        linhas = bruto.decode("utf-8-sig").splitlines()
        cab, primeira = linhas[0], linhas[1]
        # espelha a tabela da tela: Município, Nº, Valor serviços, ... , Líquido
        assert cab.split(";")[:3] == ["Município", "Nº", "Valor serviços"]
        assert "Valor dos materiais (validado pelo operador)" in cab
        assert any("(destaque do emitente)" in c for c in cab.split(";"))  # retenções individualizadas
        assert "R$ 1.200,00" in primeira                         # material validado, formatado
        assert len(linhas) == 2                                  # cabeçalho + 1 nota


# ---------- Redefinição (reset de demonstração): backup antes de apagar ----------

def test_redefinir_faz_backup_antes_de_apagar():
    """Redefinir zera idempotência (I-1) e marcações (I-4) — mas nunca em
    silêncio: copia cada banco para um backup datado antes de remover (I-6)."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        bd_export = d / "registro_exportacao.sqlite"
        bd_marc = d / "marcacoes.sqlite"
        reg = RegistroDeExportacao(bd_export); reg.registrar_lote([("1" * 44, "NFE")], "L1"); reg.fechar()
        StoreMarcacoes(bd_marc).marcar("9" * 44, "sim", "Mubarak")

        resumo = redefinicao.redefinir_dados(bancos=(bd_export, bd_marc), pastas=(),
                                             pasta_backup=d / "backups")

        # os bancos sumiram do lugar de trabalho...
        assert not bd_export.exists() and not bd_marc.exists()
        # ...mas continuam recuperáveis no backup datado
        backup = Path(resumo["backup"])
        assert (backup / "registro_exportacao.sqlite").exists()
        assert (backup / "marcacoes.sqlite").exists()
        assert set(resumo["apagados"]) == {"registro_exportacao.sqlite", "marcacoes.sqlite"}
        # e o estado volta ao inicial: nota antes exportada agora reabre como nova
        assert RegistroDeExportacao(bd_export).ja_exportada("1" * 44) is False


def test_redefinir_sem_dados_nao_e_erro():
    """Redefinir o que já está limpo é no-op, não falha (I-6: previsível)."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        resumo = redefinicao.redefinir_dados(
            bancos=(d / "nao_existe.sqlite",), pastas=(), pasta_backup=d / "backups")
        assert resumo["apagados"] == [] and resumo["backup"] is None


# ---------- Notas persistidas: importa uma vez, telas leem do banco ----------

def test_notas_persistidas_round_trip():
    """A nota extraída é gravada e reconstruída fielmente a partir do banco — sem
    reler o XML. Reimportar a mesma chave não duplica (PK, alinhado a I-1)."""
    from tronco.notas import StoreNotas, reconstruir
    with tempfile.TemporaryDirectory() as d:
        store = StoreNotas(Path(d) / "n.sqlite")
        r = _reg("nfe_exemplo.xml")
        store.salvar(r.chave, "NFE", r.to_dict(), "nfe_exemplo.xml")
        store.salvar(r.chave, "NFE", r.to_dict(), "nfe_exemplo.xml")  # reimport
        listados = store.listar()
        assert len(listados) == 1 and store.contar() == 1     # chave PK
        reconstruido = reconstruir(listados[0]["tipo"], listados[0]["dados"])
        assert reconstruido.chave == r.chave
        assert reconstruido.emit_nome == "Fornos LTDA"
        assert reconstruido.campos_faltantes == r.campos_faltantes  # lista preservada
        store.fechar()


def test_redefinir_inclui_banco_de_notas():
    """Redefinir esvazia também as notas importadas (com backup antes)."""
    from tronco.notas import StoreNotas
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        bd_notas = d / "notas.sqlite"
        store = StoreNotas(bd_notas)
        r = _reg("nfe_exemplo.xml")
        store.salvar(r.chave, "NFE", r.to_dict(), "x.xml")
        store.fechar()
        resumo = redefinicao.redefinir_dados(bancos=(bd_notas,), pastas=(),
                                             pasta_backup=d / "bkp")
        assert not bd_notas.exists()
        assert (Path(resumo["backup"]) / "notas.sqlite").exists()
        assert StoreNotas(bd_notas).contar() == 0       # recriado vazio


def test_contrato_round_trip_e_edicao():
    """Configuração de contrato persiste fielmente (incl. booleans), e editar
    mantém criado_em e atualiza atualizado_em (auditável — I-4)."""
    import sqlite3, pytest as _pytest
    from tronco.contratos import StoreContratos, Contrato
    with tempfile.TemporaryDirectory() as d:
        store = StoreContratos(Path(d) / "c.sqlite")
        c = Contrato(prest_identificacao="ORBENK LTDA", prest_documento="79283065000303",
                     prest_natureza="nao_optante", numero="02", ano="2026",
                     categoria_servico="limpeza_conservacao", material_previsao="sim_discriminado",
                     ret_federal_sujeito=True, ret_federal_codigo_receita="6147",
                     inss_cessao_mao_obra=True, inss_aliquota="11", iss_retido_tomador=True,
                     iss_aliquota="5")
        cid = store.salvar(c)
        obtido = store.obter(cid)
        assert obtido.prest_identificacao == "ORBENK LTDA"
        assert obtido.ret_federal_sujeito is True and obtido.inss_cessao_mao_obra is True
        assert obtido.ret_federal_codigo_receita == "6147" and obtido.iss_aliquota == "5"
        assert obtido.criado_em and obtido.criado_em == obtido.atualizado_em

        obtido.iss_aliquota = "3"               # edição
        store.salvar(obtido)
        reeditado = store.obter(cid)
        assert reeditado.iss_aliquota == "3"
        assert reeditado.criado_em == obtido.criado_em            # criação preservada
        assert reeditado.atualizado_em >= reeditado.criado_em     # atualização mexeu

        # unicidade por (documento, número, ano): segundo contrato igual estoura
        with _pytest.raises(sqlite3.IntegrityError):
            store.salvar(Contrato(prest_identificacao="X", prest_documento="79283065000303",
                                  numero="02", ano="2026"))
        assert len(store.listar()) == 1
        store.fechar()


def test_redefinir_arquiva_e_esvazia_pasta_de_exportacoes():
    """Os artefatos CSV são ARQUIVADOS no backup antes de a pasta ser esvaziada —
    I-5: nada é editado/reescrito, o lote é movido inteiro e fica recuperável."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        exp = d / "exportacoes"; exp.mkdir()
        (exp / "lote_X_NFE.csv").write_text("a;b\n1;2\n", encoding="utf-8")
        resumo = redefinicao.redefinir_dados(bancos=(), pastas=(exp,),
                                             pasta_backup=d / "bkp")
        assert resumo["artefatos_limpos"] == 1
        assert exp.is_dir() and list(exp.iterdir()) == []          # pasta vazia, mas existe
        assert (Path(resumo["backup"]) / "exportacoes" / "lote_X_NFE.csv").exists()


# ---------- Contrato: campos novos de retenção + migração de schema ----------

def test_contrato_campos_de_retencao_round_trip():
    """Os campos estruturados de regra (IR %, contribuições, adicional INSS, ISS)
    persistem fielmente, incluindo os novos booleans (I-4)."""
    from tronco.contratos import StoreContratos, Contrato
    with tempfile.TemporaryDirectory() as d:
        store = StoreContratos(Path(d) / "c.sqlite")
        c = Contrato(prest_identificacao="ACME", prest_documento="11222333000181",
                     numero="07", ano="2026", ret_federal_sujeito=True,
                     ret_federal_ir_pct="4.8", ret_federal_pis=False,
                     inss_cessao_mao_obra=True, inss_aliquota="11", inss_adicional_pct="3",
                     iss_retido_tomador=True, iss_aliquota="5", iss_subitem_lista="7.02",
                     iss_local_incidencia="local_prestacao", iss_deduz_material=True)
        cid = store.salvar(c)
        o = store.obter(cid)
        assert o.ret_federal_ir_pct == "4.8"
        assert o.ret_federal_csll is True and o.ret_federal_pis is False   # boolean fiel
        assert o.inss_adicional_pct == "3" and o.iss_subitem_lista == "7.02"
        assert o.iss_local_incidencia == "local_prestacao" and o.iss_deduz_material is True
        store.fechar()


def test_contrato_migra_schema_antigo_sem_perder_dados():
    """Abrir um banco com schema ANTIGO (sem as colunas novas) adiciona as colunas
    sem perder o que já estava lá — I-6: campo novo não some silenciosamente."""
    import sqlite3
    from tronco.contratos import StoreContratos, Contrato, _CAMPOS
    with tempfile.TemporaryDirectory() as d:
        caminho = Path(d) / "c.sqlite"
        # tabela "legada" com um subconjunto mínimo de colunas
        conn = sqlite3.connect(str(caminho))
        conn.execute("CREATE TABLE contratos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "prest_identificacao TEXT, prest_documento TEXT, numero TEXT, ano TEXT, "
                     "ret_federal_sujeito TEXT, UNIQUE (prest_documento, numero, ano))")
        conn.execute("INSERT INTO contratos (prest_identificacao, prest_documento, numero, "
                     "ano, ret_federal_sujeito) VALUES ('VELHO','11222333000181','01','2025','1')")
        conn.commit(); conn.close()

        store = StoreContratos(caminho)                 # roda a migração ao abrir
        cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(contratos)").fetchall()}
        assert all(campo in cols for campo in _CAMPOS)  # todas as colunas novas existem
        antigo = store.listar()[0]
        assert antigo.prest_identificacao == "VELHO"    # dado preservado
        assert antigo.ret_federal_sujeito is True
        # contribuições federais migradas com DEFAULT '1' (mantém o trio 4,65%)
        assert antigo.ret_federal_csll is True and antigo.ret_federal_cofins is True
        store.fechar()


# ---------- Conferência da nota contra o contrato (Fase 2 — sugestão, I-3) ----------

def _reg_nfse(**kw):
    """RegistroNFSe mínimo para conferência (demais campos default None)."""
    from galho_nfse.modelo import RegistroNFSe
    base = dict(chave="X", prest_cnpj="11222333000181", valor_servicos="1000.00")
    base.update(kw)
    return RegistroNFSe(**base)


def _contrato(**kw):
    from tronco.contratos import Contrato
    base = dict(prest_identificacao="ACME", prest_documento="11222333000181",
                numero="07", ano="2026", material_previsao="nao")
    base.update(kw)
    return Contrato(**base)


def test_conferencia_iss_confere_e_diverge():
    """ISS: esperado = valor_serviços × alíquota do contrato; bate -> confere,
    não bate -> diverge. É sugestão, não decisão (I-3)."""
    from galho_nfse import retencao
    reg = _reg_nfse(iss_valor_destaque_emitente="50.00")
    # contrato ISS 5% sobre 1000 = 50,00 -> confere
    res = retencao.conferir_retencao(reg, _contrato(iss_retido_tomador=True, iss_aliquota="5"))
    iss = [a for a in res.achados if a.tributo == "ISS"][0]
    assert iss.esperado == "50.00" and iss.situacao == "confere"
    # contrato ISS 2% sobre 1000 = 20,00, mas a nota destacou 50 -> diverge
    res2 = retencao.conferir_retencao(reg, _contrato(iss_retido_tomador=True, iss_aliquota="2"))
    iss2 = [a for a in res2.achados if a.tributo == "ISS"][0]
    assert iss2.esperado == "20.00" and iss2.situacao == "diverge"


def test_conferencia_ir_indefinido_sem_marcacao_de_material():
    """Se o contrato prevê material e o operador ainda não marcou, o IR fica
    INDEFINIDO (a alíquota depende do material) — I-6, não chuta."""
    from galho_nfse import retencao
    reg = _reg_nfse(ir_destaque_emitente="48.00")
    contrato = _contrato(ret_federal_sujeito=True, ret_federal_ir_pct="4.8",
                         material_previsao="sim_discriminado")
    res = retencao.conferir_retencao(reg, contrato, material_marcado=None)
    ir = [a for a in res.achados if a.tributo == "IR"][0]
    assert ir.situacao == "indefinido" and ir.esperado is None
    # marcado -> agora confere (4,8% de 1000 = 48,00)
    res2 = retencao.conferir_retencao(reg, contrato, material_marcado="sim")
    ir2 = [a for a in res2.achados if a.tributo == "IR"][0]
    assert ir2.esperado == "48.00" and ir2.situacao == "confere"


def test_conferencia_nao_grava_nada():
    """Conferência é read-only: não persiste marcação nem registro (I-3/I-5).
    Rodar não cria nenhum arquivo .sqlite no diretório de trabalho temporário."""
    from galho_nfse import retencao
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            reg = _reg_nfse(inss_destaque_emitente="110.00")
            retencao.conferir_retencao(reg, _contrato(inss_cessao_mao_obra=True,
                                                      inss_aliquota="11"))
            assert list(Path(d).glob("*.sqlite")) == []   # nada gravado
        finally:
            os.chdir(cwd)


# ---------- Bloco federal comum (tronco) — IN 1234/2012, reusável pelos 2 galhos ----------

def test_retencao_federal_comum_calcula_ir_e_contribuicoes():
    """O bloco federal comum (tronco) calcula IR + CSLL/COFINS/PIS sobre a base, como
    SUGESTÃO (I-3). Mesmas entradas normalizadas → mesmos `Achado` p/ qualquer galho."""
    from tronco import retencao_federal
    achados = retencao_federal.achados_federais(
        base="1000.00", ir_pct="4.8", ir_codigo="6147", ir_destaque="48.00",
        csll_ativo=True, csll_destaque="10.00",
        cofins_ativo=True, cofins_destaque="30.00",
        pis_ativo=True, pis_destaque="6.50",
    )
    por = {a.tributo: a for a in achados}
    assert por["IR"].esperado == "48.00" and por["IR"].situacao == "confere"     # 4,8% de 1000
    assert por["CSLL"].esperado == "10.00" and por["CSLL"].situacao == "confere"  # 1%
    assert por["COFINS"].esperado == "30.00" and por["COFINS"].situacao == "confere"  # 3%
    assert por["PIS"].esperado == "6.50" and por["PIS"].situacao == "confere"     # 0,65%


def test_retencao_federal_comum_contrib_inativa_e_ir_sem_material_gating():
    """Contribuição não-incidente: confere se a nota não destacou, diverge se destacou (I-6).
    E sem gating de material (default 'nao'/None), o IR é conferido direto — caminho da NF-e."""
    from tronco import retencao_federal
    achados = retencao_federal.achados_federais(
        base="1000.00", ir_pct="1.2", ir_codigo=None, ir_destaque="12.00",
        csll_ativo=False, csll_destaque=None,
        cofins_ativo=False, cofins_destaque="30.00",
        pis_ativo=True, pis_destaque="6.50",
    )
    por = {a.tributo: a for a in achados}
    assert por["IR"].situacao == "confere"        # 1,2% de 1000 = 12,00, sem gating
    assert por["CSLL"].situacao == "confere"      # não incide e não destacou
    assert por["COFINS"].situacao == "diverge"    # não incide mas destacou 30


# ---------- Conferência da NF-e (galho NF-e, Fase 2) — federal, gatilho Simples ----------

def _reg_nfe(**kw):
    """RegistroNFe mínimo para conferência (demais campos default None)."""
    from galho_nfe.modelo import RegistroNFe
    base = dict(chave="NFE1", emit_cnpj="11222333000181", valor_total="1000.00",
                emit_optante_simples=False)
    base.update(kw)
    return RegistroNFe(**base)


def test_nfe_nao_optante_retem_federal_e_nao_inss_iss():
    """NF-e de fornecedor NÃO optante: bloco federal aplica (sugestão); INSS/ISS não
    entram (não se aplicam à venda mercantil)."""
    from galho_nfe import retencao
    reg = _reg_nfe(emit_optante_simples=False)
    contrato = _contrato(ret_federal_sujeito=True, ret_federal_ir_pct="1.2",
                         ret_federal_codigo_receita="6147")
    res = retencao.conferir_retencao(reg, contrato)
    assert {a.tributo for a in res.achados} == {"IR", "CSLL", "COFINS", "PIS"}  # só federal
    ir = [a for a in res.achados if a.tributo == "IR"][0]
    assert ir.esperado == "12.00"                       # 1,2% de 1000
    # NF-e não destaca a retenção -> destaque ausente, diverge do esperado (operador valida)
    assert ir.destaque_emitente is None and ir.situacao == "diverge"


def test_nfe_optante_simples_dispensa_retencao():
    """NF-e de fornecedor optante do Simples: retenção federal dispensada (LC 123/2006)."""
    from galho_nfe import retencao
    reg = _reg_nfe(emit_optante_simples=True)
    res = retencao.conferir_retencao(reg, _contrato(ret_federal_sujeito=True, ret_federal_ir_pct="1.2"))
    assert {a.tributo for a in res.achados} == {"IR", "CSLL", "COFINS", "PIS"}
    assert all(a.esperado == "0.00" and a.situacao == "confere" for a in res.achados)


def test_nfe_regime_indefinido_quando_optante_desconhecido():
    """Sem indicador de optante (CRT ausente) -> indefinido visível, nunca chuta (I-6)."""
    from galho_nfe import retencao
    reg = _reg_nfe(emit_optante_simples=None)
    res = retencao.conferir_retencao(reg, _contrato(ret_federal_sujeito=True, ret_federal_ir_pct="1.2"))
    assert all(a.situacao == "indefinido" and a.esperado is None for a in res.achados)


def test_federal_comum_paridade_nfe_nfse():
    """O bloco federal é o MESMO para os dois galhos: mesmas entradas -> mesmos esperados.
    Prova que a NF-e e a NFS-e compartilham tronco/retencao_federal.py sem divergir."""
    from galho_nfe import retencao as ret_nfe
    from galho_nfse import retencao as ret_nfse
    contrato = _contrato(ret_federal_sujeito=True, ret_federal_ir_pct="4.8")
    fed_nfe = {a.tributo: a.esperado
               for a in ret_nfe.conferir_retencao(_reg_nfe(emit_optante_simples=False), contrato).achados}
    nfse_achados = ret_nfse.conferir_retencao(_reg_nfse(), contrato).achados
    fed_nfse = {a.tributo: a.esperado for a in nfse_achados if a.tributo in _FEDERAIS_TRIB}
    assert fed_nfe == fed_nfse == {"IR": "48.00", "CSLL": "10.00", "COFINS": "30.00", "PIS": "6.50"}


_FEDERAIS_TRIB = ("IR", "CSLL", "COFINS", "PIS")


# ---------- Motor de enquadramento federal — Fase 2, derivação (I-3/I-6) ----------
# O catálogo real é lançado pelo especialista (galho_nfse/catalogo_federal.py) e começa
# vazio. Aqui testamos o MOTOR com um catálogo de fixture, e que o real começa vazio.

def _catalogo_fixture():
    from galho_nfse.enquadramento import RegraEnquadramento
    return [
        RegraEnquadramento(codigo="X-000", descricao="dispensa", fundamento="f",
                           naturezas=("simples", "mei", "pessoa_fisica"), sujeito=False),
        RegraEnquadramento(codigo="X-001", descricao="com material", fundamento="f",
                           naturezas=("nao_optante",), categorias=("geral",),
                           materiais=("sim_discriminado", "sim_sem_discriminacao"),
                           sujeito=True, ir_pct="1.2", csll=True, cofins=True, pis=True),
        RegraEnquadramento(codigo="X-002", descricao="sem material", fundamento="f",
                           naturezas=("nao_optante",), categorias=("geral",),
                           materiais=("nao",),
                           sujeito=True, ir_pct="4.8", csll=True, cofins=True, pis=True),
    ]


def test_motor_casa_primeira_regra():
    """O motor devolve a primeira regra cuja condição casa o contrato."""
    from galho_nfse import enquadramento
    cat = _catalogo_fixture()
    sug = enquadramento.aplicar_catalogo_federal(_contrato(prest_natureza="simples"), catalogo=cat)
    assert sug.regra.codigo == "X-000" and sug.regra.sujeito is False
    sug = enquadramento.aplicar_catalogo_federal(
        _contrato(prest_natureza="nao_optante", categoria_servico="geral", material_previsao="nao"),
        catalogo=cat)
    assert sug.regra.codigo == "X-002" and sug.regra.ir_pct == "4.8"
    sug = enquadramento.aplicar_catalogo_federal(
        _contrato(prest_natureza="nao_optante", categoria_servico="geral",
                  material_previsao="sim_discriminado"), catalogo=cat)
    assert sug.regra.codigo == "X-001"


def test_motor_indefinido_quando_nenhuma_regra_casa():
    """I-6: nenhuma regra casa (inclui catálogo vazio) → indefinido com motivo visível."""
    from galho_nfse import enquadramento
    sug = enquadramento.aplicar_catalogo_federal(_contrato(prest_natureza="nao_optante"), catalogo=[])
    assert sug.regra is None and sug.indefinido_motivo
    sug = enquadramento.aplicar_catalogo_federal(
        _contrato(prest_natureza="nao_optante", categoria_servico="transporte_passageiros",
                  material_previsao="nao"), catalogo=_catalogo_fixture())
    assert sug.regra is None


def test_motor_pureza_nao_muta_contrato():
    """I-3: aplicar o catálogo não muta o contrato nem grava nada."""
    from galho_nfse import enquadramento
    c = _contrato(prest_natureza="nao_optante")
    enquadramento.aplicar_catalogo_federal(c, _catalogo_fixture())
    assert c.ret_federal_origem == "derivado" and c.ret_federal_regra_codigo is None  # default intacto


def test_store_regras_crud_e_ordem(tmp_path):
    """CRUD do catálogo cadastrado pela tela (I-4): salvar/listar/obter/editar/remover;
    condição (listas) e audit voltam do banco; a ordem de avaliação é respeitada."""
    from galho_nfse.enquadramento import RegraEnquadramento
    from galho_nfse.catalogo_federal import StoreRegrasFederais
    store = StoreRegrasFederais(tmp_path / "cat.sqlite")
    assert store.listar() == []                                  # começa vazio
    r1 = RegraEnquadramento(codigo="TF-001", descricao="com material", fundamento="IN",
                            naturezas=("nao_optante",), categorias=("geral",),
                            materiais=("sim_discriminado",), sujeito=True, ir_pct="1.2",
                            csll=True, cofins=True, pis=True, ordem=2)
    r2 = RegraEnquadramento(codigo="TF-000", descricao="dispensa", fundamento="IN",
                            naturezas=("simples",), sujeito=False, ordem=1)
    store.salvar(r1); store.salvar(r2)
    lista = store.listar()
    assert [r.codigo for r in lista] == ["TF-000", "TF-001"]     # ordenado por `ordem`
    lido = store.obter(lista[1].id)
    assert lido.naturezas == ("nao_optante",) and lido.materiais == ("sim_discriminado",)
    assert lido.sujeito is True and lido.criado_em                # audit gravado (I-4)
    # editar mantém criado_em e atualiza atualizado_em
    lido.descricao = "com material (revisado)"
    store.salvar(lido)
    rel = store.obter(lido.id)
    assert rel.descricao == "com material (revisado)" and rel.criado_em == lido.criado_em
    store.remover(lido.id)
    assert [r.codigo for r in store.listar()] == ["TF-000"]
    store.fechar()


def test_regra_agregada_derivada():
    """A agregada é IR + as contribuições que incidem (nunca digitada)."""
    from decimal import Decimal
    from galho_nfse.enquadramento import RegraEnquadramento
    r = RegraEnquadramento(codigo="X", descricao="d", fundamento="f", sujeito=True,
                           ir_pct="4.8", csll=True, cofins=True, pis=True)
    assert r.agregada_pct() == Decimal("9.45") and r.agregada_txt() == "9,45%"
    assert r.ir_txt() == "4,8%"
    r2 = RegraEnquadramento(codigo="Y", descricao="d", fundamento="f", sujeito=True, ir_pct="1.5")
    assert r2.agregada_pct() == Decimal("1.5")      # só IR, sem trio


def test_contrato_persiste_codigo_e_override_federal(tmp_path):
    """I-4: o contrato persiste o código da regra derivada e, no override manual,
    a justificativa + autor + data — reler do banco devolve tudo."""
    from tronco.contratos import StoreContratos
    store = StoreContratos(tmp_path / "contratos.sqlite")
    c = _contrato(prest_natureza="nao_optante", ret_federal_regra_codigo="TF-002",
                  ret_federal_origem="derivado", ret_federal_sujeito=True,
                  ret_federal_ir_pct="4.8")
    id_ = store.salvar(c)
    lido = store.obter(id_)
    assert lido.ret_federal_regra_codigo == "TF-002" and lido.ret_federal_origem == "derivado"
    # Override manual (caso especial) → persiste rastro completo.
    lido.ret_federal_origem = "ajustado"
    lido.ret_federal_justificativa = "Aquisição de combustível — alíquota específica."
    lido.ret_federal_ajustado_por = "operador"
    lido.ret_federal_ajustado_em = "2026-06-02T12:00:00+00:00"
    store.salvar(lido)
    rel = store.obter(id_)
    assert rel.ret_federal_origem == "ajustado"
    assert rel.ret_federal_justificativa == "Aquisição de combustível — alíquota específica."
    assert rel.ret_federal_ajustado_por == "operador"
    store.fechar()


# ---------- Identidade do operador (tronco) — fonte de autoria, I-4 ----------

def test_operador_cadastro_e_atual(tmp_path):
    """Antes do cadastro não há operador; após salvar, `atual` devolve a identidade
    vigente com data de cadastro (fonte de criada_por/autor — I-4)."""
    from tronco.operador import StoreOperador
    s = StoreOperador(tmp_path / "operador.sqlite")
    assert s.existe() is False and s.atual() is None
    op = s.salvar("mnm", "Mubarak Nunes Machado")
    assert op.iniciais == "MNM" and op.nome == "Mubarak Nunes Machado"
    assert op.cadastrado_em is not None
    lido = s.atual()
    assert lido.iniciais == "MNM" and lido.nome == "Mubarak Nunes Machado"
    assert s.existe() is True
    s.fechar()


def test_operador_iniciais_normalizadas_e_validadas(tmp_path):
    """Iniciais viram caixa alta sem símbolos/espaços (entram no numero da NPP sem
    quebrá-lo); iniciais ou nome vazios são erro (I-6, não inventa identidade)."""
    from tronco.operador import StoreOperador
    s = StoreOperador(tmp_path / "operador.sqlite")
    assert s.salvar("m.n.m ", "Fulano").iniciais == "MNM"
    with pytest.raises(ValueError):
        s.salvar("", "Sem Iniciais")
    with pytest.raises(ValueError):
        s.salvar(".-/", "Só Símbolos")
    with pytest.raises(ValueError):
        s.salvar("MNM", "   ")
    s.fechar()


def test_operador_edicao_mantem_historico_e_vigente(tmp_path):
    """Reeditar a identidade não apaga a anterior (append, I-4); `atual` é a última."""
    from tronco.operador import StoreOperador
    s = StoreOperador(tmp_path / "operador.sqlite")
    s.salvar("ABC", "Antiga")
    s.salvar("XYZ", "Nova")
    assert s.atual().iniciais == "XYZ" and s.atual().nome == "Nova"
    s.fechar()


# ---------- NPP — entidade de vínculo nota->NPP->contrato (tronco) ----------

def test_npp_criar_gera_numero_e_audita(tmp_path):
    """Criar gera o numero portátil (NPP_<iniciais>_<AAAAMMDD>_<NNNN>) e grava autoria
    e datas (I-4); a NPP é recuperável por id."""
    from datetime import datetime, timezone
    from tronco.npp import StoreNPP
    s = StoreNPP(tmp_path / "npps.sqlite")
    dia = datetime(2026, 6, 2, tzinfo=timezone.utc)
    npp = s.criar(contrato_id=7, competencia="2026-05", iniciais="MNM",
                  autor="Mubarak Nunes Machado", rotulo="maio/parcela 1", agora=dia)
    assert npp.numero == "NPP_MNM_20260602_0001"
    assert npp.id is not None and npp.criada_por == "Mubarak Nunes Machado"
    assert npp.criada_em == npp.atualizada_em
    assert s.obter(npp.id).competencia == "2026-05"
    s.fechar()


def test_npp_sequencia_por_dia_reinicia(tmp_path):
    """NNNN incrementa no mesmo dia e reinicia em outro dia (sequência local por data)."""
    from datetime import datetime, timezone
    from tronco.npp import StoreNPP
    s = StoreNPP(tmp_path / "npps.sqlite")
    d1 = datetime(2026, 6, 2, tzinfo=timezone.utc)
    d2 = datetime(2026, 6, 3, tzinfo=timezone.utc)
    a = s.criar(contrato_id=1, competencia="2026-05", iniciais="MNM", autor="x", agora=d1)
    b = s.criar(contrato_id=1, competencia="2026-05", iniciais="MNM", autor="x", agora=d1)
    c = s.criar(contrato_id=2, competencia="2026-06", iniciais="MNM", autor="x", agora=d2)
    assert a.numero.endswith("20260602_0001")
    assert b.numero.endswith("20260602_0002")   # mesmo dia -> incrementa
    assert c.numero.endswith("20260603_0001")   # outro dia -> reinicia
    s.fechar()


def test_npp_par_contrato_competencia_nao_e_unico(tmp_path):
    """Decisão do humano: vários NPPs no mesmo (contrato, competência) coexistem."""
    from tronco.npp import StoreNPP
    s = StoreNPP(tmp_path / "npps.sqlite")
    a = s.criar(contrato_id=7, competencia="2026-05", iniciais="AB", autor="x")
    b = s.criar(contrato_id=7, competencia="2026-05", iniciais="AB", autor="x")
    assert a.id != b.id and a.numero != b.numero
    assert len(s.listar_por_contrato(7)) == 2
    s.fechar()


def test_npp_salvar_atualiza_sem_mudar_numero(tmp_path):
    """salvar() atualiza rótulo/observações/competência; o numero (identidade) é imutável."""
    from tronco.npp import StoreNPP
    s = StoreNPP(tmp_path / "npps.sqlite")
    npp = s.criar(contrato_id=7, competencia="2026-05", iniciais="AB", autor="x", rotulo="v1")
    numero = npp.numero
    npp.rotulo, npp.observacoes = "v2", "ajuste"
    s.salvar(npp)
    lido = s.obter(npp.id)
    assert lido.rotulo == "v2" and lido.observacoes == "ajuste" and lido.numero == numero
    s.fechar()


def test_npp_criar_exige_contrato_competencia_iniciais(tmp_path):
    """I-6: criar sem contrato, competência ou iniciais é erro visível; salvar() numa
    NPP nova (sem id) também é erro (use criar)."""
    from tronco.npp import StoreNPP, NPP
    s = StoreNPP(tmp_path / "npps.sqlite")
    with pytest.raises(ValueError):
        s.criar(contrato_id=None, competencia="2026-05", iniciais="AB", autor="x")
    with pytest.raises(ValueError):
        s.criar(contrato_id=7, competencia="  ", iniciais="AB", autor="x")
    with pytest.raises(ValueError):
        s.criar(contrato_id=7, competencia="2026-05", iniciais="", autor="x")
    with pytest.raises(ValueError):
        s.salvar(NPP(contrato_id=7, competencia="2026-05"))
    s.fechar()


# ---------- Vínculo nota->NPP em StoreNotas (I-1/I-6) ----------

def test_notas_vinculo_npp_e_listar_por_npp(tmp_path):
    """salvar grava o npp_id; listar/listar_por_npp devolvem o vínculo e filtram."""
    from tronco.notas import StoreNotas
    s = StoreNotas(tmp_path / "n.sqlite")
    r = _reg("nfe_exemplo.xml")
    s.salvar(r.chave, "NFE", r.to_dict(), "x.xml", npp_id=1)
    s.salvar("9" * 44, "NFE", r.to_dict(), "y.xml", npp_id=2)
    assert {n["chave"] for n in s.listar_por_npp(1)} == {r.chave}
    assert s.listar_por_npp(1)[0]["npp_id"] == 1
    assert len(s.listar_por_npp(2)) == 1
    s.fechar()


def test_notas_reimport_mesma_npp_e_idempotente(tmp_path):
    """Reimportar a mesma chave na MESMA NPP não duplica e não levanta conflito (I-1)."""
    from tronco.notas import StoreNotas
    s = StoreNotas(tmp_path / "n.sqlite")
    r = _reg("nfe_exemplo.xml")
    s.salvar(r.chave, "NFE", r.to_dict(), "x.xml", npp_id=1)
    s.salvar(r.chave, "NFE", r.to_dict(), "x.xml", npp_id=1)   # reimport mesma NPP
    assert s.contar() == 1 and len(s.listar_por_npp(1)) == 1
    s.fechar()


def test_notas_reimport_outra_npp_e_conflito_visivel(tmp_path):
    """Reimportar uma chave já vinculada a OUTRA NPP é conflito visível, não sobrescreve
    (I-1/I-6): o erro carrega a NPP onde a nota já consta."""
    from tronco.notas import StoreNotas, ConflitoDeChave
    s = StoreNotas(tmp_path / "n.sqlite")
    r = _reg("nfe_exemplo.xml")
    s.salvar(r.chave, "NFE", r.to_dict(), "x.xml", npp_id=1)
    with pytest.raises(ConflitoDeChave) as exc:
        s.salvar(r.chave, "NFE", r.to_dict(), "x.xml", npp_id=2)
    assert exc.value.npp_id_existente == 1
    # não moveu: segue na NPP 1, intacta
    assert len(s.listar_por_npp(1)) == 1 and s.listar_por_npp(2) == []
    s.fechar()


def test_notas_migracao_adiciona_npp_id(tmp_path):
    """Banco criado por versão anterior (sem npp_id) ganha a coluna na abertura (I-6)."""
    import sqlite3
    bd = tmp_path / "notas.sqlite"
    conn = sqlite3.connect(str(bd))
    conn.execute("CREATE TABLE notas (chave TEXT PRIMARY KEY, tipo TEXT NOT NULL, "
                 "origem TEXT, dados_json TEXT NOT NULL, importado_em TEXT NOT NULL)")
    conn.execute("INSERT INTO notas VALUES ('VELHA','NFE','v.xml','{}','2025-01-01T00:00:00+00:00')")
    conn.commit(); conn.close()
    from tronco.notas import StoreNotas
    s = StoreNotas(bd)                       # abre -> migra
    velha = [n for n in s.listar() if n["chave"] == "VELHA"][0]
    assert velha["npp_id"] is None           # legado sem vínculo, sem quebrar
    s.salvar("NOVA", "NFE", {}, "n.xml", npp_id=5)
    assert s.listar_por_npp(5)[0]["chave"] == "NOVA"
    s.fechar()


# ---------- Validação de retenção pelo operador (Fase 2, validação humana) ----------

def test_validacao_retencao_round_trip_e_normaliza(tmp_path):
    """validar grava a decisão do operador com autor+data (I-4) e normaliza o valor;
    atual devolve a vigente."""
    from tronco.validacao_retencao import StoreValidacaoRetencao
    s = StoreValidacaoRetencao(tmp_path / "v.sqlite")
    assert s.atual("NOTA1", "IR") is None
    s.validar("NOTA1", "IR", "confirmado", "48.00", "Mubarak")
    v = s.atual("NOTA1", "IR")
    assert v["acao"] == "confirmado" and v["valor"] == "48.00" and v["autor"] == "Mubarak"
    assert v["validado_em"]
    # entrada pt-BR / sem casas decimais é normalizada para X.XX
    s.validar("NOTA1", "INSS", "retificado", "1.200,5", "Mubarak")
    assert s.atual("NOTA1", "INSS")["valor"] == "1200.50"
    s.fechar()


def test_validacao_retencao_append_mantem_vigente(tmp_path):
    """Retificar depois de confirmar não apaga o histórico (I-4); a vigente é a última."""
    from tronco.validacao_retencao import StoreValidacaoRetencao
    s = StoreValidacaoRetencao(tmp_path / "v.sqlite")
    s.validar("NOTA1", "ISS", "confirmado", "50.00", "op")
    s.validar("NOTA1", "ISS", "retificado", "40.00", "op")
    v = s.atual("NOTA1", "ISS")
    assert v["acao"] == "retificado" and v["valor"] == "40.00"
    s.fechar()


def test_validacao_retencao_atuais_mapa_por_tributo(tmp_path):
    """atuais devolve a vigente por tributo (uma consulta) — base do total retido/líquido."""
    from tronco.validacao_retencao import StoreValidacaoRetencao
    s = StoreValidacaoRetencao(tmp_path / "v.sqlite")
    s.validar("NOTA1", "IR", "confirmado", "48.00", "op")
    s.validar("NOTA1", "CSLL", "confirmado", "10.00", "op")
    s.validar("NOTA1", "IR", "retificado", "45.00", "op")    # vigente do IR
    mapa = s.atuais("NOTA1")
    assert set(mapa) == {"IR", "CSLL"}
    assert mapa["IR"]["valor"] == "45.00" and mapa["CSLL"]["valor"] == "10.00"
    assert s.atuais("OUTRA") == {}
    s.fechar()


def test_validacao_retencao_valida_entradas(tmp_path):
    """I-6: tributo/ação inválidos, valor não-numérico ou autor vazio são erro visível —
    nada gravado."""
    from tronco.validacao_retencao import StoreValidacaoRetencao
    s = StoreValidacaoRetencao(tmp_path / "v.sqlite")
    with pytest.raises(ValueError):
        s.validar("N", "XPTO", "confirmado", "10.00", "op")     # tributo inválido
    with pytest.raises(ValueError):
        s.validar("N", "IR", "chutado", "10.00", "op")          # ação inválida
    with pytest.raises(ValueError):
        s.validar("N", "IR", "confirmado", "abc", "op")         # valor não-numérico
    with pytest.raises(ValueError):
        s.validar("N", "IR", "confirmado", "10.00", "   ")      # autor vazio
    assert s.atuais("N") == {}                                  # nada gravado
    s.fechar()


# ---------- Passo 7a (UI): helpers puros da jornada NPP ----------

def test_npp_competencia_valida():
    """Competência só vale no formato AAAA-MM (01..12). Fora disso é barrada (I-6)."""
    from tronco.app import _competencia_valida
    assert _competencia_valida("2026-05")
    assert _competencia_valida("2026-12")
    assert _competencia_valida("2026-01")
    assert not _competencia_valida("2026-13")     # mês inválido
    assert not _competencia_valida("2026-00")
    assert not _competencia_valida("2026-5")      # sem zero à esquerda
    assert not _competencia_valida("05/2026")     # formato humano, não ISO
    assert not _competencia_valida("")


def test_npp_divergencia_cnpj_e_visivel():
    """CNPJ da nota × prestador do contrato divergente é sinalizado (I-6), nunca
    bloqueia nem decide nada; contrato ausente/sem documento não gera ruído."""
    from tronco.app import _divergencias_cnpj
    from tronco.contratos import Contrato
    from tronco.ingestao import ingerir
    res = ingerir(EXEMPLOS / "nfe_exemplo.xml")     # NF-e: confere pelo emit_cnpj
    igual = Contrato(prest_documento=res.registro.emit_cnpj)
    diferente = Contrato(prest_documento="00000000000000")
    assert _divergencias_cnpj([res], igual) == []
    assert _divergencias_cnpj([res], diferente)     # lista não-vazia = aviso
    assert _divergencias_cnpj([res], None) == []    # sem contrato → sem ruído


# ---------- Passo 7b (UI): conferência via NPP + validação humana ----------

def test_npp_conferir_por_tipo_despacha():
    """Despacho por tipo (galhos independentes): NF-e não-optante rende federal;
    NFS-e rende federal + INSS/ISS conforme o contrato. Só sugestão (I-3)."""
    from tronco.app import _conferir_por_tipo
    from tronco.contratos import Contrato
    from tronco.ingestao import ingerir
    nfe = ingerir(EXEMPLOS / "nfe_exemplo.xml").registro          # CRT=3, não optante
    c = Contrato(ret_federal_sujeito=True, ret_federal_ir_pct="1.2",
                 ret_federal_codigo_receita="6190")
    achados = {a.tributo for a in _conferir_por_tipo(nfe, "NFE", c).achados}
    assert achados == {"IR", "CSLL", "COFINS", "PIS"}             # NF-e: só federal
    assert "INSS" not in achados and "ISS" not in achados


def test_npp_pendente_validacao_marca_liquido_provisorio():
    """Tributo aplicável não validado deixa o líquido provisório (I-6); sugestão zero
    (não incide) não pendura; validado deixa de pender."""
    from tronco.app import _pendente_validacao
    from tronco.retencao_federal import Achado
    aplic = Achado("IR", "IR 1,2%", "240.00", "120.00", "diverge")
    zero = Achado("PIS", "PIS não incide", None, "0.00", "confere")
    assert _pendente_validacao(aplic, None) is True
    assert _pendente_validacao(zero, None) is False
    assert _pendente_validacao(aplic, {"valor": "120.00", "acao": "retificado"}) is False


def test_npp_grupos_impostos_camadas_e_total_retido(tmp_path):
    """Seção 2: as 3 camadas coexistem. Antes de validar, total retido = 0 e líquido
    provisório (I-6). Após confirmar/retificar, o validado entra no total — o destaque
    do emitente segue intocado (I-2) e a sugestão nunca é gravada sozinha (I-3)."""
    from tronco.app import _grupos_impostos
    from tronco.validacao_retencao import StoreValidacaoRetencao
    from tronco.marcacoes import StoreMarcacoes
    from tronco.contratos import Contrato
    from tronco.ingestao import ingerir
    reg = ingerir(EXEMPLOS / "nfse_com_material.xml").registro
    contrato = Contrato(prest_documento=reg.prest_cnpj, ret_federal_sujeito=True,
                        ret_federal_ir_pct="4.8", ret_federal_codigo_receita="6190",
                        material_previsao="nao")     # sem gating de material
    itens = [{"reg": reg, "tipo": "NFSE", "valor": reg.valor_servicos,
              "ja_exportada": False}]
    vs = StoreValidacaoRetencao(tmp_path / "v.sqlite")
    ms = StoreMarcacoes(tmp_path / "m.sqlite")

    grupos, total, prov = _grupos_impostos(itens, contrato, vs, ms)
    fed = next(g for g in grupos if g["label"] == "Tributos federais")
    assert {r["tributo"] for r in fed["rows"]} == {"IR", "CSLL", "COFINS", "PIS"}
    ir = next(r for r in fed["rows"] if r["tributo"] == "IR")
    assert ir["destaque"] == reg.ir_destaque_emitente     # I-2: destaque fiel exibido
    assert ir["esperado"] is not None and ir["validacao"] is None   # I-3: sugestão sem gravar
    assert total == "0.00" and prov is True               # nada validado → provisório

    vs.validar(reg.chave, "IR", "confirmado", reg.ir_destaque_emitente, "op")
    grupos, total, prov = _grupos_impostos(itens, contrato, vs, ms)
    assert total == reg.ir_destaque_emitente              # validado entra no total retido
    fed = next(g for g in grupos if g["label"] == "Tributos federais")
    assert next(r for r in fed["rows"] if r["tributo"] == "IR")["validacao"]["acao"] == "confirmado"
    vs.fechar(); ms.fechar()


# ---------- Passo 7c (UI): exportação por NPP + idempotência ----------

def test_npp_exportar_idempotente_e_artefato(tmp_path):
    """Exportação por NPP: as notas novas da NPP entram num lote, registradas por
    chave (I-1), gerando um artefato novo (I-5); reexportar não duplica."""
    import tronco.app as A
    from tronco.operador import StoreOperador
    from tronco.npp import StoreNPP
    from tronco.notas import StoreNotas
    from tronco.contratos import StoreContratos
    from tronco.idempotencia import RegistroDeExportacao
    from tronco.marcacoes import StoreMarcacoes
    from tronco.validacao_retencao import StoreValidacaoRetencao

    A.StoreOperador = lambda *a, **k: StoreOperador(tmp_path / "op.sqlite")
    A.StoreNPP = lambda *a, **k: StoreNPP(tmp_path / "npp.sqlite")
    A.StoreNotas = lambda *a, **k: StoreNotas(tmp_path / "notas.sqlite")
    A.StoreContratos = lambda *a, **k: StoreContratos(tmp_path / "contr.sqlite")
    A.RegistroDeExportacao = lambda *a, **k: RegistroDeExportacao(tmp_path / "exp.sqlite")
    A.StoreMarcacoes = lambda *a, **k: StoreMarcacoes(tmp_path / "marc.sqlite")
    A.StoreValidacaoRetencao = lambda *a, **k: StoreValidacaoRetencao(tmp_path / "val.sqlite")
    A.PASTA_SAIDA = tmp_path / "exportacoes"
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()

    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    cs = StoreContratos(tmp_path / "contr.sqlite"); cid = cs.salvar(_contrato()); cs.fechar()
    cli.post("/npps", data={"contrato_id": str(cid), "competencia": "2026-05"})
    nid = StoreNPP(tmp_path / "npp.sqlite").listar()[0].id
    cli.post(f"/npp/{nid}/importar/exemplos")
    n = len(StoreNotas(tmp_path / "notas.sqlite").listar_por_npp(nid))
    assert n > 0

    r = cli.post(f"/npp/{nid}/exportar", follow_redirects=True)
    assert r.status_code == 200
    reg = RegistroDeExportacao(tmp_path / "exp.sqlite")
    assert len(reg.listar()) == n                       # I-1: todas registradas por chave
    reg.fechar()
    assert len(list((tmp_path / "exportacoes").glob("*.csv"))) == 1   # I-5: artefato novo

    cli.post(f"/npp/{nid}/exportar", follow_redirects=True)            # reexportar
    reg = RegistroDeExportacao(tmp_path / "exp.sqlite")
    assert len(reg.listar()) == n                       # idempotência: nada duplicado
    reg.fechar()


# ---------- Passo 8: reset inclui NPP + validações, preserva o operador ----------

def test_redefinir_inclui_npp_e_validacoes_preserva_operador(tmp_path):
    """O reset zera NPPs e validações de retenção (com backup antes, I-6) e NÃO toca o
    cadastro do operador — identidade da máquina, fora da lista de bancos a zerar."""
    from datetime import datetime, timezone
    from tronco.npp import StoreNPP
    from tronco.validacao_retencao import StoreValidacaoRetencao
    from tronco.operador import StoreOperador

    # o default já inclui os dois novos bancos e exclui o operador
    nomes = {Path(b).name for b in redefinicao.BANCOS_PADRAO}
    assert {"npps.sqlite", "validacoes_retencao.sqlite"} <= nomes
    assert "operador.sqlite" not in nomes

    bd_npp = tmp_path / "npps.sqlite"
    bd_val = tmp_path / "validacoes_retencao.sqlite"
    bd_op = tmp_path / "operador.sqlite"
    s = StoreNPP(bd_npp)
    s.criar(contrato_id=1, competencia="2026-05", iniciais="MNM", autor="Mubarak",
            agora=datetime(2026, 6, 2, tzinfo=timezone.utc)); s.fechar()
    v = StoreValidacaoRetencao(bd_val)
    v.validar("CH", "IR", "confirmado", "10.00", "Mubarak"); v.fechar()
    StoreOperador(bd_op).salvar("MNM", "Mubarak")

    resumo = redefinicao.redefinir_dados(bancos=(bd_npp, bd_val), pastas=(),
                                         pasta_backup=tmp_path / "bkp")
    assert not bd_npp.exists() and not bd_val.exists()              # zerados
    assert (Path(resumo["backup"]) / "npps.sqlite").exists()        # backup antes (I-6)
    assert (Path(resumo["backup"]) / "validacoes_retencao.sqlite").exists()
    assert StoreNPP(bd_npp).listar() == []                          # recriado vazio
    assert StoreValidacaoRetencao(bd_val).atuais("CH") == {}
    assert bd_op.exists() and StoreOperador(bd_op).atual().iniciais == "MNM"  # preservado


# ---------- Catálogo de regras: código sequencial automático (TF-/INSS-/ISS-) ----------

def test_proximo_codigo_sequencial_por_prefixo(tmp_path):
    """O código é controlado pelo sistema: sequencial por prefixo de grupo, zero-padded;
    segue o maior já gravado (resistente a remoções no meio)."""
    from galho_nfse.catalogo_federal import StoreRegrasFederais
    from galho_nfse.enquadramento import RegraEnquadramento
    s = StoreRegrasFederais(tmp_path / "r.sqlite")
    assert s.proximo_codigo("TF") == "TF-001"
    s.salvar(RegraEnquadramento(codigo="TF-001", descricao="a", fundamento=""))
    s.salvar(RegraEnquadramento(codigo="TF-002", descricao="b", fundamento=""))
    assert s.proximo_codigo("TF") == "TF-003"
    assert s.proximo_codigo("INSS") == "INSS-001"   # grupo independente
    s.fechar()


def test_regra_rota_gera_codigo_e_natureza_unica(tmp_path, monkeypatch):
    """A rota cria a regra com código sequencial (usuário não digita) e natureza única."""
    import tronco.app as A
    from tronco.operador import StoreOperador
    from galho_nfse.catalogo_federal import StoreRegrasFederais
    monkeypatch.setattr(A, "StoreOperador", lambda *a, **k: StoreOperador(tmp_path / "op.sqlite"))
    monkeypatch.setattr(A, "StoreRegrasFederais", lambda *a, **k: StoreRegrasFederais(tmp_path / "r.sqlite"))
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()
    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    cli.post("/regras", data={"descricao": "PJ não optante — serviço",
                              "natureza": "nao_optante", "sujeito": "on",
                              "ir_pct": "4.8", "csll": "on", "cofins": "on", "pis": "on",
                              "codigo_receita": "6190", "ordem": "1"})
    regras = StoreRegrasFederais(tmp_path / "r.sqlite").listar()
    assert len(regras) == 1
    r = regras[0]
    assert r.codigo == "TF-001"                 # gerado pelo sistema
    assert r.naturezas == ("nao_optante",)      # seleção única
    assert r.categorias == ()                   # categoria removida
    assert r.ir_pct == "4.8" and r.codigo_receita == "6190"


# ---------- Contrato: enquadramento federal por SELEÇÃO de regra (sem sugestão) ----------

def test_contrato_seleciona_regra_do_catalogo(tmp_path, monkeypatch):
    """O contrato copia o efeito da regra ESCOLHIDA no catálogo (origem 'derivado'); sem
    regra e sem ajuste manual é barrado (I-6). Sem heurística/sugestão automática."""
    import tronco.app as A
    from tronco.operador import StoreOperador
    from tronco.contratos import StoreContratos
    from galho_nfse.catalogo_federal import StoreRegrasFederais
    from galho_nfse.enquadramento import RegraEnquadramento
    monkeypatch.setattr(A, "StoreOperador", lambda *a, **k: StoreOperador(tmp_path / "op.sqlite"))
    monkeypatch.setattr(A, "StoreContratos", lambda *a, **k: StoreContratos(tmp_path / "c.sqlite"))
    monkeypatch.setattr(A, "StoreRegrasFederais", lambda *a, **k: StoreRegrasFederais(tmp_path / "r.sqlite"))
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()
    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    rs = StoreRegrasFederais(tmp_path / "r.sqlite")
    rid = rs.salvar(RegraEnquadramento(codigo="TF-001", descricao="serviço", fundamento="",
                    naturezas=("nao_optante",), sujeito=True, ir_pct="4.8",
                    csll=True, cofins=True, pis=True, codigo_receita="6190"))
    rs.fechar()
    cli.post("/contratos", data={"prest_identificacao": "ACME", "prest_documento": "11222333000181",
             "prest_natureza": "nao_optante", "numero": "10", "ano": "2026",
             "ret_federal_regra_id": str(rid)})
    ct = StoreContratos(tmp_path / "c.sqlite").listar()[0]
    assert ct.ret_federal_regra_codigo == "TF-001" and ct.ret_federal_origem == "derivado"
    assert ct.ret_federal_ir_pct == "4.8" and ct.ret_federal_sujeito is True
    assert ct.ret_federal_codigo_receita == "6190"

    # sem regra e sem ajuste manual: barrado, nada salvo
    r = cli.post("/contratos", data={"prest_identificacao": "X", "prest_documento": "1",
                 "numero": "9", "ano": "2026"})
    assert r.status_code == 200 and "Selecione a regra".encode() in r.data
    assert len(StoreContratos(tmp_path / "c.sqlite").listar()) == 1   # nada novo gravado


# ---------- Fase 1 (UX): confirmação de destaques em lote na NPP ----------

def test_npp_confirmar_destaques_em_lote(tmp_path, monkeypatch):
    """Confirmação em lote ateste o destaque do EMITENTE para os tributos pendentes que
    têm destaque. I-3: a seleção é mecânica (pendente + tem destaque), não por conformidade
    com a sugestão. I-2: o valor gravado é o destaque recomputado no servidor. I-4: gravado
    com autor. Idempotente: re-rodar não cria novas validações vigentes."""
    import tronco.app as A
    from tronco.operador import StoreOperador
    from tronco.npp import StoreNPP
    from tronco.notas import StoreNotas
    from tronco.contratos import StoreContratos
    from tronco.idempotencia import RegistroDeExportacao
    from tronco.marcacoes import StoreMarcacoes
    from tronco.validacao_retencao import StoreValidacaoRetencao

    monkeypatch.setattr(A, "StoreOperador", lambda *a, **k: StoreOperador(tmp_path / "op.sqlite"))
    monkeypatch.setattr(A, "StoreNPP", lambda *a, **k: StoreNPP(tmp_path / "npp.sqlite"))
    monkeypatch.setattr(A, "StoreNotas", lambda *a, **k: StoreNotas(tmp_path / "notas.sqlite"))
    monkeypatch.setattr(A, "StoreContratos", lambda *a, **k: StoreContratos(tmp_path / "contr.sqlite"))
    monkeypatch.setattr(A, "RegistroDeExportacao", lambda *a, **k: RegistroDeExportacao(tmp_path / "exp.sqlite"))
    monkeypatch.setattr(A, "StoreMarcacoes", lambda *a, **k: StoreMarcacoes(tmp_path / "marc.sqlite"))
    monkeypatch.setattr(A, "StoreValidacaoRetencao", lambda *a, **k: StoreValidacaoRetencao(tmp_path / "val.sqlite"))
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()

    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    cs = StoreContratos(tmp_path / "contr.sqlite")
    cid = cs.salvar(_contrato(iss_retido_tomador=True, iss_aliquota="5",
                              ret_federal_sujeito=True, ret_federal_ir_pct="4.8")); cs.fechar()
    cli.post("/npps", data={"contrato_id": str(cid), "competencia": "2026-05"})
    nid = StoreNPP(tmp_path / "npp.sqlite").listar()[0].id
    cli.post(f"/npp/{nid}/importar/exemplos")

    # esperado = tributos pendentes COM destaque (mesmo critério mecânico da rota)
    contrato = StoreContratos(tmp_path / "contr.sqlite").obter(cid)
    esperado = 0
    for it in A._itens_da_npp(nid):
        mat = it["marcacao"]["valor"] if it["marcacao"] else None
        for a in A._conferir_por_tipo(it["reg"], it["tipo"], contrato, mat).achados:
            if A._pendente_validacao(a, None) and a.destaque_emitente is not None:
                esperado += 1
    assert esperado > 0

    cli.post(f"/npp/{nid}/confirmar-destaques", follow_redirects=True)
    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    total = 0
    for it in A._itens_da_npp(nid):
        atuais = v.atuais(it["reg"].chave)
        total += len(atuais)
        assert all(x["acao"] == "confirmado" for x in atuais.values())   # I-3: só confirma destaque
        assert all(x["autor"] == "Op" for x in atuais.values())          # I-4: autoria
    v.fechar()
    assert total == esperado

    # idempotente: re-rodar não cria novas vigentes
    cli.post(f"/npp/{nid}/confirmar-destaques", follow_redirects=True)
    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    total2 = sum(len(v.atuais(it["reg"].chave)) for it in A._itens_da_npp(nid))
    v.fechar()
    assert total2 == esperado


def test_npp_validar_inline_json(tmp_path, monkeypatch):
    """Validação inline (fetch): a rota responde JSON com fragmentos renderizados pelo
    servidor. I-2: 'confirmado' grava o destaque recomputado no servidor (o cliente não
    envia valor). I-4: gravado com autor. I-6: valor inválido volta ok:false (422), nada
    gravado. Sem o header de fetch, o caminho antigo (redirect) segue intacto."""
    import tronco.app as A
    from tronco import formato
    from tronco.operador import StoreOperador
    from tronco.npp import StoreNPP
    from tronco.notas import StoreNotas
    from tronco.contratos import StoreContratos
    from tronco.idempotencia import RegistroDeExportacao
    from tronco.marcacoes import StoreMarcacoes
    from tronco.validacao_retencao import StoreValidacaoRetencao

    monkeypatch.setattr(A, "StoreOperador", lambda *a, **k: StoreOperador(tmp_path / "op.sqlite"))
    monkeypatch.setattr(A, "StoreNPP", lambda *a, **k: StoreNPP(tmp_path / "npp.sqlite"))
    monkeypatch.setattr(A, "StoreNotas", lambda *a, **k: StoreNotas(tmp_path / "notas.sqlite"))
    monkeypatch.setattr(A, "StoreContratos", lambda *a, **k: StoreContratos(tmp_path / "contr.sqlite"))
    monkeypatch.setattr(A, "RegistroDeExportacao", lambda *a, **k: RegistroDeExportacao(tmp_path / "exp.sqlite"))
    monkeypatch.setattr(A, "StoreMarcacoes", lambda *a, **k: StoreMarcacoes(tmp_path / "marc.sqlite"))
    monkeypatch.setattr(A, "StoreValidacaoRetencao", lambda *a, **k: StoreValidacaoRetencao(tmp_path / "val.sqlite"))
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()
    FETCH = {"X-Requested-With": "fetch"}

    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    cs = StoreContratos(tmp_path / "contr.sqlite")
    cid = cs.salvar(_contrato(iss_retido_tomador=True, iss_aliquota="5",
                              ret_federal_sujeito=True, ret_federal_ir_pct="4.8")); cs.fechar()
    cli.post("/npps", data={"contrato_id": str(cid), "competencia": "2026-05"})
    nid = StoreNPP(tmp_path / "npp.sqlite").listar()[0].id
    cli.post(f"/npp/{nid}/importar/exemplos")

    # acha uma (nota, tributo) pendente COM destaque do emitente
    contrato = StoreContratos(tmp_path / "contr.sqlite").obter(cid)
    chave = tributo = destaque = None
    for it in A._itens_da_npp(nid):
        mat = it["marcacao"]["valor"] if it["marcacao"] else None
        for a in A._conferir_por_tipo(it["reg"], it["tipo"], contrato, mat).achados:
            if A._pendente_validacao(a, None) and a.destaque_emitente is not None:
                chave, tributo, destaque = it["reg"].chave, a.tributo, a.destaque_emitente
                break
        if chave:
            break
    assert chave, "esperava ao menos um tributo com destaque para validar"
    url = f"/npp/{nid}/validar/{chave}/{tributo}"

    # I-6: valor inválido → 422 ok:false, nada gravado (antes de qualquer validação)
    r = cli.post(url, data={"acao": "retificado", "valor": "abc"}, headers=FETCH)
    assert r.status_code == 422 and r.is_json and r.get_json()["ok"] is False
    assert r.get_json()["mensagem"]
    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    assert tributo not in v.atuais(chave); v.fechar()

    # I-2/I-4: confirmar (sem enviar valor) grava o destaque recomputado, com autor
    r = cli.post(url, data={"acao": "confirmado"}, headers=FETCH)
    assert r.status_code == 200 and r.is_json
    data = r.get_json()
    assert data["ok"] is True and data["chave"] == chave and data["tributo"] == tributo
    assert "validado" in data["cel_situacao"] and "Revalidar" in data["cel_validar"]
    for campo in ("progresso", "total_retido", "liquido", "grupo_total", "n_pendentes"):
        assert campo in data
    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    atual = v.atuais(chave)[tributo]; v.fechar()
    assert atual["acao"] == "confirmado" and atual["autor"] == "Op"
    assert atual["valor"] == formato.parse_valor(destaque)   # I-2: valor do servidor

    # retificar inline (append): vigente passa a ser o valor digitado pelo operador
    r = cli.post(url, data={"acao": "retificado", "valor": "9,99"}, headers=FETCH)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    atual = v.atuais(chave)[tributo]; v.fechar()
    assert atual["acao"] == "retificado" and atual["valor"] == formato.parse_valor("9,99")

    # sem o header de fetch: caminho antigo intacto (redirect, não JSON)
    r = cli.post(url, data={"acao": "confirmado"})
    assert r.status_code == 302 and not r.is_json


def test_agregar_federal_por_nota_e_alicota_agregada():
    """Agregação federal é apresentação POR NOTA (#7): cada nota rende UMA linha com o
    código de receita, a alíquota agregada derivada do contrato (nunca digitada) e a soma
    de conferência dos destaques fiéis dos tributos federais (I-2). Divergência entre
    destaque e sugestão em algum tributo marca a linha para conferência humana (I-6)."""
    from tronco.app import _agregar_federal
    c = _contrato(ret_federal_sujeito=True, ret_federal_ir_pct="4.8",
                  ret_federal_csll=True, ret_federal_cofins=True, ret_federal_pis=True)
    rows = [
        {"chave": "A", "nota_numero": "1", "tipo": "NFSE", "municipio": "Betim/MG",
         "tributo": "IR", "regra": "", "codigo": "6190", "destaque": "480.00",
         "esperado": "480.00", "situacao": "confere", "validacao": None, "pendente": True},
        {"chave": "A", "nota_numero": "1", "tipo": "NFSE", "municipio": "Betim/MG",
         "tributo": "CSLL", "regra": "", "codigo": "6190", "destaque": "100.00",
         "esperado": "120.00", "situacao": "diverge", "validacao": None, "pendente": True},
        {"chave": "B", "nota_numero": "2", "tipo": "NFE", "municipio": None,
         "tributo": "IR", "regra": "", "codigo": "6190", "destaque": "50.00",
         "esperado": "50.00", "situacao": "confere", "validacao": None, "pendente": True},
    ]
    por = {a["chave"]: a for a in _agregar_federal(rows, c)}
    assert set(por) == {"A", "B"}                            # uma linha por nota
    a = por["A"]
    assert a["codigo"] == "6190"
    assert a["aliquota_agregada"] == "9.45" and a["aliquota_txt"] == "9,45%"  # IR4,8+1+3+0,65
    assert a["soma_destaque"] == "580.00"                    # soma de conferência (I-2)
    assert a["divergente"] is True                           # CSLL: destaque≠sugestão
    assert por["B"]["divergente"] is False


def test_npp_abas_e_federal_agregado(tmp_path, monkeypatch):
    """Redesenho da NPP: duas abas (Documentos / Grupos de impostos) em progressive
    enhancement (ambos os painéis renderizados; ?aba marca o ativo) e o grupo federal
    agregado POR NOTA (6190 · 9,45%), com o resumo da nota devolvido na validação inline (#7)."""
    import tronco.app as A
    from tronco.operador import StoreOperador
    from tronco.npp import StoreNPP
    from tronco.notas import StoreNotas
    from tronco.contratos import StoreContratos
    from tronco.idempotencia import RegistroDeExportacao
    from tronco.marcacoes import StoreMarcacoes
    from tronco.validacao_retencao import StoreValidacaoRetencao

    monkeypatch.setattr(A, "StoreOperador", lambda *a, **k: StoreOperador(tmp_path / "op.sqlite"))
    monkeypatch.setattr(A, "StoreNPP", lambda *a, **k: StoreNPP(tmp_path / "npp.sqlite"))
    monkeypatch.setattr(A, "StoreNotas", lambda *a, **k: StoreNotas(tmp_path / "notas.sqlite"))
    monkeypatch.setattr(A, "StoreContratos", lambda *a, **k: StoreContratos(tmp_path / "contr.sqlite"))
    monkeypatch.setattr(A, "RegistroDeExportacao", lambda *a, **k: RegistroDeExportacao(tmp_path / "exp.sqlite"))
    monkeypatch.setattr(A, "StoreMarcacoes", lambda *a, **k: StoreMarcacoes(tmp_path / "marc.sqlite"))
    monkeypatch.setattr(A, "StoreValidacaoRetencao", lambda *a, **k: StoreValidacaoRetencao(tmp_path / "val.sqlite"))
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()

    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    cs = StoreContratos(tmp_path / "contr.sqlite")
    cid = cs.salvar(_contrato(ret_federal_sujeito=True, ret_federal_codigo_receita="6190",
                              ret_federal_ir_pct="4.8", ret_federal_csll=True,
                              ret_federal_cofins=True, ret_federal_pis=True,
                              inss_cessao_mao_obra=True, inss_aliquota="11",
                              iss_retido_tomador=True, iss_aliquota="5")); cs.fechar()
    cli.post("/npps", data={"contrato_id": str(cid), "competencia": "2026-05"})
    nid = StoreNPP(tmp_path / "npp.sqlite").listar()[0].id
    cli.post(f"/npp/{nid}/importar/exemplos")

    # abas (PE): default = documentos visível, impostos hidden; ?aba inverte; ambos no HTML
    import re
    html = cli.get(f"/npp/{nid}").get_data(as_text=True)
    assert 'role="tablist"' in html
    assert not re.search(r'id="painel-documentos"[^>]*\bhidden', html)
    assert re.search(r'id="painel-impostos"[^>]*\bhidden', html)
    html_i = cli.get(f"/npp/{nid}?aba=impostos").get_data(as_text=True)
    assert re.search(r'id="painel-documentos"[^>]*\bhidden', html_i)
    assert not re.search(r'id="painel-impostos"[^>]*\bhidden', html_i)

    # federal agregado por nota no HTML e na estrutura
    assert '6190' in html_i and '9,45%' in html_i and 'data-federal-chave=' in html_i
    contrato = StoreContratos(tmp_path / "contr.sqlite").obter(cid)
    grupos, _, _ = A._grupos_impostos(A._itens_da_npp(nid), contrato)
    federal = next(g for g in grupos if g["key"] == "federal")
    ag6190 = next(a for a in federal["agregados"] if a["codigo"] == "6190")
    assert ag6190["aliquota_txt"] == "9,45%" and ag6190["rows"] and ag6190["chave"]

    # validação inline de um tributo federal devolve o resumo da nota afetada
    chave = tributo = None
    for it in A._itens_da_npp(nid):
        for a in A._conferir_por_tipo(it["reg"], it["tipo"], contrato, None).achados:
            if a.tributo in ("IR", "CSLL", "COFINS", "PIS") and a.destaque_emitente is not None:
                chave, tributo = it["reg"].chave, a.tributo
                break
        if chave:
            break
    assert chave, "esperava um tributo federal com destaque"
    r = cli.post(f"/npp/{nid}/validar/{chave}/{tributo}", data={"acao": "confirmado"},
                 headers={"X-Requested-With": "fetch"})
    data = r.get_json()
    assert data["ok"] is True and data["federal_chave"] == chave
    assert "6190" in data["federal_resumo"]


def _seed_npp_impostos(tmp_path, monkeypatch, **contrato_kw):
    """Setup comum: stores em tmp, operador, contrato, NPP com os exemplos. Devolve
    (cli, A, nid, contrato)."""
    import tronco.app as A
    from tronco.operador import StoreOperador
    from tronco.npp import StoreNPP
    from tronco.notas import StoreNotas
    from tronco.contratos import StoreContratos
    from tronco.idempotencia import RegistroDeExportacao
    from tronco.marcacoes import StoreMarcacoes
    from tronco.validacao_retencao import StoreValidacaoRetencao
    monkeypatch.setattr(A, "StoreOperador", lambda *a, **k: StoreOperador(tmp_path / "op.sqlite"))
    monkeypatch.setattr(A, "StoreNPP", lambda *a, **k: StoreNPP(tmp_path / "npp.sqlite"))
    monkeypatch.setattr(A, "StoreNotas", lambda *a, **k: StoreNotas(tmp_path / "notas.sqlite"))
    monkeypatch.setattr(A, "StoreContratos", lambda *a, **k: StoreContratos(tmp_path / "contr.sqlite"))
    monkeypatch.setattr(A, "RegistroDeExportacao", lambda *a, **k: RegistroDeExportacao(tmp_path / "exp.sqlite"))
    monkeypatch.setattr(A, "StoreMarcacoes", lambda *a, **k: StoreMarcacoes(tmp_path / "marc.sqlite"))
    monkeypatch.setattr(A, "StoreValidacaoRetencao", lambda *a, **k: StoreValidacaoRetencao(tmp_path / "val.sqlite"))
    A.app.config.update(TESTING=True)
    cli = A.app.test_client()
    cli.post("/operador", data={"iniciais": "op", "nome": "Op"})
    cs = StoreContratos(tmp_path / "contr.sqlite")
    cid = cs.salvar(_contrato(**contrato_kw)); cs.fechar()
    cli.post("/npps", data={"contrato_id": str(cid), "competencia": "2026-05"})
    nid = StoreNPP(tmp_path / "npp.sqlite").listar()[0].id
    cli.post(f"/npp/{nid}/importar/exemplos")
    return cli, A, nid, StoreContratos(tmp_path / "contr.sqlite").obter(cid)


def test_npp_confirmar_conferem_so_os_que_conferem(tmp_path, monkeypatch):
    """#4: a confirmação por grupo grava SÓ os pendentes cujo destaque confere com a
    sugestão; divergências ficam intocadas para revisão (I-3/I-6). Grava o destaque fiel
    (I-2) com autor (I-4). Escopo: só o grupo pedido."""
    from tronco.app import _CATEGORIA, _confere_com_sugestao, _pendente_validacao
    from tronco.validacao_retencao import StoreValidacaoRetencao
    cli, A, nid, contrato = _seed_npp_impostos(
        tmp_path, monkeypatch, ret_federal_sujeito=True, ret_federal_codigo_receita="6190",
        ret_federal_ir_pct="4.8", ret_federal_csll=True, ret_federal_cofins=True,
        ret_federal_pis=True, inss_cessao_mao_obra=True, inss_aliquota="11",
        iss_retido_tomador=True, iss_aliquota="5")

    confere = set(); diverge = set()
    for it in A._itens_da_npp(nid):
        for a in A._conferir_por_tipo(it["reg"], it["tipo"], contrato, None).achados:
            if _CATEGORIA.get(a.tributo) != "federal" or not _pendente_validacao(a, None):
                continue
            (confere if _confere_com_sugestao(a) else
             (diverge if a.situacao == "diverge" else set())).add((it["reg"].chave, a.tributo))
    assert confere and diverge                      # exemplos têm os dois (sanidade)

    cli.post(f"/npp/{nid}/confirmar-conferem/federal", follow_redirects=True)

    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    validados = {(it["reg"].chave, t) for it in A._itens_da_npp(nid)
                 for t in v.atuais(it["reg"].chave)}
    v.fechar()
    assert validados == confere                     # exatamente os que conferem
    assert not (validados & diverge)                # nenhuma divergência tocada (I-3)
    assert all(_CATEGORIA.get(t) == "federal" for _, t in validados)  # só o grupo pedido


def test_npp_confirmar_agregado_federal_de_uma_nota(tmp_path, monkeypatch):
    """#7: o botão "Confirmar agregado" da linha federal grava de uma vez os tributos
    federais pendentes DAQUELA nota pelo destaque do emitente (I-2), cada um individual e
    auditável (I-4), sem tocar outras notas nem outros grupos (I-3)."""
    from tronco.app import _CATEGORIA, _pendente_validacao
    from tronco.validacao_retencao import StoreValidacaoRetencao
    cli, A, nid, contrato = _seed_npp_impostos(
        tmp_path, monkeypatch, ret_federal_sujeito=True, ret_federal_codigo_receita="6190",
        ret_federal_ir_pct="4.8", ret_federal_csll=True, ret_federal_cofins=True,
        ret_federal_pis=True, inss_cessao_mao_obra=True, inss_aliquota="11",
        iss_retido_tomador=True, iss_aliquota="5")

    alvo = None; esperado = set()
    for it in A._itens_da_npp(nid):
        fed = {a.tributo for a in A._conferir_por_tipo(it["reg"], it["tipo"], contrato, None).achados
               if _CATEGORIA.get(a.tributo) == "federal" and _pendente_validacao(a, None)
               and a.destaque_emitente is not None}
        if fed:
            alvo, esperado = it["reg"].chave, fed
            break
    assert alvo and len(esperado) > 1, "esperava nota com >1 federal pendente destacado"

    cli.post(f"/npp/{nid}/confirmar-agregado-federal/{alvo}", follow_redirects=True)

    v = StoreValidacaoRetencao(tmp_path / "val.sqlite")
    val_alvo = set(v.atuais(alvo))
    outras = {t for it in A._itens_da_npp(nid) if it["reg"].chave != alvo
              for t in v.atuais(it["reg"].chave)}
    v.fechar()
    assert val_alvo == esperado                          # exatamente os federais pendentes da nota
    assert all(_CATEGORIA.get(t) == "federal" for t in val_alvo)  # nada de INSS/ISS
    assert not outras                                    # nenhuma outra nota tocada (I-3)


def test_npp_ajustes_ui_municipio_diverge_colapsavel(tmp_path, monkeypatch):
    """#1 município é a 1ª coluna das tabelas de tributos; #2 linha divergente ganha
    realce (classe); #3 os grupos são colapsáveis (<details>)."""
    cli, A, nid, _ = _seed_npp_impostos(
        tmp_path, monkeypatch, ret_federal_sujeito=True, ret_federal_codigo_receita="6190",
        ret_federal_ir_pct="4.8", ret_federal_csll=True, ret_federal_cofins=True,
        ret_federal_pis=True, inss_cessao_mao_obra=True, inss_aliquota="11",
        iss_retido_tomador=True, iss_aliquota="5")
    html = cli.get(f"/npp/{nid}?aba=impostos").get_data(as_text=True)
    # #1: Município antes de Nota no cabeçalho da tabela de tributos
    th_mun = html.find('<th scope="col">Município</th>')
    th_nota = html.find('<th scope="col">Nota</th>')
    assert 0 < th_mun < th_nota
    # #2: há linha divergente realçada (exemplos divergem com este contrato)
    assert 'class="linha-diverge"' in html
    # #3: três grupos colapsáveis
    assert html.count('class="grupo-colapsavel"') == 3
    # #4: botão "Confirmar os que conferem" presente em algum grupo
    assert 'Confirmar os que conferem' in html


# ---------- Conferência no portal nacional (conveniência, não extração) ----------

def test_portal_consulta_aponta_para_o_ambiente_nacional():
    """Cada tipo aponta para o portal nacional oficial de consulta pública; tipo
    desconhecido NÃO inventa link (ausência visível — I-6). É conveniência de
    navegação, não extração de dado fiscal (I-2)."""
    from tronco.portais import portal_consulta
    nfe = portal_consulta("NFE")
    assert nfe and "nfe.fazenda.gov.br" in nfe["url"]
    nfse = portal_consulta("NFSE")
    assert nfse and "nfse.gov.br" in nfse["url"]
    assert portal_consulta("OUTRO") is None
    assert portal_consulta(None) is None


# ---------- Descrição do serviço pela LC 116/2003 (referência, não extração) ----------

def test_lc116_descricao_do_codigo_de_servico():
    """O cTribNac de 6 dígitos deriva o subitem (4 primeiros) e busca a redação
    oficial; código não localizado devolve None (a tela não inventa — I-6)."""
    from galho_nfse.lc116 import descricao_servico, subitem_de, LISTA_LC116
    assert len(LISTA_LC116) >= 200          # lista completa transcrita
    assert subitem_de("070201") == "7.02"
    assert descricao_servico("070201").startswith("Execução, por administração")
    assert descricao_servico("17.02").startswith("Datilografia")   # aceita subitem direto
    assert descricao_servico("999999") is None
    assert descricao_servico(None) is None


# ---------- Detalhe NFS-e: total retido (destaque) e grupos de tributos ----------

def test_total_retido_destaque_soma_federais_inss_e_iss_so_quando_retido():
    """Soma os destaques retidos (I-2: soma de valores fiéis, não apuração). ISS só
    entra quando o indicador diz retido (tpRetISSQN ∈ {2,3})."""
    from tronco.app import _total_retido_destaque
    com_mat = _reg("nfse_com_material.xml")     # ISS indicador '1' (não retido)
    assert _total_retido_destaque(com_mat) == "458.50"   # só federais; ISS fora
    simples = _reg("nfse_simples.xml")           # ISS indicador '2' (retido), federais 0
    assert _total_retido_destaque(simples) == "90.00"    # só o ISS retido


def test_grupos_conferencia_ordena_inss_federais_iss_com_destaque_e_sugestao():
    """Três grupos na ordem INSS → federais → ISS; cada um exibe o destaque do emitente
    (sempre, Fase 1) e, com contrato, a sugestão por tributo (Fase 2). Os federais
    agregam sob o código de receita."""
    from tronco.app import _grupos_conferencia, _conferir_por_tipo
    from tronco.contratos import Contrato
    reg = _reg("nfse_com_material.xml")
    # sem contrato: só destaque, sem código/sugestão
    g0 = _grupos_conferencia(reg, None, None)
    assert [x["key"] for x in g0] == ["inss", "federal", "iss"]
    fed0 = next(x for x in g0 if x["key"] == "federal")
    assert [l["tributo"] for l in fed0["linhas"]] == ["IR", "CSLL", "COFINS", "PIS"]
    assert fed0["soma_destaque"] == "458.50" and fed0["codigo"] is None
    assert all(l["esperado"] is None for x in g0 for l in x["linhas"])
    # com contrato: aparece o código de receita e a sugestão por tributo
    contrato = Contrato(prest_identificacao="ACME", prest_documento="11222333000181",
                        prest_natureza="nao_optante", numero="01", ano="2026",
                        categoria_servico="manutencao_predial", material_previsao="sim_discriminado",
                        ret_federal_sujeito=True, ret_federal_codigo_receita="6190",
                        ret_federal_csll=True, ret_federal_cofins=True, ret_federal_pis=True,
                        iss_retido_tomador=True, iss_aliquota="5")
    res = _conferir_por_tipo(reg, "NFSE", contrato, "sim")
    g1 = _grupos_conferencia(reg, res, contrato)
    fed1 = next(x for x in g1 if x["key"] == "federal")
    assert fed1["codigo"] == "6190" and fed1["aliquota_txt"]
    assert any(l["esperado"] is not None for l in fed1["linhas"])
