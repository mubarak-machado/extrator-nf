"""
Links de consulta pública nos portais nacionais (tronco — comum aos dois galhos).

É CONVENIÊNCIA DE CONFERÊNCIA, não extração (I-2): a chave já foi extraída do
XML; aqui apenas apontamos o operador para o portal oficial onde ELE confere a
nota colando a chave. Os portais nacionais são captcha/SPA e NÃO expõem um
deep-link público pela chave crua — então o link abre a página de consulta e o
operador cola a chave. Não fingimos abrir a nota específica (I-6): a tela diz
explicitamente que a conferência é feita por ele no site oficial.

URLs verificadas (jun/2026):
  - NF-e: portal nacional da RFB, consulta por chave de 44 dígitos + captcha.
  - NFS-e: portal nacional (padrão nacional), consulta "Por Chave de Acesso"
    de 50 dígitos.
São constantes mantidas à mão — se o endereço de uma consulta mudar, troca-se
aqui (um lugar só).
"""
from __future__ import annotations

PORTAIS = {
    "NFE": {
        "nome": "Portal Nacional da NF-e",
        "url": "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx"
               "?tipoConsulta=resumo&tipoConteudo=7PhJ+gAVw2g%3D",
    },
    "NFSE": {
        "nome": "Portal Nacional da NFS-e",
        "url": "https://www.nfse.gov.br/consultapublica",
    },
}


def portal_consulta(tipo: str | None) -> dict | None:
    """Devolve {nome, url} do portal de consulta do tipo, ou None se desconhecido
    (tipo não mapeado não inventa link — a ausência é visível, I-6)."""
    return PORTAIS.get(tipo or "")
