"""
Conferência de retenção da NF-e mercantil contra a regra do contrato (galho NF-e, Fase 2).

A NF-e tem **só o bloco federal** (IR/CSLL/COFINS/PIS, IN 1234/2012), e mesmo esse só
quando o fornecedor **não é optante do Simples** (optante → dispensa, LC 123/2006). INSS
e ISS **não se aplicam** à venda mercantil. O cálculo federal é o comum do tronco
(`tronco.retencao_federal`) — este galho só o adapta aos campos da NF-e e aplica o
gatilho do Simples. Depende apenas do tronco, nunca do galho NFS-e (galhos independentes).

⚠️ A NF-e **não destaca** a retenção que o órgão fará: os campos
`pis_destaque_emitente`/`cofins_destaque_emitente` do `RegistroNFe` são os tributos
**próprios do vendedor** na operação, **não** a retenção — por isso o destaque da retenção
entra como `None` (o operador insere/valida depois, Fase 2). Não mapear um no outro (I-2).

Fronteira de invariante (00_PRINCIPIOS) — igual ao galho NFS-e:
- I-2: só **lê** o registro; não toca a extração.
- I-3: devolve **sugestão** (`esperado`); nunca grava, nunca decide.
- I-6: regime do fornecedor desconhecido (CRT ausente) → `indefinido` visível, nunca chute.
"""
from __future__ import annotations

from tronco.retencao_federal import (
    Achado, ResultadoConferencia, achados_federais, rotulo_contrato,
)

_FEDERAIS = ("IR", "CSLL", "COFINS", "PIS")


def conferir_retencao(reg, contrato, material_marcado=None) -> ResultadoConferencia:
    """Confere a NF-e `reg` contra a regra do `contrato`. `material_marcado` é aceito por
    paridade de assinatura com a NFS-e, mas a NF-e não tem o caso de material aplicado."""
    optante = reg.emit_optante_simples
    if optante is True:
        achados = [_dispensado_simples(t) for t in _FEDERAIS]
    elif optante is None:
        achados = [_indefinido_regime(t) for t in _FEDERAIS]
    elif contrato.ret_federal_sujeito:
        # Não optante e contrato sujeito ao federal: aplica IN 1234/2012 (sugestão).
        # Destaques da retenção = None (a NF-e não os traz; o operador valida depois).
        achados = list(achados_federais(
            base=reg.valor_total,
            ir_pct=contrato.ret_federal_ir_pct,
            ir_codigo=contrato.ret_federal_codigo_receita,
            ir_destaque=None,
            csll_ativo=contrato.ret_federal_csll, csll_destaque=None,
            cofins_ativo=contrato.ret_federal_cofins, cofins_destaque=None,
            pis_ativo=contrato.ret_federal_pis, pis_destaque=None,
        ))
    else:
        # Contrato declara que não há retenção federal — nada a conferir.
        achados = []
    return ResultadoConferencia(rotulo_contrato(contrato), achados)


def _dispensado_simples(tributo) -> Achado:
    return Achado(tributo, "Optante do Simples — retenção dispensada (LC 123/2006)",
                  None, "0.00", "confere",
                  "Fornecedor optante do Simples: o órgão não retém o federal.")


def _indefinido_regime(tributo) -> Achado:
    return Achado(tributo, "Regime do fornecedor indefinido", None, None, "indefinido",
                  "CRT ausente na nota: confirme se o fornecedor é optante do Simples.")
