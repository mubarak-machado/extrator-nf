"""
Extração da NF-e — Fase 1 (galho NF-e).

Transcreve campos de cabeçalho do binding nfelib para o RegistroNFe. É FIEL
(I-2): não calcula, não interpreta, não decide retenção. Tributos vão para
campos rotulados `_destaque_emitente`.

I-6: campos esperados ausentes não quebram a extração nem são chutados — entram
em `campos_faltantes`, que a tela mostra como "confira".
"""
from __future__ import annotations

from .modelo import RegistroNFe
from tronco.util import pega, so_digitos

# Campos cuja ausência queremos sinalizar (não exaustivo; foca no que importa
# para lançamento de pagamento).
_ESPERADOS = {
    "numero": "número da nota",
    "data_emissao": "data de emissão",
    "emit_cnpj": "CNPJ do emitente",
    "emit_nome": "nome do emitente",
    "dest_cnpj": "CNPJ do destinatário",
    "valor_total": "valor total da nota",
}


def extrair_nfe(inf_nfe) -> RegistroNFe:
    """Recebe o objeto infNFe (nfelib) e devolve o registro plano."""
    ide = getattr(inf_nfe, "ide", None)
    emit = getattr(inf_nfe, "emit", None)
    dest = getattr(inf_nfe, "dest", None)
    tot = pega(inf_nfe, "total", "ICMSTot")  # objeto ICMSTot (ou None)
    # `pega` no total devolve o objeto desembrulhado; reacessamos via getattr:
    icmstot = getattr(getattr(inf_nfe, "total", None), "ICMSTot", None)

    crt = pega(emit, "CRT")  # já desembrulhado (string "1".."4") ou None
    optante = None if crt is None else (str(crt) == "1")

    reg = RegistroNFe(
        chave=so_digitos(pega(inf_nfe, "Id")),
        numero=pega(ide, "nNF"),
        serie=pega(ide, "serie"),
        modelo=pega(ide, "mod"),
        data_emissao=pega(ide, "dhEmi"),
        natureza_operacao=pega(ide, "natOp"),
        emit_cnpj=pega(emit, "CNPJ"),
        emit_nome=pega(emit, "xNome"),
        emit_optante_simples=optante,
        emit_crt=crt,
        emit_uf=pega(emit, "enderEmit", "UF"),
        emit_municipio=pega(emit, "enderEmit", "xMun"),
        dest_cnpj=pega(dest, "CNPJ"),
        dest_nome=pega(dest, "xNome"),
        valor_total=pega(icmstot, "vNF"),
        valor_produtos=pega(icmstot, "vProd"),
        valor_desconto=pega(icmstot, "vDesc"),
        valor_outras_despesas=pega(icmstot, "vOutro"),
        icms_destaque_emitente=pega(icmstot, "vICMS"),
        ipi_destaque_emitente=pega(icmstot, "vIPI"),
        pis_destaque_emitente=pega(icmstot, "vPIS"),
        cofins_destaque_emitente=pega(icmstot, "vCOFINS"),
        trib_aprox_destaque_emitente=pega(icmstot, "vTotTrib"),
    )

    d = reg.to_dict()
    reg.campos_faltantes = [
        rotulo for campo, rotulo in _ESPERADOS.items() if not d.get(campo)
    ]
    return reg
