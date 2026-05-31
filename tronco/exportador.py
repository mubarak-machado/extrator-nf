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
  2. cria o artefato novo com as notas inéditas;
  3. registra as chaves no SQLite SÓ APÓS o artefato existir.
"""
from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class TemLinha(Protocol):
    tipo: str
    chave: str
    COLUNAS: list[str]
    def linha_export(self) -> list: ...


class Exportador(ABC):
    @abstractmethod
    def exportar(self, registros: list[TemLinha], lote_id: str) -> str:
        """Cria um artefato NOVO com os registros e devolve seu identificador."""
        ...


class ExportadorCsvLocal(Exportador):
    """
    Destino do POC: um CSV novo por lote em `pasta_saida`. Como NF-e e NFS-e têm
    colunas próprias (galhos independentes), gera um arquivo por tipo dentro do
    lote. Append-only: nunca abre arquivo existente para edição.
    """

    def __init__(self, pasta_saida: str | Path) -> None:
        self.pasta_saida = Path(pasta_saida)
        self.pasta_saida.mkdir(parents=True, exist_ok=True)

    def exportar(self, registros: list[TemLinha], lote_id: str) -> str:
        if not registros:
            return ""
        por_tipo: dict[str, list[TemLinha]] = {}
        for r in registros:
            por_tipo.setdefault(r.tipo, []).append(r)

        artefatos = []
        for tipo, regs in por_tipo.items():
            destino = self.pasta_saida / f"lote_{lote_id}_{tipo}.csv"
            if destino.exists():
                # I-5: nunca sobrescrever um artefato de lote já criado.
                raise FileExistsError(
                    f"Artefato {destino.name} já existe — exportação é imutável por lote."
                )
            colunas = regs[0].COLUNAS
            with destino.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(colunas)
                for r in regs:
                    w.writerow(r.linha_export())
            artefatos.append(str(destino))
        return " | ".join(artefatos)


def novo_lote_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
