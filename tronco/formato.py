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


def parse_valor(texto) -> str | None:
    """Lê um valor monetário digitado por humano e devolve string decimal
    canônica ('1.200,00' ou 'R$ 1.200,00' ou '1200.00' -> '1200.00'). Entrada
    vazia/inválida -> None (não chuta — I-6). Inverso prático de `moeda`."""
    if texto is None:
        return None
    s = "".join(c for c in str(texto) if c.isdigit() or c in ".,-").strip()
    if not s or s in ("-", ".", ","):
        return None
    if "," in s:                       # vírgula é o decimal; ponto é milhar
        s = s.replace(".", "").replace(",", ".")
    try:
        return f"{Decimal(s):.2f}"
    except (InvalidOperation, ValueError):
        return None


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
    """'2026-05-01' ou '2026-05' -> '05/2026' (mês/ano de competência). A NPP guarda a
    competência como 'AAAA-MM' (sem dia), que o fromisoformat não parseia — tratamos
    esse caso explicitamente antes de cair no parse de data completa."""
    if not iso:
        return TRACO
    s = str(iso)
    ano, _, mes = s.partition("-")
    if len(ano) == 4 and ano.isdigit() and len(mes) == 2 and mes.isdigit():
        return f"{mes}/{ano}"
    try:
        return datetime.fromisoformat(s).strftime("%m/%Y")
    except ValueError:
        return s


def npp_curto(numero) -> str:
    """'NPP_MNS_20260604_0001' -> '04/06 · 0001'. Rótulo de UI da NPP: o operador
    trabalha na sua própria instância, então o prefixo 'NPP' (óbvio pelo contexto da
    tela) e as iniciais do operador são ruído — sobra data (dia/mês) e sequencial.

    Só apresentação (I-2): o `numero` completo segue **imutável** no banco (é a
    identidade) e **inteiro** no artefato exportado; a autoria das iniciais continua
    persistida em `criada_por` e visível na linha 'Responsável' do detalhe (I-4).
    Fora do padrão (sem 8 dígitos de data), devolve o que veio — nunca inventa (I-6)."""
    partes = str(numero or "").split("_")
    if len(partes) >= 4 and len(partes[-2]) == 8 and partes[-2].isdigit():
        d = partes[-2]
        return f"{d[6:8]}/{d[4:6]} · {partes[-1]}"
    return str(numero) if numero else TRACO


def cnpj(valor) -> str:
    """14 dígitos -> '11.222.333/0001-81'. Fora disso, devolve o que veio."""
    d = _digitos(valor)
    if len(d) != 14:
        return str(valor) if valor else TRACO
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def cpf(valor) -> str:
    """11 dígitos -> '123.456.789-09'. Fora disso, devolve o que veio."""
    d = _digitos(valor)
    if len(d) != 11:
        return str(valor) if valor else TRACO
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def documento(valor) -> str:
    """CPF (11 díg) ou CNPJ (14 díg), formatado no padrão br conforme o tamanho.
    Fora desses tamanhos, devolve o que veio (I-6: não chuta máscara)."""
    d = _digitos(valor)
    if len(d) == 11:
        return cpf(d)
    if len(d) == 14:
        return cnpj(d)
    return str(valor) if valor else TRACO


def parse_competencia(texto) -> str | None:
    """Lê uma competência/vigência digitada (mm/aaaa) e canoniza para 'MM/AAAA'.
    Aceita digitação corrida ('052026'), com barra ('5/2026') ou já formatada. Só
    apresentação/normalização de entrada (I-2). Inválido/vazio -> devolve o texto cru
    (ou None se vazio), nunca adivinha mês/ano (I-6)."""
    if texto is None:
        return None
    bruto = str(texto).strip()
    if not bruto:
        return None
    d = _digitos(bruto)
    # mmaaaa (6) ou maaaa (5, mês de 1 dígito) -> separa em mês/ano e zero-padda o mês.
    if len(d) in (5, 6):
        mes, ano = d[:-4], d[-4:]
        mes_i = int(mes)
        if 1 <= mes_i <= 12:
            return f"{mes_i:02d}/{ano}"
    return bruto


def parse_subitem(texto) -> str | None:
    """Canoniza o subitem da lista LC 116 (N.NN): '702' -> '7.02', '1705' -> '17.05'.
    Aceita já pontuado. Só normalização de entrada (I-2). Vazio -> None; entrada que não
    é só dígitos (ou já vem pontuada) -> devolve o que veio, não adivinha (I-6)."""
    if texto is None:
        return None
    bruto = str(texto).strip()
    if not bruto:
        return None
    d = _digitos(bruto)
    # Só formata a digitação corrida (3+ dígitos, sem pontuação). Já pontuado/curto: cru.
    if d == bruto and len(d) >= 3:
        return f"{d[:-2]}.{d[-2:]}"
    return bruto


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
