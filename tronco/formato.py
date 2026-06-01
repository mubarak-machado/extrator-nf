"""
Formatação humana de valores para exibição (pt-BR).

Tudo aqui é só apresentação — não altera o dado extraído. É tolerante a entrada
ruim (I-6): se não consegue formatar, devolve algo legível em vez de quebrar.
Registrado como filtros Jinja em app.py.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

TRACO = "—"


def _digitos(s) -> str:
    return "".join(c for c in str(s) if c.isdigit()) if s is not None else ""


def moeda(valor) -> str:
    """'5000.00' -> 'R$ 5.000,00'. None/invalez -> traço/valor cru."""
    if valor is None or valor == "":
        return TRACO
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return str(valor)
    inteiro, _, dec = f"{d:.2f}".partition(".")
    neg = inteiro.startswith("-")
    inteiro = inteiro.lstrip("-")
    blocos = []
    while len(inteiro) > 3:
        blocos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    blocos.insert(0, inteiro)
    return ("-" if neg else "") + "R$ " + ".".join(blocos) + "," + dec


def numero(valor) -> str:
    """Como moeda, mas sem o prefixo R$ (para somatórios neutros)."""
    m = moeda(valor)
    return m.replace("R$ ", "") if m != TRACO else TRACO


def ezero(valor) -> bool:
    """True se o valor é zero, vazio ou ausente — para *atenuar* (não esconder)
    a exibição. Continua sendo renderizado; só recebe menos ênfase visual, de
    modo que os valores reais saltem (contraste relevante). Não altera o dado.
    Registrado como *teste* Jinja em app.py: usar `{{ x is ezero }}`."""
    if valor is None or valor == "":
        return True
    try:
        return Decimal(str(valor)) == 0
    except (InvalidOperation, ValueError):
        return False


def data(iso) -> str:
    """'2026-05-12T10:14:00-03:00' -> '12/05/2026'."""
    if not iso:
        return TRACO
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def datahora(iso) -> str:
    """'2026-05-12T10:14:00-03:00' -> '12/05/2026 10:14'."""
    if not iso:
        return TRACO
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(iso)


def competencia(iso) -> str:
    """'2026-05-01' -> '05/2026' (mês/ano de competência)."""
    if not iso:
        return TRACO
    try:
        return datetime.fromisoformat(str(iso)).strftime("%m/%Y")
    except ValueError:
        return str(iso)


def cnpj(valor) -> str:
    """14 dígitos -> '11.222.333/0001-81'. Fora disso, devolve o que veio."""
    d = _digitos(valor)
    if len(d) != 14:
        return str(valor) if valor else TRACO
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def percent(valor) -> str:
    """'5.00' -> '5,00%'."""
    if valor is None or valor == "":
        return TRACO
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return str(valor)
    return f"{d:.2f}".replace(".", ",") + "%"


def chave(valor) -> str:
    """Agrupa a chave de acesso em blocos de 4 para leitura."""
    d = _digitos(valor)
    if not d:
        return TRACO
    return " ".join(d[i:i + 4] for i in range(0, len(d), 4))


def simnao(valor) -> str:
    if valor is True:
        return "Sim"
    if valor is False:
        return "Não"
    return TRACO


# Dispatcher usado na EXPORTAÇÃO (CSV). Reusa as funções acima — formatar é
# apresentação, não interpretação (I-2). "texto" passa o valor cru; "faltantes"
# junta a lista de campos a conferir (I-6); "cru" é para a chave (identificador
# de busca/colagem — sem agrupar em blocos como na tela).
def formatar(valor, fmt: str) -> str:
    if fmt == "texto":
        return str(valor) if valor not in (None, "") else TRACO
    if fmt == "faltantes":
        return "; ".join(valor) if valor else TRACO
    if fmt == "cru":
        return str(valor) if valor not in (None, "") else ""
    fn = {"moeda": moeda, "data": data, "datahora": datahora,
          "competencia": competencia, "cnpj": cnpj, "percent": percent,
          "simnao": simnao}.get(fmt)
    if fn is None:
        raise ValueError(f"formato de exportação desconhecido: {fmt!r}")
    return fn(valor)
