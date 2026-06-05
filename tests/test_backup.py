"""
Testes de backup (snapshot JSON) — organizados pelos invariantes que exercitam.

Cobrem o que o plano `docs/planos/backup-e-sincronizacao.md` exige do round-trip:
FK por chave natural (nunca rowid), `dados` da nota transcrito fielmente (I-2), autoria e
ledger preservados (I-1/I-4), integridade por hash (I-6) e o recorte por escopo.
"""
from __future__ import annotations

import pytest

from tronco import backup
from tronco.backup import Bancos
from tronco.contratos import Contrato, MunicipioIss
from galho_nfse.enquadramento import RegraEnquadramento
from galho_nfse.inss import RegraInss


@pytest.fixture
def bancos(tmp_path):
    b = Bancos.abrir(tmp_path)
    yield b
    b.fechar()


def _semear(b: Bancos) -> dict:
    """Cria operador, contrato (com município), regras, NPP, nota, marcação, validação e
    uma entrada de ledger. Devolve as referências úteis para as asserções."""
    b.operador.salvar("MNM", "Fulano de Tal")
    contrato = Contrato(prest_documento="12345678000199", numero="07", ano="2026",
                        prest_identificacao="Prestadora LTDA",
                        municipios=[MunicipioIss(municipio="Belo Horizonte", uf="MG",
                                                 iss_aliquota="5", iss_retido=True,
                                                 iss_recolhimento="dar")])
    contrato_id = b.contratos.salvar(contrato)
    b.federais.salvar(RegraEnquadramento(codigo="TF-001", descricao="Geral",
                                         fundamento="IN 1234/2012", sujeito=True,
                                         ir_pct="4.8", csll=True, cofins=True, pis=True))
    b.inss.salvar(RegraInss(codigo="INSS-001", descricao="Cessão", fundamento="IN 2110/2022",
                            cessao_mao_obra=True, aliquota="11"))
    npp = b.npps.criar(contrato_id=contrato_id, competencia="2026-05",
                       iniciais="MNM", autor="Fulano de Tal (MNM)")
    chave = "31260512345678000199550010000000011000000017"
    dados_nota = {"chave": chave, "tipo": "NFSE", "valor_total": "1000.00",
                  "discriminacao": "serviço com empregados materiais"}
    b.notas.salvar(chave, "NFSE", dados_nota, origem="nota.xml", npp_id=npp.id)
    b.marcacoes.marcar(chave, "sim", "Fulano (MNM)", valor_material="100.00")
    b.validacoes.validar(chave, "ISS", "confirmado", "50.00", "Fulano (MNM)")
    b.exportacoes.registrar_lote([(chave, "NFSE")], "lote-2026-05-A")
    return {"contrato_id": contrato_id, "npp": npp, "chave": chave, "dados_nota": dados_nota}


# ---------- envelope e integridade (I-6) ----------

def test_envelope_versionado_e_hash_confere(bancos):
    _semear(bancos)
    env = backup.exportar_configuracao(bancos)
    assert env["formato"] == "extrator-nf/snapshot"
    assert env["schema_versao"] == 1
    assert env["escopo"] == "configuracao"
    assert env["gerado_por"] == {"iniciais": "MNM", "nome": "Fulano de Tal"}
    # o hash bate com o recomputado sobre o bloco dados (detecta truncamento/corrupção)
    assert env["hash_conteudo"] == backup.hash_conteudo(env["dados"])
    assert env["contagem"]["contratos"] == 1
    assert env["contagem"]["regras_federais"] == 1
    assert env["contagem"]["regras_inss"] == 1


def test_hash_muda_se_dados_forem_adulterados(bancos):
    _semear(bancos)
    env = backup.exportar_configuracao(bancos)
    env["dados"]["contratos"][0]["numero"] = "ADULTERADO"
    assert env["hash_conteudo"] != backup.hash_conteudo(env["dados"])


# ---------- FK por chave natural, nunca rowid (regra de ouro, I-6) ----------

def test_contrato_sem_rowid_com_chave_natural(bancos):
    ref = _semear(bancos)
    env = backup.exportar_contrato(bancos, ref["contrato_id"])
    c = env["dados"]["contratos"][0]
    assert "id" not in c
    assert (c["prest_documento"], c["numero"], c["ano"]) == ("12345678000199", "07", "2026")
    assert c["municipios"][0]["municipio"] == "Belo Horizonte"
    assert "id" not in c["municipios"][0] and "contrato_id" not in c["municipios"][0]


def test_npp_referencia_contrato_e_nota_por_chave_natural(bancos):
    ref = _semear(bancos)
    env = backup.exportar_npp(bancos, ref["npp"].id)
    npp = env["dados"]["npps"][0]
    nota = env["dados"]["notas"][0]
    # NPP → contrato por (doc, num, ano); nunca por id
    assert npp["contrato_ref"] == ["12345678000199", "07", "2026"]
    assert "contrato_id" not in npp and "id" not in npp
    assert npp["numero"] == ref["npp"].numero
    # nota → NPP por numero; nunca por npp_id
    assert nota["npp_ref"] == ref["npp"].numero
    assert "npp_id" not in nota
    # contrato EMBUTIDO na NPP (decisão do humano)
    assert len(env["dados"]["contratos"]) == 1


# ---------- I-2: dados da nota transcritos fielmente ----------

def test_dados_da_nota_preservados(bancos):
    ref = _semear(bancos)
    env = backup.exportar_npp(bancos, ref["npp"].id)
    assert env["dados"]["notas"][0]["dados"] == ref["dados_nota"]


# ---------- I-1 / I-4: ledger e autoria preservados ----------

def test_npp_carrega_ledger_e_autoria_original(bancos):
    ref = _semear(bancos)
    env = backup.exportar_npp(bancos, ref["npp"].id)
    led = env["dados"]["exportacoes"]
    assert len(led) == 1 and led[0]["chave"] == ref["chave"]
    assert led[0]["lote_id"] == "lote-2026-05-A"
    marc = env["dados"]["marcacoes"][0]
    assert marc["autor"] == "Fulano (MNM)" and marc["valor"] == "sim"
    assert marc["valor_material"] == "100.00" and marc["marcado_em"]
    val = env["dados"]["validacoes"][0]
    assert val["autor"] == "Fulano (MNM)" and val["tributo"] == "ISS"
    assert val["acao"] == "confirmado" and val["validado_em"]


# ---------- recorte por escopo ----------

def test_pessoal_inclui_operador_completo_nao(bancos):
    _semear(bancos)
    completo = backup.exportar_completo(bancos)
    pessoal = backup.exportar_pessoal(bancos)
    assert "operador" not in completo["dados"]
    assert pessoal["dados"]["operador"]["iniciais"] == "MNM"


def test_gravar_snapshot_de_npp_usa_o_numero_no_nome(bancos, tmp_path):
    ref = _semear(bancos)
    env = backup.exportar_npp(bancos, ref["npp"].id)
    caminho = backup.gravar_snapshot(env, tmp_path / "saida")
    assert caminho.name == f"{ref['npp'].numero}.json"
    assert caminho.exists()
