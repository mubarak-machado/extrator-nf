"""
Tabela de retenção da IN RFB 1234/2012 — códigos de receita agregados (federal).

Transcrição da tabela **fornecida pelo especialista** (CSV de códigos de retenção de
órgão público federal). O sistema **estrutura** o que foi ditado, não inventa (I-3); os
percentuais não saem daqui por adivinhação — vieram da fonte. Ao escolher um código
agregado na tela de Regras, o operador preenche de uma vez IR/CSLL/COFINS/PIS conforme
esta tabela (autopreenchimento é conveniência; quem ratifica é o humano).

Cada entrada: percentuais por tributo (string decimal) e o total agregado. Nesta tabela,
CSLL é sempre 1,0%; COFINS ∈ {3,0%; 0}; PIS ∈ {0,65%; 0}; o IR é o que varia — por isso o
catálogo modela IR como percentual e as contribuições como incidência (taxa fixa em lei).
"""
from __future__ import annotations

# codigo_receita -> {total, ir, csll, cofins, pis} (percentuais, string decimal)
CODIGOS: dict[str, dict[str, str]] = {
    "6147": {"total": "5.85", "ir": "1.2",  "csll": "1.0", "cofins": "3.0", "pis": "0.65"},
    "9060": {"total": "4.89", "ir": "0.24", "csll": "1.0", "cofins": "3.0", "pis": "0.65"},
    "8739": {"total": "1.24", "ir": "0.24", "csll": "1.0", "cofins": "0.0", "pis": "0.0"},
    "8767": {"total": "2.2",  "ir": "1.2",  "csll": "1.0", "cofins": "0.0", "pis": "0.0"},
    "6175": {"total": "7.05", "ir": "2.4",  "csll": "1.0", "cofins": "3.0", "pis": "0.65"},
    "8850": {"total": "3.4",  "ir": "2.4",  "csll": "1.0", "cofins": "0.0", "pis": "0.0"},
    "8863": {"total": "4.65", "ir": "0.0",  "csll": "1.0", "cofins": "3.0", "pis": "0.65"},
    "6188": {"total": "7.05", "ir": "2.4",  "csll": "1.0", "cofins": "3.0", "pis": "0.65"},
    "6190": {"total": "9.45", "ir": "4.8",  "csll": "1.0", "cofins": "3.0", "pis": "0.65"},
}

# Valores de IR distintos da tabela — alimentam a lista (datalist) do campo de IR, junto
# das alíquotas "clássicas" do Anexo I; o operador ainda pode digitar outro valor.
IR_VALORES = sorted({c["ir"] for c in CODIGOS.values()} | {"1.5", "5.85", "7.05", "9.45"},
                    key=lambda v: float(v))


def opcoes_agregadas() -> list[dict]:
    """Lista para o seletor de alíquota agregada (código + total + quebra), ordenada
    pelo total. Cada item traz os percentuais para o autopreenchimento no formulário."""
    itens = [{"codigo": cod, **v} for cod, v in CODIGOS.items()]
    itens.sort(key=lambda x: float(x["total"]))
    return itens
