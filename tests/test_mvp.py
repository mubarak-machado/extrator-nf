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

def test_exportador_cria_artefato_e_recusa_sobrescrever():
    with tempfile.TemporaryDirectory() as d:
        exp = ExportadorCsvLocal(d)
        r = _reg("nfe_exemplo.xml")
        caminho = exp.exportar([r], "loteX")
        assert os.path.exists(caminho)
        with pytest.raises(FileExistsError):       # imutável por lote
            exp.exportar([r], "loteX")


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
