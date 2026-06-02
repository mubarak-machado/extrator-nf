"""
Armazenamento das notas importadas (tronco).

Mudança de modelo: o app **não lê XML ao vivo** a cada tela. A leitura do XML
acontece **uma única vez**, na importação manual disparada pelo usuário; o
resultado (o registro plano já extraído — §4 do 01_ARQUITETURA) é guardado aqui.
As telas leem deste banco, nunca da pasta de exemplos.

Por que isto não fere os invariantes:
- I-1: a idempotência continua no `RegistroDeExportacao` (PK por chave). Aqui a
  chave também é PRIMARY KEY, então reimportar a mesma nota não duplica linha.
- I-2: guardamos o que foi extraído fielmente (asdict do registro), sem
  interpretar nada. Persistir não é apurar.
- I-6: importar é explícito; arquivos ilegíveis são reportados a quem importou,
  não engolidos (a rota cuida disso).

A reconstrução do objeto de registro a partir do JSON vive em `reconstruir`, que
importa o modelo do galho certo de forma tardia (como a ingestão faz).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tronco.config import caminho_dado
CAMINHO_PADRAO = caminho_dado("notas.sqlite")


def reconstruir(tipo: str, dados: dict) -> Any:
    """Recria o registro plano (RegistroNFe/RegistroNFSe) a partir do dict salvo.

    Os modelos são dataclasses; `asdict` produz exatamente os nomes dos campos,
    então a reconstrução é direta. Import tardio para não acoplar o tronco aos
    galhos no topo do módulo (mesma disciplina da ingestão)."""
    if tipo == "NFE":
        from galho_nfe.modelo import RegistroNFe
        return RegistroNFe(**dados)
    if tipo == "NFSE":
        from galho_nfse.modelo import RegistroNFSe
        return RegistroNFSe(**dados)
    raise ValueError(f"tipo de nota desconhecido: {tipo!r}")


class StoreNotas:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        # chave como PRIMARY KEY: reimportar a mesma nota não duplica (alinhado a I-1).
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notas (
                chave        TEXT PRIMARY KEY,
                tipo         TEXT NOT NULL,        -- 'NFE' ou 'NFSE'
                origem       TEXT,                 -- nome do arquivo de origem
                dados_json   TEXT NOT NULL,        -- asdict do registro extraído
                importado_em TEXT NOT NULL         -- ISO-8601 UTC
            )
            """
        )
        self._conn.commit()

    def salvar(self, chave: str, tipo: str, dados: dict, origem: str = "") -> None:
        """Insere/atualiza uma nota. REPLACE para que reimportar reflita o XML
        atual sem estourar a PRIMARY KEY."""
        self._conn.execute(
            "INSERT OR REPLACE INTO notas (chave, tipo, origem, dados_json, importado_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (chave, tipo, origem, json.dumps(dados, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def listar(self) -> list[dict]:
        """Notas importadas, mais recentes primeiro. Cada item traz `dados` já
        desserializado (o dict do registro plano)."""
        cur = self._conn.execute(
            "SELECT chave, tipo, origem, dados_json, importado_em FROM notas "
            "ORDER BY importado_em DESC, chave"
        )
        out = []
        for r in cur.fetchall():
            out.append({"chave": r["chave"], "tipo": r["tipo"], "origem": r["origem"],
                        "importado_em": r["importado_em"],
                        "dados": json.loads(r["dados_json"])})
        return out

    def contar(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM notas").fetchone()[0]

    def fechar(self) -> None:
        self._conn.close()
