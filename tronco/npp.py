"""
NPP — Nota de Pré-Pagamento (tronco).

Entidade explícita que amarra **nota → NPP → contrato**, substituindo a heurística por
CNPJ. Pertence a **um** contrato e **uma** competência e agrupa 1+ notas. Vários NPPs no
mesmo (contrato, competência) são válidos (decisão do humano) — por isso **NÃO** há UNIQUE
nesse par.

O `numero` (`NPP_<iniciais>_<AAAAMMDD>_<NNNN>`) é gerado na criação e é o identificador
**estável e portátil** da NPP: a app roda local em cada máquina e o export/import de NPPs
entre operadores é etapa futura. A sequência `NNNN` reinicia a cada dia, contada
localmente. Por ser identidade, o `numero` é **imutável** após criado.

Invariantes:
- I-4 (rastreável): `criada_por` (identidade do operador) + `criada_em`/`atualizada_em`;
  as iniciais no `numero` carregam a autoria.
- I-6 (ambiguidade visível): criar sem contrato, competência ou iniciais é **erro visível**
  — nunca inventa identidade nem vínculo.
- O **status** da NPP (aberta/exportada/vazia) NÃO é armazenado: é derivado das notas
  (como a consolidação derivava 'novas'). Aqui vive só o vínculo.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "npps.sqlite"


@dataclass
class NPP:
    numero: str = ""                    # NPP_<iniciais>_<AAAAMMDD>_<NNNN> — gerado, imutável
    contrato_id: int | None = None      # FK → contratos.id (obrigatório na criação)
    competencia: str = ""               # "AAAA-MM" (mesma forma do dCompet da nota)
    rotulo: str | None = None           # rótulo humano opcional (o numero já desambigua)
    observacoes: str | None = None
    criada_por: str = "operador"        # I-4 — identidade do operador
    criada_em: str | None = None        # ISO-8601 UTC
    atualizada_em: str | None = None
    id: int | None = None


class StoreNPP:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        # (contrato_id, competencia) NÃO é UNIQUE — várias NPPs no mesmo par são válidas.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS npps (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                numero        TEXT NOT NULL UNIQUE,
                contrato_id   INTEGER NOT NULL,
                competencia   TEXT NOT NULL,
                rotulo        TEXT,
                observacoes   TEXT,
                criada_por    TEXT NOT NULL,
                criada_em     TEXT NOT NULL,
                atualizada_em TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def criar(self, *, contrato_id, competencia, iniciais, autor,
              rotulo=None, observacoes=None, agora=None) -> NPP:
        """Cria uma NPP nova: gera o `numero` (sequência por dia) e grava com autoria (I-4).
        `agora` é injetável (testes); default = agora UTC."""
        if contrato_id is None:
            raise ValueError("NPP exige um contrato")
        if not (competencia or "").strip():
            raise ValueError("NPP exige a competência")
        agora = agora or agora_maquina()
        numero = self._proximo_numero(iniciais, agora)
        ts = agora.isoformat()
        cur = self._conn.execute(
            "INSERT INTO npps (numero, contrato_id, competencia, rotulo, observacoes, "
            "criada_por, criada_em, atualizada_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (numero, contrato_id, competencia, rotulo, observacoes, autor, ts, ts),
        )
        self._conn.commit()
        return NPP(numero=numero, contrato_id=contrato_id, competencia=competencia,
                   rotulo=rotulo, observacoes=observacoes, criada_por=autor,
                   criada_em=ts, atualizada_em=ts, id=cur.lastrowid)

    def _proximo_numero(self, iniciais, agora: datetime) -> str:
        ini = (iniciais or "").strip().upper()
        if not ini:
            raise ValueError("iniciais do operador ausentes — cadastre o operador")
        prefixo = f"NPP_{ini}_{agora.strftime('%Y%m%d')}_"
        # NNNN é zero-padded de 4 dígitos: ordem lexical = ordem numérica (até 9999/dia).
        row = self._conn.execute(
            "SELECT numero FROM npps WHERE numero LIKE ? ORDER BY numero DESC LIMIT 1",
            (prefixo + "%",),
        ).fetchone()
        seq = int(row["numero"].rsplit("_", 1)[-1]) + 1 if row else 1
        return f"{prefixo}{seq:04d}"

    def salvar(self, npp: NPP) -> int:
        """Atualiza uma NPP existente (competência/rótulo/observações). NÃO gera `numero`
        nem cria — use `criar` para nova NPP; o `numero` é imutável."""
        if npp.id is None:
            raise ValueError("use criar() para uma NPP nova; salvar() só atualiza")
        npp.atualizada_em = agora_maquina().isoformat()
        self._conn.execute(
            "UPDATE npps SET competencia = ?, rotulo = ?, observacoes = ?, atualizada_em = ? "
            "WHERE id = ?",
            (npp.competencia, npp.rotulo, npp.observacoes, npp.atualizada_em, npp.id),
        )
        self._conn.commit()
        return npp.id

    def _do_row(self, row: sqlite3.Row) -> NPP:
        return NPP(id=row["id"], numero=row["numero"], contrato_id=row["contrato_id"],
                   competencia=row["competencia"], rotulo=row["rotulo"],
                   observacoes=row["observacoes"], criada_por=row["criada_por"],
                   criada_em=row["criada_em"], atualizada_em=row["atualizada_em"])

    def listar(self) -> list[NPP]:
        cur = self._conn.execute("SELECT * FROM npps ORDER BY criada_em DESC, id DESC")
        return [self._do_row(r) for r in cur.fetchall()]

    def obter(self, id_: int) -> NPP | None:
        row = self._conn.execute("SELECT * FROM npps WHERE id = ?", (id_,)).fetchone()
        return self._do_row(row) if row else None

    def listar_por_contrato(self, contrato_id: int) -> list[NPP]:
        cur = self._conn.execute(
            "SELECT * FROM npps WHERE contrato_id = ? ORDER BY competencia DESC, id DESC",
            (contrato_id,),
        )
        return [self._do_row(r) for r in cur.fetchall()]

    def remover(self, id_: int) -> None:
        self._conn.execute("DELETE FROM npps WHERE id = ?", (id_,))
        self._conn.commit()

    def fechar(self) -> None:
        self._conn.close()
