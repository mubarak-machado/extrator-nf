"""
Bloco federal da conferência de retenção — IN RFB 1234/2012 (tronco comum).

Mora no tronco porque a regra federal (IR/CSLL/COFINS/PIS) é a MESMA para os dois
galhos: NFS-e de serviço e NF-e mercantil (esta quando o fornecedor não é optante do
Simples). Cada galho adapta seu próprio registro/contrato e chama `achados_federais`
com entradas normalizadas — o módulo não conhece nenhum dos galhos, então não cria
dependência galho↔galho (preserva "dois galhos independentes", docs/01).

Fronteira de invariante (docs/00) — igual à do galho:
- I-2: só LÊ valores; não toca a extração. O destaque do emitente entra como dado.
- I-3: devolve SUGESTÃO (`esperado`) para conferência humana; nunca grava, nunca decide.
- I-6: sem percentual/base, ou material previsto e não conferido → estado `indefinido`
  visível, nunca chute.

Aqui também vivem o tipo de resultado por tributo (`Achado`) e os utilitários de
comparação/formatação compartilhados pelos dois galhos (INSS/ISS, no galho NFS-e, reusam).
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
    regra: str                         # regra declarada (texto curto)
    destaque_emitente: str | None      # valor lido da nota (decimal canônico) ou None
    esperado: str | None               # valor sugerido pela regra — SUGESTÃO, não decisão
    situacao: str                      # "confere" | "diverge" | "indefinido"
    nota: str = ""                     # observação curta (ex.: "marque o material")
    codigo: str | None = None          # código de receita (federal); agrega a exibição


@dataclass
class ResultadoConferencia:
    """Resultado por contrato — comum aos dois galhos (mesmo formato de tela)."""
    contrato_rotulo: str               # ex. "02/2026"
    achados: list[Achado] = field(default_factory=list)


def rotulo_contrato(c) -> str:
    """Rótulo curto do contrato (entidade do tronco) — usado pelos dois galhos e pela UI."""
    num_ = c.numero or "—"
    return f"{num_}/{c.ano}" if c.ano else num_


def achados_federais(*, base, ir_pct, ir_codigo, ir_destaque,
                     material_previsto="nao", material_marcado=None,
                     csll_ativo, csll_destaque,
                     cofins_ativo, cofins_destaque,
                     pis_ativo, pis_destaque) -> list[Achado]:
    """Bloco federal IN 1234/2012: IR + CSLL/COFINS/PIS. Recebe valores crus de cada
    galho (normaliza aqui); só sugestão (I-3). `material_previsto`/`material_marcado` só
    importam à NFS-e (gating do IR pela presença de material aplicado) — a NF-e omite
    (default 'nao'/None = sem gating)."""
    b = num(base)
    achados = [_achado_ir(b, ir_pct, ir_codigo, ir_destaque, material_previsto, material_marcado)]
    contribs = (
        (_CONTRIB[0][0], _CONTRIB[0][1], csll_ativo, csll_destaque),
        (_CONTRIB[1][0], _CONTRIB[1][1], cofins_ativo, cofins_destaque),
        (_CONTRIB[2][0], _CONTRIB[2][1], pis_ativo, pis_destaque),
    )
    for nome, taxa, ativo, destaque in contribs:
        achados.append(_achado_contrib(nome, taxa, ativo, num(destaque), b))
    # Etiqueta cada linha federal com o código de receita já usado na conferência —
    # apenas para a exibição agregar por código (não muda nada da apuração; I-2/I-3).
    for a in achados:
        a.codigo = ir_codigo
    return achados


def _achado_ir(base, ir_pct, ir_codigo, ir_destaque, material_previsto, material_marcado) -> Achado:
    pct = num(ir_pct)
    destaque = num(ir_destaque)
    regra = f"IR {pct_txt(pct)}" + (f", cód. {ir_codigo}" if ir_codigo else "")
    # A alíquota de IR depende de ter havido material; se previsto e ainda não conferido,
    # não dá para conferir o IR (I-6). (Só a NFS-e usa isto; a NF-e passa 'nao'.)
    if material_previsto != "nao" and material_marcado is None:
        return Achado("IR", regra, fmt(destaque), None, "indefinido",
                      "Marque o material para conferir o IR (a alíquota depende dele).")
    if pct is None or base is None:
        return Achado("IR", regra, fmt(destaque), None, "indefinido",
                      "Defina o percentual de IR no contrato e o valor dos serviços.")
    esperado = base * pct / 100
    return Achado("IR", regra, fmt(destaque), fmt(esperado), comparar(esperado, destaque))


def _achado_contrib(nome, taxa, ativo, destaque, base) -> Achado:
    if ativo:
        regra = f"{nome} incide ({pct_txt(taxa)})"
        if base is None:
            return Achado(nome, regra, fmt(destaque), None, "indefinido",
                          "Confira o valor dos serviços.")
        esperado = base * taxa / 100
        return Achado(nome, regra, fmt(destaque), fmt(esperado), comparar(esperado, destaque))
    # Não deve incidir: confere se a nota não destacou (ou destacou zero).
    regra = f"{nome} não incide"
    situacao = "confere" if (destaque is None or destaque == 0) else "diverge"
    return Achado(nome, regra, fmt(destaque), fmt(Decimal(0)), situacao)


# ------------------------- utilidades compartilhadas (tronco) -------------------------

def num(v):
    """Valor (string humana ou canônica) -> Decimal, ou None. Reusa parse_valor (I-6)."""
    canon = formato.parse_valor(v)
    if canon is None:
        return None
    try:
        return Decimal(canon)
    except InvalidOperation:
        return None


def comparar(esperado, destaque) -> str:
    if esperado is None:
        return "indefinido"
    if destaque is None:
        return "confere" if esperado == 0 else "diverge"
    return "confere" if abs(esperado - destaque) <= TOLERANCIA else "diverge"


def fmt(v) -> str | None:
    return f"{v:.2f}" if v is not None else None


def pct_txt(v) -> str:
    if v is None:
        return "—"
    return (f"{v:.2f}".rstrip("0").rstrip(".")).replace(".", ",") + "%"
