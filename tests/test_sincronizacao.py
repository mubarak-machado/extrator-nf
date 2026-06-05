"""
Testes de sincronização (importação de snapshot) — organizados pelos invariantes.

Round-trip completo (export numa máquina A, import numa máquina B vazia → estado igual),
união do ledger (I-1), preservação de autoria (I-4), conflito visível e barramento por
hash/schema (I-6), e a regra de FK por chave natural.
"""
from __future__ import annotations

import pytest

from tronco import backup, sincronizacao
from tronco.backup import Bancos
from tronco.contratos import Contrato, MunicipioIss
from galho_nfse.enquadramento import RegraEnquadramento
from galho_nfse.inss import RegraInss


def _semear(b: Bancos) -> dict:
    b.operador.salvar("MNM", "Fulano de Tal")
    cid = b.contratos.salvar(Contrato(
        prest_documento="12345678000199", numero="07", ano="2026",
        prest_identificacao="Prestadora LTDA",
        municipios=[MunicipioIss(municipio="Belo Horizonte", uf="MG",
                                 iss_aliquota="5", iss_retido=True, iss_recolhimento="dar")]))
    b.federais.salvar(RegraEnquadramento(codigo="TF-001", descricao="Geral",
                                         fundamento="IN 1234/2012", sujeito=True, ir_pct="4.8"))
    b.inss.salvar(RegraInss(codigo="INSS-001", descricao="Cessão",
                            fundamento="IN 2110/2022", cessao_mao_obra=True, aliquota="11"))
    npp = b.npps.criar(contrato_id=cid, competencia="2026-05", iniciais="MNM",
                       autor="Fulano (MNM)")
    chave = "31260512345678000199550010000000011000000017"
    b.notas.salvar(chave, "NFSE", {"chave": chave, "valor_total": "1000.00"},
                   origem="nota.xml", npp_id=npp.id)
    b.marcacoes.marcar(chave, "sim", "Fulano (MNM)", valor_material="100.00")
    b.validacoes.validar(chave, "ISS", "confirmado", "50.00", "Fulano (MNM)")
    b.exportacoes.registrar_lote([(chave, "NFSE")], "lote-A")
    return {"cid": cid, "npp": npp, "chave": chave}


@pytest.fixture
def origem(tmp_path):
    b = Bancos.abrir(tmp_path / "A")
    ref = _semear(b)
    yield b, ref
    b.fechar()


@pytest.fixture
def destino(tmp_path):
    b = Bancos.abrir(tmp_path / "B")
    yield b
    b.fechar()


# ---------- round-trip: A -> B vazio reconstrói o estado por chave natural ----------

def test_round_trip_npp_reconstroi_em_maquina_vazia(origem, destino):
    a, ref = origem
    snap = backup.exportar_npp(a, ref["npp"].id)
    plano = sincronizacao.planejar_importacao(snap, destino)
    assert plano.valido and plano.resumo()["conflito"] == 0
    resumo = sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    assert resumo.aplicados > 0 and resumo.conflitos_pendentes == 0
    # contrato embutido recriado e a NPP religada a ELE por chave natural (rowid novo, local)
    npp_b = destino.npps.obter_por_numero(ref["npp"].numero)
    assert npp_b is not None
    contrato_b = destino.contratos.obter(npp_b.contrato_id)
    assert (contrato_b.prest_documento, contrato_b.numero, contrato_b.ano) == \
        ("12345678000199", "07", "2026")
    # nota religada à NPP local (npp_id é rowid de B, não o de A)
    notas_b = destino.notas.listar_por_npp(npp_b.id)
    assert len(notas_b) == 1 and notas_b[0]["chave"] == ref["chave"]
    assert notas_b[0]["dados"] == {"chave": ref["chave"], "valor_total": "1000.00"}


# ---------- I-1: ledger viaja junto e se une append-only ----------

def test_ledger_unido_marca_nota_como_ja_exportada(origem, destino):
    a, ref = origem
    snap = backup.exportar_npp(a, ref["npp"].id)
    assert destino.exportacoes.ja_exportada(ref["chave"]) is False
    sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    # após importar, a nota já consta como exportada em B — trava de duplicidade (I-1)
    assert destino.exportacoes.ja_exportada(ref["chave"]) is True
    led = destino.exportacoes.listar()
    assert led[0]["lote_id"] == "lote-A"          # lote_id original preservado


def test_reimportar_e_idempotente(origem, destino):
    a, ref = origem
    snap = backup.exportar_npp(a, ref["npp"].id)
    sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    r2 = sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    # segunda passada: tudo idêntico, nada aplicado de novo
    assert r2.aplicados == 0
    assert len(destino.npps.listar()) == 1
    assert len(destino.notas.listar()) == 1
    assert len(destino.marcacoes.historico()) == 1
    assert len(destino.validacoes.historico()) == 1


def test_config_com_listas_reimporta_sem_falso_conflito(origem, destino):
    # Regra com naturezas/categorias preenchidas: tupla no objeto (asdict), lista após o
    # round-trip JSON. Reimportar não pode acusar conflito só por tupla×lista.
    a, ref = origem
    a.federais.salvar(RegraEnquadramento(
        codigo="TF-009", descricao="Específica", fundamento="IN 1234/2012",
        naturezas=("nao_optante",), categorias=("geral", "vigilancia"),
        sujeito=True, ir_pct="4.8"))
    snap = backup.exportar_configuracao(a)
    sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)   # 1ª: cria tudo
    plano = sincronizacao.planejar_importacao(snap, destino)               # 2ª: tudo idêntico
    assert plano.resumo()["conflito"] == 0
    assert plano.resumo()["novo"] == 0


# ---------- I-4: autoria e timestamps originais preservados ----------

def test_marcacao_e_validacao_preservam_autor_e_data(origem, destino):
    a, ref = origem
    snap = backup.exportar_npp(a, ref["npp"].id)
    marc_orig = a.marcacoes.atual(ref["chave"])
    val_orig = a.validacoes.atual(ref["chave"], "ISS")
    sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    marc_b = destino.marcacoes.atual(ref["chave"])
    val_b = destino.validacoes.atual(ref["chave"], "ISS")
    assert marc_b["autor"] == "Fulano (MNM)" and marc_b["marcado_em"] == marc_orig["marcado_em"]
    assert val_b["autor"] == "Fulano (MNM)" and val_b["validado_em"] == val_orig["validado_em"]


# ---------- I-6: conflito visível, nunca sobrescreve sozinho ----------

def test_contrato_divergente_vira_conflito_e_nao_sobrescreve(origem, destino):
    a, ref = origem
    # B já tem o MESMO contrato (mesma chave natural) com conteúdo diferente
    destino.contratos.salvar(Contrato(prest_documento="12345678000199", numero="07",
                                      ano="2026", prest_identificacao="OUTRO NOME"))
    snap = backup.exportar_configuracao(a)
    plano = sincronizacao.planejar_importacao(snap, destino)
    conflitos = plano.conflitos
    assert any(i.entidade == "contratos" for i in conflitos)
    # sem resolução, aplicar NÃO sobrescreve o local (I-6)
    sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    local = destino.contratos.obter_por_chave_natural("12345678000199", "07", "2026")
    assert local.prest_identificacao == "OUTRO NOME"


def test_conflito_resolvido_usar_snapshot_sobrescreve(origem, destino):
    a, ref = origem
    destino.contratos.salvar(Contrato(prest_documento="12345678000199", numero="07",
                                      ano="2026", prest_identificacao="OUTRO NOME"))
    snap = backup.exportar_configuracao(a)
    plano = sincronizacao.planejar_importacao(snap, destino)
    conflito = next(i for i in plano.conflitos if i.entidade == "contratos")
    sincronizacao.aplicar_importacao(snap, destino, {conflito.id: "usar_snapshot"},
                                     backup_previo=False)
    local = destino.contratos.obter_por_chave_natural("12345678000199", "07", "2026")
    assert local.prest_identificacao == "Prestadora LTDA"


def test_hash_corrompido_barra_importacao(origem, destino):
    a, ref = origem
    snap = backup.exportar_configuracao(a)
    snap["dados"]["contratos"][0]["numero"] = "ADULTERADO"   # hash não bate mais
    plano = sincronizacao.planejar_importacao(snap, destino)
    assert plano.valido is False and "Hash" in plano.erro
    resumo = sincronizacao.aplicar_importacao(snap, destino, backup_previo=False)
    assert resumo.aplicados == 0 and destino.contratos.listar() == []


def test_schema_desconhecido_barra(destino):
    plano = sincronizacao.planejar_importacao(
        {"formato": "extrator-nf/snapshot", "schema_versao": 999, "dados": {}}, destino)
    assert plano.valido is False and "schema" in plano.erro.lower()


# ---------- vínculo órfão: NPP sem contrato local nem embutido ----------

def test_npp_sem_contrato_e_conflito_visivel(origem, destino):
    a, ref = origem
    snap = backup.exportar_npp(a, ref["npp"].id)
    snap["dados"]["contratos"] = []          # tira o contrato embutido
    snap["hash_conteudo"] = backup.hash_conteudo(snap["dados"])  # re-hash p/ passar do envelope
    plano = sincronizacao.planejar_importacao(snap, destino)
    npp_item = next(i for i in plano.itens if i.entidade == "npps")
    assert npp_item.situacao == "conflito" and "ausente" in npp_item.motivo
