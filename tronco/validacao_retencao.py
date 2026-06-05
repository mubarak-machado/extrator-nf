"""
Validação de retenção pelo operador — confirmar/retificar por tributo (tronco, Fase 2).

A entrada formal do projeto na Fase 2, mas só na metade de **validação humana** (I-3): o
operador **confirma** o destaque do emitente ou **retifica** para o valor correto (o
destaque pode estar equivocado na nota). É esse valor validado que alimenta o "Total
retido" e o "Valor líquido" da NPP — não o destaque cru, nem uma apuração automática.

Espelha `tronco/marcacoes.py`: registro **append-only** com autor + data (I-4); a validação
vigente é a última. Não sobrescreve o destaque do emitente (I-2, extração intocada); não
aplica regra de negócio sozinho (I-3). **Linha vermelha:** o campo de retificação NUNCA é
pré-preenchido com a sugestão da regra (isso seria o software decidir) — quem chama envia o
valor que o operador digitou ('retificado') ou confirmou a partir do destaque ('confirmado').

Tributos: IR/CSLL/COFINS/PIS (federal), INSS, ISS — os mesmos do `Achado` da conferência.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tronco import formato
from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "validacoes_retencao.sqlite"

TRIBUTOS = ("IR", "CSLL", "COFINS", "PIS", "INSS", "ISS")
ACOES = ("confirmado", "retificado")


class StoreValidacaoRetencao:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS validacoes_retencao (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chave       TEXT NOT NULL,        -- nota
                tributo     TEXT NOT NULL,        -- IR/CSLL/COFINS/PIS/INSS/ISS
                acao        TEXT NOT NULL,        -- 'confirmado' (= destaque) | 'retificado'
                valor       TEXT NOT NULL,        -- valor VALIDADO (decimal canônico X.XX)
                autor       TEXT NOT NULL,        -- identidade do operador (I-4)
                validado_em TEXT NOT NULL         -- ISO-8601 UTC
            )
            """
        )
        self._conn.commit()

    def validar(self, chave: str, tributo: str, acao: str, valor, autor: str) -> dict:
        """Grava a decisão do operador sobre um tributo da nota (append; I-4). `valor` é o
        valor validado (o destaque, se 'confirmado'; o digitado, se 'retificado'); é
        normalizado para decimal canônico. Entradas inválidas → erro visível, nada gravado."""
        if tributo not in TRIBUTOS:
            raise ValueError(f"tributo inválido: {tributo!r}")
        if acao not in ACOES:
            raise ValueError(f"ação inválida: {acao!r} (use 'confirmado' ou 'retificado')")
        val = formato.parse_valor(valor)
        if val is None:
            raise ValueError("valor da validação é obrigatório e deve ser numérico")
        autor = (autor or "").strip()
        if not autor:
            raise ValueError("autor da validação é obrigatório (I-4)")
        agora = agora_maquina().isoformat()
        self._conn.execute(
            "INSERT INTO validacoes_retencao (chave, tributo, acao, valor, autor, validado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chave, tributo, acao, val, autor, agora),
        )
        self._conn.commit()
        return {"chave": chave, "tributo": tributo, "acao": acao, "valor": val,
                "autor": autor, "validado_em": agora}

    def historico(self) -> list[dict]:
        """Todas as validações já gravadas (append-only), em ordem cronológica (id). O
        backup precisa do rastro completo para que a decisão humana que embasou um líquido
        permaneça auditável após um round-trip de snapshot (I-4)."""
        cur = self._conn.execute(
            "SELECT chave, tributo, acao, valor, autor, validado_em "
            "FROM validacoes_retencao ORDER BY id"
        )
        return [dict(r) for r in cur.fetchall()]

    def importar(self, chave: str, tributo: str, acao: str, valor: str,
                 autor: str, validado_em: str) -> bool:
        """Insere uma validação vinda de um snapshot PRESERVANDO autor e data originais
        (I-4) — diferente de `validar`, que carimba o relógio local. Idempotente: linha
        idêntica (mesma tupla) não duplica. Retorna True se inseriu, False se já existia."""
        if tributo not in TRIBUTOS:
            raise ValueError(f"tributo inválido: {tributo!r}")
        if acao not in ACOES:
            raise ValueError(f"ação inválida: {acao!r}")
        ja = self._conn.execute(
            "SELECT 1 FROM validacoes_retencao WHERE chave = ? AND tributo = ? AND acao = ? "
            "AND valor = ? AND autor = ? AND validado_em = ?",
            (chave, tributo, acao, valor, autor, validado_em),
        ).fetchone()
        if ja is not None:
            return False
        self._conn.execute(
            "INSERT INTO validacoes_retencao (chave, tributo, acao, valor, autor, validado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chave, tributo, acao, valor, autor, validado_em),
        )
        self._conn.commit()
        return True

    def atual(self, chave: str, tributo: str) -> dict | None:
        """Validação vigente (a última) para (chave, tributo), ou None se nunca validado."""
        row = self._conn.execute(
            "SELECT acao, valor, autor, validado_em FROM validacoes_retencao "
            "WHERE chave = ? AND tributo = ? ORDER BY id DESC LIMIT 1",
            (chave, tributo),
        ).fetchone()
        return dict(row) if row else None

    def atuais(self, chave: str) -> dict:
        """Mapa tributo -> validação vigente, para os tributos já validados da nota."""
        rows = self._conn.execute(
            "SELECT tributo, acao, valor, autor, validado_em FROM validacoes_retencao v "
            "WHERE chave = ? AND id = (SELECT MAX(id) FROM validacoes_retencao "
            "                          WHERE chave = v.chave AND tributo = v.tributo)",
            (chave,),
        ).fetchall()
        return {r["tributo"]: {"acao": r["acao"], "valor": r["valor"], "autor": r["autor"],
                               "validado_em": r["validado_em"]} for r in rows}

    def fechar(self) -> None:
        self._conn.close()
