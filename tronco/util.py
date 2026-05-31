"""
Utilitários compartilhados pelo tronco e pelos galhos.

Dois problemas práticos que aparecem ao ler XML via nfelib (bindings xsdata):

1. Campos de enumeração vêm como objetos Enum (ex.: Tmod.VALUE_55), não como
   string "55". `desenum` desembrulha para o valor cru.

2. A árvore do XML é profunda e cheia de campos opcionais. Acessar
   `inf.dest.CNPJ` quebra com AttributeError se `dest` for None. `pega` caminha
   o caminho e devolve None em qualquer elo ausente — em vez de estourar.

Isso serve diretamente ao invariante I-6 (00_PRINCIPIOS): campo ausente vira
None visível (e a tela mostra "—" / "confira"), nunca uma exceção que esconde a
nota inteira nem um chute para "preencher" o buraco.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any


def desenum(valor: Any) -> Any:
    """Desembrulha Enum -> seu .value; Decimal -> str; resto inalterado."""
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def pega(raiz: Any, *caminho: str) -> Any:
    """
    Caminha atributos aninhados com tolerância a None.

    pega(inf, "dest", "CNPJ") devolve inf.dest.CNPJ, ou None se `dest` (ou
    qualquer elo) for None/inexistente. Aplica `desenum` ao resultado final.
    """
    atual = raiz
    for parte in caminho:
        if atual is None:
            return None
        atual = getattr(atual, parte, None)
    return desenum(atual)


def so_digitos(texto: Any) -> str:
    """Mantém apenas dígitos. Útil para normalizar chaves de acesso."""
    if texto is None:
        return ""
    return "".join(c for c in str(texto) if c.isdigit())
