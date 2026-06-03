"""
Exportação — etapa 4 do tronco (02_MAPA), atrás de interface plugável.

Invariante I-5: a exportação SEMPRE cria um artefato novo (um arquivo por lote),
append-only, imutável. Nunca altera/reordena/insere em estrutura editada à mão.

No MVP (POC), o destino concreto é um CSV local novo por lote. A troca pelo
Google Sheets (criar planilha nova via API) é um plugue: basta outra classe que
implemente `Exportador.exportar(...)`. A regra do I-5 vive na interface, não no
destino — então trocar o destino não pode reintroduzir escrita em planilha velha.

Fluxo correto (respeita I-1):
  1. filtra notas já exportadas (idempotência) ANTES de exportar;
  2. cria o artefato novo com as notas novas;
  3. registra as chaves no SQLite SÓ APÓS o artefato existir.
"""
from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from pathlib import Path

from tronco import formato
from tronco.util import agora as agora_maquina


class Exportador(ABC):
    @abstractmethod
    def exportar(self, itens: list[dict], spec, lote_id: str, sufixo: str) -> str:
        """Cria um artefato NOVO (um arquivo) e devolve seu identificador."""
        ...


class ExportadorCsvLocal(Exportador):
    """
    Destino do POC: um CSV novo por lote em `pasta_saida`. O FORMATO (quais
    colunas, em que ordem) é decidido pela `spec` recebida — o padrão individual e
    o consolidado espelham as respectivas tabelas da tela. Append-only: nunca abre
    arquivo existente para edição (I-5).
    """

    def __init__(self, pasta_saida: str | Path) -> None:
        self.pasta_saida = Path(pasta_saida)
        self.pasta_saida.mkdir(parents=True, exist_ok=True)

    def exportar(self, itens: list[dict], spec, lote_id: str, sufixo: str) -> str:
        """Escreve um CSV (cabeçalho + uma linha por item) a partir de uma `spec`
        (campo, cabeçalho, formato) e uma lista de dicts já montados por quem chama.
        utf-8-sig grava o BOM (Excel pt-BR abre com acentos certos) e ';' separa
        colunas (a vírgula é decimal no Brasil). I-5: recusa sobrescrever artefato."""
        if not itens:
            return ""
        destino = self.pasta_saida / f"lote_{lote_id}_{sufixo}.csv"
        if destino.exists():
            raise FileExistsError(
                f"Artefato {destino.name} já existe — exportação é imutável por lote."
            )
        with destino.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([cab for _, cab, _ in spec])
            for d in itens:
                w.writerow([formato.formatar(d.get(campo), fmt) for campo, _, fmt in spec])
        return str(destino)


def novo_lote_id() -> str:
    return agora_maquina().strftime("%Y%m%dT%H%M%S")
