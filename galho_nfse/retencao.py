"""
Conferência de retenção da NFS-e contra a regra do contrato (galho NFS-e, Fase 2).

Compara o **destaque do emitente** lido da nota (I-2, transcrito como
`_destaque_emitente`) com a **regra que o especialista declarou no contrato**
(`tronco.contratos.Contrato`) e devolve, por tributo, um *achado* dizendo se
confere, diverge ou está indefinido.

Fronteira de invariante (00_PRINCIPIOS) — leia antes de mexer:
- I-3: isto é **sugestão para conferência humana**, sempre acompanhada da regra que
  a gerou. **Nunca aplica** retenção nem grava decisão. Funções puras, sem efeito
  colateral. O `esperado` é rótulo "confira", não verdade apurada.
- I-2: só **lê** o registro; não toca a extração.
- I-4: usa como input a **marcação de material** já persistida (autor/data) — é o
  que o 00 prevê para a Fase 2. Não cria marcação nova.
- I-6: sem contrato, contrato ambíguo (vários p/ o mesmo prestador) ou material não
  conferido → estado **indefinido visível**, nunca chute.

O vínculo nota↔contrato é a heurística por CNPJ (decisão #2 segue aberta):
`casar_contratos` devolve TODAS as correspondências; quem chama trata 0/1/vários.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from tronco import formato

# Tolerância da comparação (centavos de arredondamento não são divergência).
TOLERANCIA = Decimal("0.02")

# Alíquotas fixas das contribuições federais (IN 1234/2012).
_CONTRIB = (("CSLL", Decimal("1")), ("COFINS", Decimal("3")), ("PIS", Decimal("0.65")))


@dataclass
class Achado:
    tributo: str                       # "IR" | "CSLL" | "COFINS" | "PIS" | "INSS" | "ISS"
    regra: str                         # regra declarada no contrato (texto curto)
    destaque_emitente: str | None      # valor lido da nota (decimal canônico) ou None
    esperado: str | None               # valor sugerido pela regra — SUGESTÃO, não decisão
    situacao: str                      # "confere" | "diverge" | "indefinido"
    nota: str = ""                     # observação curta (ex.: "marque o material")


@dataclass
class ResultadoConferencia:
    contrato_rotulo: str               # ex. "02/2026"
    achados: list[Achado] = field(default_factory=list)


def casar_contratos(reg, contratos):
    """Contratos cujo documento do prestador casa com o CNPJ da nota. Devolve todos
    (0, 1 ou vários); a escolha entre vários é do humano (I-6), não daqui."""
    doc = formato._digitos(reg.prest_cnpj)
    if not doc:
        return []
    return [c for c in contratos if formato._digitos(c.prest_documento) == doc]


def rotulo_contrato(c) -> str:
    num = c.numero or "—"
    return f"{num}/{c.ano}" if c.ano else num


def conferir_retencao(reg, contrato, material_marcado=None) -> ResultadoConferencia:
    """Confere a NFS-e `reg` contra a regra do `contrato`. `material_marcado` é a
    marcação humana vigente ("sim"/"nao"/None) — input da Fase 2 (I-4)."""
    base = _num(reg.valor_servicos)
    achados: list[Achado] = []

    # ---- Federal: IR (IN 1234/2012) ----
    if contrato.ret_federal_sujeito:
        achados.append(_achado_ir(reg, contrato, base, material_marcado))
        # CSLL / COFINS / PIS: incide? e o valor confere?
        destaques = {"CSLL": reg.csll_destaque_emitente, "COFINS": reg.cofins_destaque_emitente,
                     "PIS": reg.pis_destaque_emitente}
        ativos = {"CSLL": contrato.ret_federal_csll, "COFINS": contrato.ret_federal_cofins,
                  "PIS": contrato.ret_federal_pis}
        for nome, taxa in _CONTRIB:
            achados.append(_achado_contrib(nome, taxa, ativos[nome], _num(destaques[nome]), base))

    # ---- INSS (IN 2110/2022) ----
    if contrato.inss_cessao_mao_obra:
        achados.append(_achado_inss(reg, contrato, base))

    # ---- ISS (LC 116/2003) ----
    if contrato.iss_retido_tomador:
        achados.append(_achado_iss(reg, contrato, base))

    return ResultadoConferencia(rotulo_contrato(contrato), achados)


# --------------------------- achados por tributo ---------------------------

def _achado_ir(reg, contrato, base, material_marcado) -> Achado:
    pct = _num(contrato.ret_federal_ir_pct)
    destaque = _num(reg.ir_destaque_emitente)
    cod = contrato.ret_federal_codigo_receita
    regra = f"IR {_pct_txt(pct)}" + (f", cód. {cod}" if cod else "")
    # A alíquota de IR depende de ter havido material; se o contrato prevê material e
    # o operador ainda não conferiu, não dá para conferir o IR (I-6).
    if contrato.material_previsao != "nao" and material_marcado is None:
        return Achado("IR", regra, _fmt(destaque), None, "indefinido",
                      "Marque o material para conferir o IR (a alíquota depende dele).")
    if pct is None or base is None:
        return Achado("IR", regra, _fmt(destaque), None, "indefinido",
                      "Defina o percentual de IR no contrato e o valor dos serviços.")
    esperado = base * pct / 100
    return Achado("IR", regra, _fmt(destaque), _fmt(esperado), _comparar(esperado, destaque))


def _achado_contrib(nome, taxa, ativo, destaque, base) -> Achado:
    if ativo:
        regra = f"{nome} incide ({_pct_txt(taxa)})"
        if base is None:
            return Achado(nome, regra, _fmt(destaque), None, "indefinido",
                          "Confira o valor dos serviços.")
        esperado = base * taxa / 100
        return Achado(nome, regra, _fmt(destaque), _fmt(esperado), _comparar(esperado, destaque))
    # Não deve incidir: confere se a nota não destacou (ou destacou zero).
    regra = f"{nome} não incide"
    situacao = "confere" if (destaque is None or destaque == 0) else "diverge"
    return Achado(nome, regra, _fmt(destaque), _fmt(Decimal(0)), situacao)


def _achado_inss(reg, contrato, base) -> Achado:
    aliq = _num(contrato.inss_aliquota)
    adic = _num(contrato.inss_adicional_pct) or Decimal(0)
    destaque = _num(reg.inss_destaque_emitente)
    base_calc, obs = base, ""
    # Material previsto SEM discriminação → base mínima (IN 2110/2022, art. 118).
    base_min = _num(contrato.inss_base_minima_pct)
    if contrato.material_previsao == "sim_sem_discriminacao" and base_min and base is not None:
        base_calc = base * base_min / 100
        obs = f"base mín. {_pct_txt(base_min)}"
    regra = f"INSS {_pct_txt(aliq)}" + (f" +{_pct_txt(adic)}" if adic else "") + (f", {obs}" if obs else "")
    if aliq is None or base_calc is None:
        return Achado("INSS", regra, _fmt(destaque), None, "indefinido",
                      "Defina a alíquota de INSS no contrato.")
    esperado = base_calc * (aliq + adic) / 100
    return Achado("INSS", regra, _fmt(destaque), _fmt(esperado), _comparar(esperado, destaque))


def _achado_iss(reg, contrato, base) -> Achado:
    aliq = _num(contrato.iss_aliquota)
    destaque = _num(reg.iss_valor_destaque_emitente)
    sub = contrato.iss_subitem_lista
    regra = f"ISS retido {_pct_txt(aliq)}" + (f", subitem {sub}" if sub else "")
    if aliq is None or base is None:
        return Achado("ISS", regra, _fmt(destaque), None, "indefinido",
                      "Defina a alíquota de ISS (2%–5%) no contrato.")
    esperado = base * aliq / 100
    return Achado("ISS", regra, _fmt(destaque), _fmt(esperado), _comparar(esperado, destaque))


# ------------------------------- utilidades --------------------------------

def _num(v):
    """Valor (string humana ou canônica) -> Decimal, ou None. Reusa parse_valor (I-6)."""
    canon = formato.parse_valor(v)
    if canon is None:
        return None
    try:
        return Decimal(canon)
    except InvalidOperation:
        return None


def _comparar(esperado, destaque) -> str:
    if esperado is None:
        return "indefinido"
    if destaque is None:
        return "confere" if esperado == 0 else "diverge"
    return "confere" if abs(esperado - destaque) <= TOLERANCIA else "diverge"


def _fmt(v) -> str | None:
    return f"{v:.2f}" if v is not None else None


def _pct_txt(v) -> str:
    if v is None:
        return "—"
    return (f"{v:.2f}".rstrip("0").rstrip(".")).replace(".", ",") + "%"
