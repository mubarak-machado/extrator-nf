"""
Identidade do operador — cadastro local da máquina (tronco).

A aplicação roda **local em cada máquina** e não tem autenticação (POC de um usuário).
Mesmo assim, o I-4 exige que marcações e decisões sejam **rastreáveis por autor**: é
daqui que sai esse autor. Na primeira inicialização o operador faz um cadastro básico
(iniciais + nome); as iniciais compõem o `numero` da NPP (ver `tronco.npp`) e o nome/iniciais
alimentam `criada_por`/`autor` nas marcações e validações (I-4).

Mora no próprio repositório (`operador.sqlite`), separado dos dados de notas — por isso o
**reset do piloto não o apaga** (é identidade da máquina, não dado de teste). Esses dados
entram, no futuro, na função de backup/sincronização da aplicação (fora deste escopo).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "operador.sqlite"


@dataclass
class Operador:
    iniciais: str = ""               # ex. "MNM" — compõe o numero da NPP (sem espaços/símbolos)
    nome: str = ""                   # nome do operador (rastreabilidade e exibição)
    cadastrado_em: str | None = None  # ISO-8601 UTC
    id: int | None = None


def _normaliza_iniciais(valor: str) -> str:
    """Só letras/dígitos, caixa alta — para entrar no `numero` da NPP sem quebrá-lo
    (o separador do número é '_'). Vazio após limpar é erro (I-6: não inventa identidade)."""
    limpo = re.sub(r"[^A-Za-z0-9]", "", valor or "").upper()
    if not limpo:
        raise ValueError("iniciais do operador não podem ser vazias")
    return limpo


class StoreOperador:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operador (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                iniciais      TEXT NOT NULL,
                nome          TEXT NOT NULL,
                cadastrado_em TEXT NOT NULL      -- ISO-8601 UTC
            )
            """
        )
        self._conn.commit()

    def salvar(self, iniciais: str, nome: str) -> Operador:
        """Grava (ou regrava) a identidade do operador. Mantém histórico (append): a
        identidade vigente é a última — edições não apagam o que já embasou registros (I-4)."""
        ini = _normaliza_iniciais(iniciais)
        nome = (nome or "").strip()
        if not nome:
            raise ValueError("nome do operador é obrigatório")
        agora = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO operador (iniciais, nome, cadastrado_em) VALUES (?, ?, ?)",
            (ini, nome, agora),
        )
        self._conn.commit()
        return Operador(iniciais=ini, nome=nome, cadastrado_em=agora, id=cur.lastrowid)

    def atual(self) -> Operador | None:
        """Identidade vigente (a última cadastrada), ou None se a máquina ainda não tem."""
        row = self._conn.execute(
            "SELECT id, iniciais, nome, cadastrado_em FROM operador ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return Operador(**dict(row)) if row else None

    def existe(self) -> bool:
        return self.atual() is not None

    def fechar(self) -> None:
        self._conn.close()
