"""
Idempotência por chave — o coração do tronco (invariante I-1).

Regras que este módulo materializa, vindas de 00_PRINCIPIOS e 01_ARQUITETURA §5:

- A chave (44 díg da NF-e ou id único da NFS-e) é PRIMARY KEY. O banco recusa
  duplicata por construção — não dependemos de o código "lembrar" de checar.
- Antes de montar um lote: nota já registrada => status JÁ_EXPORTADA. Isso é
  status, não erro (I-1, I-6).
- A gravação no registro acontece SÓ APÓS o sucesso da exportação, nunca antes.
  Se a exportação falha, a nota continua exportável numa próxima tentativa.

Duplicação inter-lote é o erro de maior custo do sistema (pagamento em
duplicidade). Este módulo existe para torná-lo impossível por construção.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "registro_exportacao.sqlite"


class RegistroDeExportacao:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self.caminho = str(caminho)
        self._conn = sqlite3.connect(self.caminho)
        self._conn.row_factory = sqlite3.Row
        self._criar_tabela()

    def _criar_tabela(self) -> None:
        # chave como PRIMARY KEY: o próprio banco impede duplicata (I-1).
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exportacoes (
                chave        TEXT PRIMARY KEY,
                tipo         TEXT NOT NULL,        -- 'NFE' ou 'NFSE'
                lote_id      TEXT NOT NULL,
                exportado_em TEXT NOT NULL         -- ISO-8601 UTC
            )
            """
        )
        self._conn.commit()

    def ja_exportada(self, chave: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM exportacoes WHERE chave = ?", (chave,)
        )
        return cur.fetchone() is not None

    def filtrar_novas(self, chaves: list[str]) -> tuple[list[str], list[str]]:
        """Divide chaves em (novas, ja_exportadas). Não grava nada."""
        novas, repetidas = [], []
        for chave in chaves:
            (repetidas if self.ja_exportada(chave) else novas).append(chave)
        return novas, repetidas

    def listar(self) -> list[dict]:
        """Lista as exportações já registradas (mais recentes primeiro). Leitura
        do registro de idempotência — alimenta a tela de Histórico (I-1). Não é
        apuração nem altera nada: só devolve o que já foi exportado."""
        cur = self._conn.execute(
            "SELECT chave, tipo, lote_id, exportado_em FROM exportacoes "
            "ORDER BY exportado_em DESC, lote_id DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def registrar_lote(self, chaves_tipos: list[tuple[str, str]], lote_id: str) -> None:
        """
        Grava as chaves de um lote APÓS exportação bem-sucedida.

        Recebe pares (chave, tipo). Usa INSERT OR IGNORE para que uma corrida
        improvável não estoure — a PRIMARY KEY garante unicidade de qualquer modo.
        Chamar este método é responsabilidade de quem confirmou o sucesso da
        exportação; nunca antes dela.
        """
        agora = agora_maquina().isoformat()
        self._conn.executemany(
            "INSERT OR IGNORE INTO exportacoes (chave, tipo, lote_id, exportado_em) "
            "VALUES (?, ?, ?, ?)",
            [(chave, tipo, lote_id, agora) for chave, tipo in chaves_tipos],
        )
        self._conn.commit()

    def importar(self, registros: list[dict]) -> int:
        """União append-only do ledger I-1 a partir de um snapshot. INSERT OR IGNORE
        PRESERVANDO `lote_id` e `exportado_em` originais; chave já presente é no-op.

        Por que unir é seguro em QUALQUER máquina (decisão do humano): marcar uma chave
        como já exportada só pode IMPEDIR um pagamento futuro, nunca causá-lo. O ledger
        nunca perde uma chave nem reabre uma nota paga como exportável — é a trava que
        impede pagamento em duplicidade ao transportar/restaurar trabalho. Retorna quantas
        chaves novas entraram."""
        antes = self._conn.execute("SELECT COUNT(*) FROM exportacoes").fetchone()[0]
        self._conn.executemany(
            "INSERT OR IGNORE INTO exportacoes (chave, tipo, lote_id, exportado_em) "
            "VALUES (?, ?, ?, ?)",
            [(r["chave"], r["tipo"], r["lote_id"], r["exportado_em"]) for r in registros],
        )
        self._conn.commit()
        depois = self._conn.execute("SELECT COUNT(*) FROM exportacoes").fetchone()[0]
        return depois - antes

    def fechar(self) -> None:
        self._conn.close()
