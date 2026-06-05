"""
Marcação de material aplicado — persistência com autoria e data (I-4).

Quando o usuário marca, numa NFS-e, se houve ou não emprego de material, essa
marcação afeta (na Fase 2) a base de INSS e a alíquota de IR. O invariante I-4
exige que isso seja DADO PERSISTIDO E RASTREÁVEL — nunca estado de tela. Aqui
guardamos por chave da nota: o valor marcado, quem marcou e quando.

Mantemos histórico (append) em vez de sobrescrever, para que uma marcação que
embasou uma apuração permaneça auditável mesmo se depois for corrigida.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "marcacoes.sqlite"


class StoreMarcacoes:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS marcacoes_material (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                chave          TEXT NOT NULL,
                valor          TEXT NOT NULL,     -- 'sim' ou 'nao'
                valor_material TEXT,              -- valor validado pelo operador (só quando 'sim')
                autor          TEXT NOT NULL,
                marcado_em     TEXT NOT NULL      -- ISO-8601 UTC
            )
            """
        )
        # Migração leve: bancos antigos não têm a coluna valor_material.
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(marcacoes_material)")}
        if "valor_material" not in cols:
            self._conn.execute("ALTER TABLE marcacoes_material ADD COLUMN valor_material TEXT")
        self._conn.commit()

    def marcar(self, chave: str, valor: str, autor: str,
               valor_material: str | None = None) -> None:
        """Grava a conferência humana. `valor_material` é o valor VALIDADO pelo
        operador (string decimal), guardado só quando houve material ('sim'). É a
        decisão humana (I-4) — nunca a sugestão crua da máquina."""
        if valor not in ("sim", "nao"):
            raise ValueError("valor de marcação deve ser 'sim' ou 'nao'")
        self._conn.execute(
            "INSERT INTO marcacoes_material (chave, valor, valor_material, autor, marcado_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (chave, valor, valor_material if valor == "sim" else None,
             autor or "desconhecido", agora_maquina().isoformat()),
        )
        self._conn.commit()

    def historico(self) -> list[dict]:
        """Todas as marcações já gravadas (append-only), em ordem cronológica (id). O
        backup precisa do rastro completo, não só da vigente — preservar autoria e data
        originais é o que mantém o I-4 auditável após um round-trip de snapshot."""
        cur = self._conn.execute(
            "SELECT chave, valor, valor_material, autor, marcado_em "
            "FROM marcacoes_material ORDER BY id"
        )
        return [dict(r) for r in cur.fetchall()]

    def importar(self, chave: str, valor: str, autor: str, marcado_em: str,
                 valor_material: str | None = None) -> bool:
        """Insere uma marcação vinda de um snapshot PRESERVANDO autor e data originais
        (I-4) — diferente de `marcar`, que carimba o relógio local. Idempotente: linha
        idêntica (mesma tupla) não duplica. Retorna True se inseriu, False se já existia."""
        if valor not in ("sim", "nao"):
            raise ValueError("valor de marcação deve ser 'sim' ou 'nao'")
        vm = valor_material if valor == "sim" else None
        ja = self._conn.execute(
            "SELECT 1 FROM marcacoes_material WHERE chave = ? AND valor = ? "
            "AND IFNULL(valor_material, '') = IFNULL(?, '') AND autor = ? AND marcado_em = ?",
            (chave, valor, vm, autor or "desconhecido", marcado_em),
        ).fetchone()
        if ja is not None:
            return False
        self._conn.execute(
            "INSERT INTO marcacoes_material (chave, valor, valor_material, autor, marcado_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (chave, valor, vm, autor or "desconhecido", marcado_em),
        )
        self._conn.commit()
        return True

    def atual(self, chave: str) -> dict | None:
        """Última marcação vigente para a chave (ou None se nunca marcada)."""
        cur = self._conn.execute(
            "SELECT valor, valor_material, autor, marcado_em FROM marcacoes_material "
            "WHERE chave = ? ORDER BY id DESC LIMIT 1",
            (chave,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def fechar(self) -> None:
        self._conn.close()
