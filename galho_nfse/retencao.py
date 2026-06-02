"""
Conferência de retenção da NFS-e contra a regra do contrato (galho NFS-e, Fase 2).

Compara o **destaque do emitente** lido da nota (I-2, transcrito como
`_destaque_emitente`) com a **regra que o especialista declarou no contrato**
(`tronco.contratos.Contrato`) e devolve, por tributo, um *achado* dizendo se
confere, diverge ou está indefinido.

O bloco **federal** (IR/CSLL/COFINS/PIS, IN 1234/2012) é comum aos dois galhos e vive
em `tronco.retencao_federal` — aqui só o adaptamos (campos da NFS-e/contrato) e
acrescentamos os tributos próprios do serviço: **INSS** (IN 2110/2022) e **ISS**
(LC 116/2003).

Fronteira de invariante (00_PRINCIPIOS) — leia antes de mexer:
- I-3: isto é **sugestão para conferência humana**, sempre acompanhada da regra que
  a gerou. **Nunca aplica** retenção nem grava decisão. Funções puras, sem efeito
  colateral. O `esperado` é rótulo "confira", não verdade apurada.
- I-2: só **lê** o registro; não toca a extração.
- I-4: usa como input a **marcação de material** já persistida (autor/data) — é o
  que o 00 prevê para a Fase 2. Não cria marcação nova.
- I-6: sem contrato ou material não conferido → estado **indefinido visível**, nunca chute.

O vínculo nota↔contrato é **explícito** via NPP (nota → NPP → contrato, escolhido pelo
operador) — a antiga heurística por CNPJ (`casar_contratos`) foi removida com a modelagem
por NPP. `conferir_retencao` recebe o contrato já resolvido; só confere, não escolhe.
"""
from __future__ import annotations

from decimal import Decimal

# ResultadoConferencia e rotulo_contrato são re-exportados do tronco (comuns aos 2 galhos).
from tronco.retencao_federal import (
    Achado, ResultadoConferencia, achados_federais, comparar, fmt, num, pct_txt,
    rotulo_contrato,
)


def conferir_retencao(reg, contrato, material_marcado=None) -> ResultadoConferencia:
    """Confere a NFS-e `reg` contra a regra do `contrato`. `material_marcado` é a
    marcação humana vigente ("sim"/"nao"/None) — input da Fase 2 (I-4)."""
    base = num(reg.valor_servicos)
    achados: list[Achado] = []

    # ---- Federal: IR + CSLL/COFINS/PIS (IN 1234/2012) — bloco comum (tronco) ----
    if contrato.ret_federal_sujeito:
        achados.extend(achados_federais(
            base=reg.valor_servicos,
            ir_pct=contrato.ret_federal_ir_pct,
            ir_codigo=contrato.ret_federal_codigo_receita,
            ir_destaque=reg.ir_destaque_emitente,
            material_previsto=contrato.material_previsao,
            material_marcado=material_marcado,
            csll_ativo=contrato.ret_federal_csll, csll_destaque=reg.csll_destaque_emitente,
            cofins_ativo=contrato.ret_federal_cofins, cofins_destaque=reg.cofins_destaque_emitente,
            pis_ativo=contrato.ret_federal_pis, pis_destaque=reg.pis_destaque_emitente,
        ))

    # ---- INSS (IN 2110/2022) ----
    if contrato.inss_cessao_mao_obra:
        achados.append(_achado_inss(reg, contrato, base))

    # ---- ISS (LC 116/2003) ----
    if contrato.iss_retido_tomador:
        achados.append(_achado_iss(reg, contrato, base))

    return ResultadoConferencia(rotulo_contrato(contrato), achados)


# --------------------------- achados próprios do serviço ---------------------------

def _achado_inss(reg, contrato, base) -> Achado:
    aliq = num(contrato.inss_aliquota)
    adic = num(contrato.inss_adicional_pct) or Decimal(0)
    destaque = num(reg.inss_destaque_emitente)
    base_calc, obs = base, ""
    # Material previsto SEM discriminação → base mínima (IN 2110/2022, art. 118).
    base_min = num(contrato.inss_base_minima_pct)
    if contrato.material_previsao == "sim_sem_discriminacao" and base_min and base is not None:
        base_calc = base * base_min / 100
        obs = f"base mín. {pct_txt(base_min)}"
    regra = f"INSS {pct_txt(aliq)}" + (f" +{pct_txt(adic)}" if adic else "") + (f", {obs}" if obs else "")
    if aliq is None or base_calc is None:
        return Achado("INSS", regra, fmt(destaque), None, "indefinido",
                      "Defina a alíquota de INSS no contrato.")
    esperado = base_calc * (aliq + adic) / 100
    return Achado("INSS", regra, fmt(destaque), fmt(esperado), comparar(esperado, destaque))


def _achado_iss(reg, contrato, base) -> Achado:
    aliq = num(contrato.iss_aliquota)
    destaque = num(reg.iss_valor_destaque_emitente)
    sub = contrato.iss_subitem_lista
    regra = f"ISS retido {pct_txt(aliq)}" + (f", subitem {sub}" if sub else "")
    if aliq is None or base is None:
        return Achado("ISS", regra, fmt(destaque), None, "indefinido",
                      "Defina a alíquota de ISS (2%–5%) no contrato.")
    esperado = base * aliq / 100
    return Achado("ISS", regra, fmt(destaque), fmt(esperado), comparar(esperado, destaque))
