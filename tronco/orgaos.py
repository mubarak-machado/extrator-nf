"""
Razão social de órgãos públicos conhecidos, indexada por CNPJ.

Dado de REFERÊNCIA sobre o tomador (o próprio órgão que paga), não sobre o
emitente. Algumas notas trazem o nome do tomador abreviado, divergente ou
ausente; aqui mapeamos o CNPJ do órgão à sua razão social canônica, só para
EXIBIÇÃO. A extração fiel do XML (I-2) não é tocada — o `toma_nome` lido da nota
segue intacto no registro; este módulo apenas oferece um rótulo melhor à tela
quando o CNPJ é de um órgão que conhecemos.
"""
from __future__ import annotations

from tronco.util import so_digitos

# CNPJ (só dígitos) -> razão social canônica do órgão tomador.
_RAZAO_POR_CNPJ = {
    "26989715001699": "Procuradoria da República de Minas Gerais",
}


def nome(cnpj) -> str | None:
    """Razão social canônica do órgão cujo CNPJ é `cnpj`, ou None se desconhecido.
    Tolerante à formatação (aceita com ou sem máscara)."""
    return _RAZAO_POR_CNPJ.get(so_digitos(cnpj))
