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
from pathlib import Path
from typing import Any

from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "notas.sqlite"


class ConflitoDeChave(Exception):
    """A mesma nota (chave) já consta em OUTRA NPP. Não se sobrescreve nem se move em
    silêncio (I-1/I-6) — a rota mostra "já consta na NPP nº X" e o humano decide."""

    def __init__(self, chave: str, npp_id_existente: int) -> None:
        self.chave = chave
        self.npp_id_existente = npp_id_existente
        super().__init__(f"chave {chave} já consta na NPP {npp_id_existente}")


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
        # npp_id: vínculo da nota à NPP (uma nota = uma NPP).
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notas (
                chave        TEXT PRIMARY KEY,
                tipo         TEXT NOT NULL,        -- 'NFE' ou 'NFSE'
                origem       TEXT,                 -- nome do arquivo de origem
                dados_json   TEXT NOT NULL,        -- asdict do registro extraído
                npp_id       INTEGER,              -- NPP a que a nota pertence (FK lógica)
                importado_em TEXT NOT NULL         -- ISO-8601 UTC
            )
            """
        )
        self._migrar_colunas()
        self._conn.commit()

    def _migrar_colunas(self) -> None:
        """Adiciona `npp_id` num banco criado por versão anterior — o CREATE TABLE IF NOT
        EXISTS não altera tabela já existente. Não migrar deixaria o vínculo sem onde
        gravar (I-6, falha silenciosa)."""
        existentes = {r["name"] for r in self._conn.execute("PRAGMA table_info(notas)")}
        if "npp_id" not in existentes:
            self._conn.execute("ALTER TABLE notas ADD COLUMN npp_id INTEGER")

    def salvar(self, chave: str, tipo: str, dados: dict, origem: str = "",
               npp_id: int | None = None) -> None:
        """Insere/atualiza uma nota dentro de uma NPP. Reimportar a mesma chave na MESMA
        NPP (ou sem vínculo) é idempotente (REPLACE). Reimportar uma chave já vinculada a
        OUTRA NPP levanta `ConflitoDeChave` — não sobrescreve nem move em silêncio (I-1/I-6)."""
        row = self._conn.execute("SELECT npp_id FROM notas WHERE chave = ?", (chave,)).fetchone()
        if row is not None:
            existente = row["npp_id"]
            if existente is not None and npp_id is not None and existente != npp_id:
                raise ConflitoDeChave(chave, existente)
        self._conn.execute(
            "INSERT OR REPLACE INTO notas (chave, tipo, origem, dados_json, npp_id, importado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chave, tipo, origem, json.dumps(dados, ensure_ascii=False), npp_id,
             agora_maquina().isoformat()),
        )
        self._conn.commit()

    def _do_row(self, r: sqlite3.Row) -> dict:
        return {"chave": r["chave"], "tipo": r["tipo"], "origem": r["origem"],
                "npp_id": r["npp_id"], "importado_em": r["importado_em"],
                "dados": json.loads(r["dados_json"])}

    def listar(self) -> list[dict]:
        """Notas importadas, mais recentes primeiro. Cada item traz `dados` já
        desserializado (o dict do registro plano) e o `npp_id` de vínculo."""
        cur = self._conn.execute(
            "SELECT chave, tipo, origem, dados_json, npp_id, importado_em FROM notas "
            "ORDER BY importado_em DESC, chave"
        )
        return [self._do_row(r) for r in cur.fetchall()]

    def listar_por_npp(self, npp_id: int) -> list[dict]:
        """Notas vinculadas a uma NPP (as 'Documentos de origem' da tela)."""
        cur = self._conn.execute(
            "SELECT chave, tipo, origem, dados_json, npp_id, importado_em FROM notas "
            "WHERE npp_id = ? ORDER BY importado_em DESC, chave",
            (npp_id,),
        )
        return [self._do_row(r) for r in cur.fetchall()]

    def contar(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM notas").fetchone()[0]

    def fechar(self) -> None:
        self._conn.close()
