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
        # e o estado volta ao inicial: nota antes exportada agora reabre como inédita
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


def test_conferencia_casa_por_cnpj_e_trata_ambiguidade():
    """casar_contratos casa por CNPJ e devolve TODOS — 0, 1 ou vários. A escolha
    entre vários é do humano (I-6), a função não decide."""
    from galho_nfse import retencao
    reg = _reg_nfse()
    c1 = _contrato(numero="07")
    c2 = _contrato(numero="08")
    outro = _contrato(prest_documento="99999999000100", numero="09")
    assert retencao.casar_contratos(reg, []) == []                 # nenhum
    assert len(retencao.casar_contratos(reg, [c1, outro])) == 1    # um
    assert len(retencao.casar_contratos(reg, [c1, c2, outro])) == 2  # vários (ambíguo)


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
