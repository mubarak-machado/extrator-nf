"""
Motor de enquadramento de retenção de **INSS** (galho NFS-e, Fase 2).

Espelho do motor federal (`galho_nfse/enquadramento.py`): aqui mora **só a estrutura e
o casamento** da regra de INSS (IN RFB 2110/2022). As regras em si — cada item do
catálogo — o especialista cadastra pela tela **Regras** (aba INSS), persistidas por
`StoreRegrasInss` (`galho_nfse/catalogo_inss.py`). Este módulo não inventa regra nenhuma;
estrutura (`RegraInss`) e aplica (`aplicar_catalogo_inss`) o que foi lançado.

O INSS é próprio do serviço (não existe na NF-e mercantil), por isso vive no galho — ao
contrário do federal, que é comum aos dois galhos (tronco).

Cada regra é **auto-descritiva**: carrega a *condição* (natureza do prestador, categoria
do serviço, previsão de material) e o *efeito* (incide?, alíquota 11%/3,5%, base mínima
quando o material não é discriminado, adicional de aposentadoria especial). A derivação
devolve a **primeira** regra cuja condição casar — a ordem no catálogo importa.

Fronteira de invariante (00_PRINCIPIOS):
- I-3: **sugere** o enquadramento; quem ratifica é o humano ao salvar o contrato. Puro,
  sem efeito colateral — não grava nem decide sozinho. Estrutura a regra, não a inventa.
- I-6: nenhuma regra casa → `regra=None` com motivo **visível**; nunca um padrão chutado.
- I-2: só lê características já cadastradas no contrato; não toca a extração da nota.
- I-4: cada regra do catálogo guarda autor e data (criação/edição), rastreável.
"""
from __future__ import annotations

from dataclasses import dataclass


def _pct_txt(v: str | None) -> str:
    if not v:
        return "—"
    return v.replace(".", ",") + "%"


def _casa_campo(valor, conjunto) -> bool:
    """Condição vazia não restringe; senão o valor do contrato precisa estar nela."""
    return not conjunto or valor in conjunto


@dataclass
class RegraInss:
    codigo: str                      # estável, definido pelo sistema (ex.: "INSS-001")
    descricao: str                   # rótulo curto p/ a tabela do operador
    fundamento: str                  # IN/artigo (ex.: "IN RFB 2110/2022, art. 112")
    # --- Condição: quando a regra se aplica (tupla vazia = não restringe esse campo) ---
    naturezas: tuple[str, ...] = ()  # prest_natureza que casam (ver contratos.NATUREZAS)
    categorias: tuple[str, ...] = () # categoria_servico que casam (ver contratos.CATEGORIAS)
    materiais: tuple[str, ...] = ()  # material_previsao que casam (ver contratos.MATERIAL_PREVISAO)
    # --- Efeito: o enquadramento que a regra dita ---
    cessao_mao_obra: bool = False    # o INSS incide (cessão de mão de obra/empreitada)?
    aliquota: str | None = None      # "11" | "3.5" (desoneração CPRB)
    base_minima_pct: str | None = None   # ver contratos.BASES_MINIMAS ("50"/"65"/"80"/"30")
    adicional_pct: str | None = None     # ver contratos.INSS_ADICIONAL ("4"/"3"/"2")
    # --- Persistência / ordem de avaliação / auditoria (I-4) ---
    ordem: int = 0                   # menor = avaliada primeiro (a 1ª que casa vence)
    criado_por: str = "operador"
    criado_em: str | None = None
    atualizado_em: str | None = None
    id: int | None = None

    def casa(self, contrato) -> bool:
        """A condição da regra casa com as características do contrato?"""
        return (_casa_campo(contrato.prest_natureza, self.naturezas)
                and _casa_campo(contrato.categoria_servico, self.categorias)
                and _casa_campo(contrato.material_previsao, self.materiais))

    def aliquota_txt(self) -> str:
        return _pct_txt(self.aliquota)

    def resumo_txt(self) -> str:
        """Efeito em uma linha p/ a tabela (ex.: '11% +3%' ou 'dispensado')."""
        if not self.cessao_mao_obra:
            return "dispensado"
        txt = self.aliquota_txt()
        if self.adicional_pct:
            txt += f" +{_pct_txt(self.adicional_pct)}"
        return txt


@dataclass
class SugestaoInss:
    regra: RegraInss | None             # a regra casada; None = indefinido (I-6)
    indefinido_motivo: str = ""         # preenchido quando regra is None


_MOTIVO_SEM_REGRA = (
    "Nenhuma regra de INSS do catálogo casa com as características deste contrato. "
    "Defina o enquadramento de INSS manualmente, com justificativa, ou cadastre a "
    "regra na tela Regras."
)


def aplicar_catalogo_inss(contrato, catalogo=None) -> SugestaoInss:
    """Devolve a **primeira** regra do `catalogo` (lista de `RegraInss`, já ordenada)
    cuja condição casa com o `contrato` — ou indefinido, com motivo visível. Pura: não
    faz I/O nem grava (I-3). Quem chama carrega o catálogo do banco
    (`StoreRegrasInss.listar()`) e passa aqui; `None` é tratado como vazio."""
    for regra in (catalogo or []):
        if regra.casa(contrato):
            return SugestaoInss(regra)
    return SugestaoInss(None, _MOTIVO_SEM_REGRA)
