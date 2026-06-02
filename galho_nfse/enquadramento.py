"""
Motor de enquadramento de retenção federal (galho NFS-e, Fase 2).

Aqui mora **só a estrutura e o casamento** das regras de tratamento tributário dos
tributos **federais** (IR, CSLL, COFINS, PIS). As regras em si — cada item do catálogo
— o especialista cadastra pela tela **Regras**, persistidas por `StoreRegrasFederais`
(`galho_nfse/catalogo_federal.py`). Este módulo não inventa regra nenhuma; ele apenas
estrutura (`RegraEnquadramento`) e aplica (`aplicar_catalogo_federal`) o que foi lançado.

Cada regra é **auto-descritiva**: carrega a *condição* que a aplica (natureza do
prestador, categoria do serviço, previsão de material) e o *efeito* (alíquota de IR, o
trio CSLL/COFINS/PIS, código de receita). A derivação devolve a **primeira** regra cuja
condição casar com o contrato — por isso a ordem no catálogo importa.

Fronteira de invariante (00_PRINCIPIOS) — leia antes de mexer:
- I-3: isto **sugere** o enquadramento a partir das características; quem ratifica é o
  humano ao salvar (a rota grava). Funções **puras, sem efeito colateral** — não gravam
  nem decidem sozinhas. O sistema **estrutura** a regra, não a inventa.
- I-6: nenhuma regra casa (catálogo vazio ou característica não prevista) → `regra=None`
  com motivo **visível**; nunca um padrão chutado. A tela obriga ajuste manual justificado.
- I-2: só lê características já cadastradas no contrato; não toca a extração da nota.
- I-4: cada regra do catálogo guarda autor e data (criação/edição), rastreável.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Alíquotas fixas das contribuições federais — o "trio" dos 4,65% (CSLL+COFINS+PIS).
_TRIO = (("csll", Decimal("1")), ("cofins", Decimal("3")), ("pis", Decimal("0.65")))


def _pct_txt(v: Decimal) -> str:
    return (f"{v:.2f}".rstrip("0").rstrip(".")).replace(".", ",") + "%"


def _casa_campo(valor, conjunto) -> bool:
    """Condição vazia não restringe; senão o valor do contrato precisa estar nela."""
    return not conjunto or valor in conjunto


@dataclass
class RegraEnquadramento:
    codigo: str                      # estável, definido pelo especialista (ex.: "TF-001")
    descricao: str                   # rótulo curto p/ a tabela do operador
    fundamento: str                  # IN/artigo (ex.: "IN RFB 1234/2012, Anexo I")
    # --- Condição: quando a regra se aplica (tupla vazia = não restringe esse campo) ---
    naturezas: tuple[str, ...] = ()  # prest_natureza que casam (ver contratos.NATUREZAS)
    categorias: tuple[str, ...] = () # categoria_servico que casam (ver contratos.CATEGORIAS)
    materiais: tuple[str, ...] = ()  # material_previsao que casam (ver contratos.MATERIAL_PREVISAO)
    # --- Efeito: o enquadramento que a regra dita ---
    sujeito: bool = False            # o grupo federal incide?
    ir_pct: str | None = None        # "1.2" | "4.8" | … (None quando dispensado)
    csll: bool = False
    cofins: bool = False
    pis: bool = False
    codigo_receita: str | None = None
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

    def agregada_pct(self) -> Decimal:
        """Alíquota agregada do grupo: IR + as contribuições que incidem. Derivada
        (nunca digitada) — ex.: IR 4,8 + 4,65 = 9,45."""
        total = Decimal(self.ir_pct) if self.ir_pct else Decimal(0)
        for nome, taxa in _TRIO:
            if getattr(self, nome):
                total += taxa
        return total

    def ir_txt(self) -> str:
        return _pct_txt(Decimal(self.ir_pct)) if self.ir_pct else "—"

    def agregada_txt(self) -> str:
        return _pct_txt(self.agregada_pct())


@dataclass
class SugestaoFederal:
    regra: RegraEnquadramento | None    # a regra casada; None = indefinido (I-6)
    indefinido_motivo: str = ""         # preenchido quando regra is None


_MOTIVO_SEM_REGRA = (
    "Nenhuma regra do catálogo casa com as características deste contrato. "
    "Defina o enquadramento federal manualmente, com justificativa, ou cadastre a "
    "regra na tela Regras."
)


def aplicar_catalogo_federal(contrato, catalogo=None) -> SugestaoFederal:
    """Devolve a **primeira** regra do `catalogo` (lista de `RegraEnquadramento`, já
    ordenada) cuja condição casa com o `contrato` — ou indefinido, com motivo visível.
    Pura: não faz I/O nem grava (I-3). Quem chama carrega o catálogo do banco
    (`StoreRegrasFederais.listar()`) e passa aqui; `None` é tratado como vazio."""
    for regra in (catalogo or []):
        if regra.casa(contrato):
            return SugestaoFederal(regra)
    return SugestaoFederal(None, _MOTIVO_SEM_REGRA)
