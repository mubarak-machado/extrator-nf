"""
Persistência do catálogo de regras de enquadramento de **INSS** (galho NFS-e, Fase 2).

Espelho de `galho_nfse/catalogo_federal.py`: o especialista cadastra as regras pela tela
**Regras** (aba INSS); são gravadas aqui, em SQLite, e o motor (`galho_nfse/inss.py`) as
carrega para casar com cada contrato. A estrutura é `RegraInss` (definida no motor); este
módulo só guarda e devolve.

Fronteira de invariante (00_PRINCIPIOS):
- I-3: o store **guarda** o que o especialista dita; não infere nem aplica retenção. A
  regra só passa a *sugerir* enquadramento quando casa um contrato — e o humano ratifica.
- I-4: cada regra guarda autor e data (criação/edição), rastreável.
- I-6: enquanto não houver regra que case um contrato, o enquadramento cai em indefinido
  visível (tratado no motor e na tela), nunca chutado.

Campos de lista (naturezas/categorias/materiais) são guardados como CSV; o booleano
(cessao_mao_obra) como '0'/'1', no mesmo padrão de `catalogo_federal.py`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from galho_nfse.inss import RegraInss
from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "catalogo_inss.sqlite"


class StoreRegrasInss:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS regras_inss (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL,
                descricao TEXT,
                fundamento TEXT,
                naturezas TEXT,
                categorias TEXT,
                materiais TEXT,
                cessao_mao_obra TEXT,
                aliquota TEXT,
                base_minima_pct TEXT,
                adicional_pct TEXT,
                ordem INTEGER DEFAULT 0,
                criado_por TEXT,
                criado_em TEXT,
                atualizado_em TEXT,
                UNIQUE (codigo)
            )
            """
        )
        self._conn.commit()

    def _do_row(self, row: sqlite3.Row) -> RegraInss:
        return RegraInss(
            id=row["id"],
            codigo=row["codigo"],
            descricao=row["descricao"] or "",
            fundamento=row["fundamento"] or "",
            naturezas=_ler_lista(row["naturezas"]),
            categorias=_ler_lista(row["categorias"]),
            materiais=_ler_lista(row["materiais"]),
            cessao_mao_obra=_ler_bool(row["cessao_mao_obra"]),
            aliquota=row["aliquota"] or None,
            base_minima_pct=row["base_minima_pct"] or None,
            adicional_pct=row["adicional_pct"] or None,
            ordem=row["ordem"] or 0,
            criado_por=row["criado_por"] or "operador",
            criado_em=row["criado_em"],
            atualizado_em=row["atualizado_em"],
        )

    def listar(self) -> list[RegraInss]:
        """Todas as regras, na ordem de avaliação (menor `ordem` primeiro; desempate
        por id). É esta lista que o motor percorre — a primeira que casa vence."""
        cur = self._conn.execute("SELECT * FROM regras_inss ORDER BY ordem, id")
        return [self._do_row(r) for r in cur.fetchall()]

    def obter(self, id_: int) -> RegraInss | None:
        cur = self._conn.execute("SELECT * FROM regras_inss WHERE id = ?", (id_,))
        row = cur.fetchone()
        return self._do_row(row) if row else None

    def proxima_ordem(self) -> int:
        cur = self._conn.execute("SELECT COALESCE(MAX(ordem), 0) + 1 AS n FROM regras_inss")
        return cur.fetchone()["n"]

    def proximo_codigo(self, prefixo: str = "INSS") -> str:
        """Próximo código sequencial no formato ``<prefixo>-NNN`` (ex.: INSS-001).
        Controlado pelo sistema (o usuário não digita) — segue o maior já gravado."""
        marca = f"{prefixo}-"
        rows = self._conn.execute(
            "SELECT codigo FROM regras_inss WHERE codigo LIKE ?", (marca + "%",)
        ).fetchall()
        maior = 0
        for r in rows:
            sufixo = (r["codigo"] or "").rsplit("-", 1)[-1]
            if sufixo.isdigit():
                maior = max(maior, int(sufixo))
        return f"{marca}{maior + 1:03d}"

    def salvar(self, r: RegraInss) -> int:
        """Insere (id None) ou atualiza. Mantém criado_em; atualiza atualizado_em. A
        UNIQUE(codigo) impede código duplicado (estoura IntegrityError — tratado pela
        rota, I-6 visível)."""
        agora = agora_maquina().isoformat()
        r.atualizado_em = agora
        valores = {
            "codigo": r.codigo, "descricao": r.descricao, "fundamento": r.fundamento,
            "naturezas": _sql_lista(r.naturezas), "categorias": _sql_lista(r.categorias),
            "materiais": _sql_lista(r.materiais),
            "cessao_mao_obra": _sql_bool(r.cessao_mao_obra), "aliquota": r.aliquota,
            "base_minima_pct": r.base_minima_pct, "adicional_pct": r.adicional_pct,
            "ordem": r.ordem, "criado_por": r.criado_por, "atualizado_em": r.atualizado_em,
        }
        if r.id is None:
            r.criado_em = agora
            valores["criado_em"] = r.criado_em
            cols = list(valores)
            cur = self._conn.execute(
                f"INSERT INTO regras_inss ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [valores[c] for c in cols],
            )
            self._conn.commit()
            r.id = cur.lastrowid
            return r.id
        sets = ", ".join(f"{c} = ?" for c in valores)
        self._conn.execute(
            f"UPDATE regras_inss SET {sets} WHERE id = ?", [*valores.values(), r.id])
        self._conn.commit()
        return r.id

    def remover(self, id_: int) -> None:
        self._conn.execute("DELETE FROM regras_inss WHERE id = ?", (id_,))
        self._conn.commit()

    def fechar(self) -> None:
        self._conn.close()


def _sql_lista(v) -> str:
    return ",".join(x for x in (v or ()) if x)


def _ler_lista(v) -> tuple[str, ...]:
    if not v:
        return ()
    return tuple(x for x in (p.strip() for p in v.split(",")) if x)


def _sql_bool(v) -> int:
    return 1 if v else 0


def _ler_bool(v) -> bool:
    if v in (None, ""):
        return False
    try:
        return bool(int(v))
    except (TypeError, ValueError):
        return bool(v)
