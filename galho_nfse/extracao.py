"""
Extração da NFS-e — Fase 1 (galho NFS-e).

Transcreve campos da NFS-e emitida (infNFSe + DPS embutida) para o RegistroNFSe.
FIEL (I-2): retenções federais e ISS vão como `_destaque_emitente`.

Caso especial — material aplicado:
- A `discriminacao` (xDescServ) é texto livre. Apenas a transcrevemos. NÃO
  procuramos palavra-chave, NÃO extraímos valor, NÃO decidimos alíquota. O aviso
  fixo e o controle de marcação ficam no modelo; a decisão é do humano (I-3/I-4).
"""
from __future__ import annotations

from .modelo import RegistroNFSe
from tronco.util import pega, so_digitos

_ESPERADOS = {
    "numero": "número da NFS-e",
    "data_emissao": "data de emissão",
    "prest_cnpj": "CNPJ do prestador",
    "toma_cnpj": "CNPJ do tomador",
    "discriminacao": "discriminação do serviço",
    "codigo_servico": "código do serviço (LC 116)",
    "valor_servicos": "valor dos serviços",
}


def extrair_nfse(inf_nfse) -> RegistroNFSe:
    """Recebe o objeto infNFSe (nfelib) e devolve o registro plano."""
    emit = getattr(inf_nfse, "emit", None)               # prestador (nota emitida)
    val_nfse = getattr(inf_nfse, "valores", None)        # valores apurados na emissão
    dps = pega(inf_nfse, "DPS", "infDPS")                # subtree estruturado
    dps_obj = getattr(getattr(inf_nfse, "DPS", None), "infDPS", None)

    prest = getattr(dps_obj, "prest", None)
    toma = getattr(dps_obj, "toma", None)
    serv = getattr(dps_obj, "serv", None)
    dps_val = getattr(dps_obj, "valores", None)

    op = pega(prest, "regTrib", "opSimpNac")             # 1=optante, 2=não
    optante = None if op is None else (str(op) == "1")

    reg = RegistroNFSe(
        chave=so_digitos(pega(inf_nfse, "Id")),
        numero=pega(inf_nfse, "nNFSe"),
        codigo_verificacao=pega(inf_nfse, "nDFSe"),
        data_emissao=pega(dps_obj, "dhEmi") or pega(inf_nfse, "dhProc"),
        competencia=pega(dps_obj, "dCompet"),
        municipio_nome=pega(inf_nfse, "xLocPrestacao") or pega(inf_nfse, "xLocEmi"),
        # Prestador
        prest_cnpj=pega(prest, "CNPJ") or pega(emit, "CNPJ"),
        prest_nome=pega(emit, "xNome"),
        prest_im=pega(prest, "IM") or pega(emit, "IM"),
        prest_optante_simples=optante,
        prest_municipio=pega(inf_nfse, "xLocEmi"),
        # Tomador (o órgão)
        toma_cnpj=pega(toma, "CNPJ"),
        toma_nome=pega(toma, "xNome"),
        # Serviço (transcrito, não interpretado)
        discriminacao=pega(serv, "cServ", "xDescServ"),
        codigo_servico=pega(serv, "cServ", "cTribNac"),
        local_prestacao=pega(serv, "locPrest", "cLocPrestacao"),
        local_prestador=pega(dps_obj, "cLocEmi"),
        # Valores e retenções COMO DESTACADAS
        valor_servicos=pega(dps_val, "vServPrest", "vServ"),
        deducoes=pega(dps_val, "vDedRed", "vDR"),
        base_calculo=pega(val_nfse, "vBC"),
        iss_aliquota_destaque_emitente=pega(val_nfse, "pAliqAplic"),
        iss_valor_destaque_emitente=pega(val_nfse, "vISSQN"),
        iss_retido_destaque_emitente=pega(dps_val, "trib", "tribMun", "tpRetISSQN"),
        ir_destaque_emitente=pega(dps_val, "trib", "tribFed", "vRetIRRF"),
        pis_destaque_emitente=pega(dps_val, "trib", "tribFed", "piscofins", "vPis"),
        cofins_destaque_emitente=pega(dps_val, "trib", "tribFed", "piscofins", "vCofins"),
        csll_destaque_emitente=pega(dps_val, "trib", "tribFed", "vRetCSLL"),
        inss_destaque_emitente=pega(dps_val, "trib", "tribFed", "vRetCP"),
        valor_liquido=pega(val_nfse, "vLiq"),
    )

    d = reg.to_dict()
    reg.campos_faltantes = [
        rotulo for campo, rotulo in _ESPERADOS.items() if not d.get(campo)
    ]
    return reg
