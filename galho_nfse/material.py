"""
Sugestão de material aplicado a partir da discriminação (texto livre) — NFS-e.

CONTEXTO DE INVARIANTE (docs/00, "Caso especial: material aplicado"):
- A `discriminacao` é texto livre. A extração (Fase 1) NÃO interpreta esse texto.
- Esta função é a semente da capacidade que o docs/00 chama de "versão futura":
  um classificador que **sugere** a partir do texto, destilado de exemplos reais.
- Ela só foi ligada por decisão humana explícita, e opera dentro do I-3: produz
  **sugestão**, nunca verdade. O sistema NUNCA aplica o valor sozinho — quem
  decide é o operador, que vê o texto original e valida/edita (a UI cuida disso).
  Só o valor VALIDADO pelo operador é persistido e exportado.

Por que é CONSERVADORA (distilada dos dados reais):
- Notas reais (ex.: Orbenk) trazem no texto valores que NÃO são material —
  "Valor RS 11597.60" (bruto) e "VALOR LIQUIDO DA NOTA FISCAL RS ..." (líquido).
  Um extrator que pegasse "qualquer R$" daria falso positivo e erraria a base de
  INSS. Por isso só sugerimos um valor quando ele aparece **amarrado à palavra
  'material'** dentro da mesma frase; caso contrário, não sugerimos nada e o
  operador decide do zero.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# "material", "materiais", "materia", "materiel"...
_RE_MATERI = re.compile(r"materi", re.IGNORECASE)
# negação: "sem (emprego/uso de) material"
_RE_SEM_MATERI = re.compile(r"sem\s+(?:emprego\s+de\s+|uso\s+de\s+)?materi", re.IGNORECASE)
# valor monetário amarrado a um indício de valor: "R$ 1.200,00", "RS 1200.00",
# "valor de R$ 1.200,00". Exige prefixo de moeda OU a palavra "valor" antes,
# e duas casas decimais — evita pegar datas (02/2026) ou postos (12x36).
_RE_VALOR = re.compile(
    r"(?:r\$|rs|valor(?:\s+de)?)\s*(?:r\$|rs)?\s*"
    r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2})",
    re.IGNORECASE,
)


def _normalizar(num: str) -> str | None:
    """'1.200,00' -> '1200.00'; '1200.00' -> '1200.00'. Devolve string decimal."""
    s = num.strip()
    if "," in s:                       # formato pt-BR: ponto é milhar, vírgula é decimal
        s = s.replace(".", "").replace(",", ".")
    try:
        return f"{Decimal(s):.2f}"
    except (InvalidOperation, ValueError):
        return None


def _frase_do_indice(texto: str, i: int) -> str:
    """Frase que contém a posição i. Fim de frase é '.'/'\\n' seguido de espaço ou
    do fim do texto — assim o ponto de milhar de '1.200,00' NÃO quebra a frase."""
    ini = 0
    for m in re.finditer(r"\.\s|\n", texto[:i]):
        ini = m.end()
    fim_m = re.search(r"\.\s|\.$|\n", texto[i:])
    fim = i + fim_m.start() if fim_m else len(texto)
    return texto[ini:fim].strip()


def sugerir_material(discriminacao: str | None) -> dict:
    """Sugere presença e valor de material a partir do texto livre.

    Devolve sempre um dict (nunca decide nada — só sugere):
      {"presenca": "sim"|"nao"|None, "valor": "<decimal>"|None, "trecho": str|None}
    - presenca "nao": o texto nega material ("sem emprego de material").
    - presenca "sim" + valor: achou um valor amarrado à palavra 'material'.
    - tudo None: o texto não permite sugerir — o operador decide do zero.
    """
    vazio = {"presenca": None, "valor": None, "trecho": None}
    if not discriminacao:
        return vazio
    texto = str(discriminacao)

    if _RE_SEM_MATERI.search(texto):
        m = _RE_SEM_MATERI.search(texto)
        return {"presenca": "nao", "valor": None, "trecho": _frase_do_indice(texto, m.start())}

    m = _RE_MATERI.search(texto)
    if not m:
        return vazio                    # sem menção a material: nada a sugerir

    frase = _frase_do_indice(texto, m.start())
    achou = _RE_VALOR.search(frase)
    if not achou:
        # menciona material mas sem valor amarrado: sugere presença, não o valor
        return {"presenca": "sim", "valor": None, "trecho": frase}
    valor = _normalizar(achou.group(1))
    return {"presenca": "sim" if valor else None, "valor": valor, "trecho": frase}
