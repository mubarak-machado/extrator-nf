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
