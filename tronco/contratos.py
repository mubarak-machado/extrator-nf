"""
Configuração de contrato — entrada do especialista (tronco).

Aqui o operador/especialista cadastra, por contrato, os parâmetros que governam a
análise das notas e das retenções: dados do prestador (natureza jurídica, etc.) e
do contrato (categoria do serviço, previsão de material, enquadramento das
retenções declarado).

Fronteira de invariante (00_PRINCIPIOS):
- I-3: o sistema **armazena** o que o especialista dita; **não infere nem aplica**
  retenção a nota nenhuma. A apuração que usa isto é a Fase 2 (não agora).
- I-2: não toca a extração da nota; a configuração vive ao lado.
- I-4: cada contrato guarda autor e data (criação/edição), rastreável.

Os campos capturados foram destilados das INs que regem a retenção:
- IN RFB 1234/2012 (IR/CSLL/COFINS/PIS por órgão federal): dispensa p/ optante do
  Simples e pessoa física; alíquota pela natureza do bem/serviço (código de
  receita); emprego de material discriminado muda o enquadramento.
- IN RFB 2110/2022 (INSS): 11% (ou 3,5% com desoneração) em cessão de mão de obra;
  material discriminado deduz da base; sem discriminação aplica base mínima
  (50% geral / 65% limpeza hospitalar / 80% demais limpezas / 30% transporte);
  optante do Simples só retém no Anexo IV.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "contratos.sqlite"

# Vocabulários (apresentação na tela). Apenas rótulos — não decidem nada.
NATUREZAS = {
    "pessoa_fisica": "Pessoa física",
    "mei": "MEI",
    "simples": "Simples Nacional",
    "nao_optante": "PJ não optante",
}
CATEGORIAS = {
    "geral": "Serviços em geral",
    "limpeza_conservacao": "Limpeza e conservação",
    "limpeza_hospitalar": "Limpeza hospitalar",
    "vigilancia": "Vigilância e segurança",
    "construcao": "Construção civil",
    "transporte_passageiros": "Transporte de passageiros",
    "locacao_mao_obra": "Locação de mão de obra",
    "outros": "Outros",
}
MATERIAL_PREVISAO = {
    "nao": "Não há",
    "sim_discriminado": "Sim — com discriminação de valor",
    "sim_sem_discriminacao": "Sim — sem discriminação de valor",
}
# Base mínima de INSS (IN 2110/2022, art. 118) quando o material não é discriminado.
BASES_MINIMAS = {"50": "50% — serviços em geral", "65": "65% — limpeza hospitalar",
                 "80": "80% — demais limpezas", "30": "30% — transporte de passageiros"}


@dataclass
class Contrato:
    # --- Prestador ---
    prest_identificacao: str = ""
    prest_tipo_pessoa: str = "PJ"            # "PJ" | "PF"
    prest_documento: str = ""                # CNPJ/CPF só dígitos
    prest_natureza: str = "nao_optante"      # ver NATUREZAS
    prest_simples_anexo: str | None = None   # "I".."V" (relevante p/ INSS: Anexo IV)
    prest_endereco: str | None = None
    prest_municipio: str | None = None
    prest_uf: str | None = None
    prest_im: str | None = None
    # --- Contrato ---
    numero: str = ""
    ano: str = ""
    vigencia_inicio: str | None = None
    vigencia_fim: str | None = None
    objeto: str | None = None
    categoria_servico: str = "geral"         # ver CATEGORIAS
    material_previsao: str = "nao"           # ver MATERIAL_PREVISAO
    # --- Enquadramento de retenção (declarado pelo especialista — base p/ Fase 2) ---
    ret_federal_sujeito: bool = False        # IR/CSLL/COFINS/PIS (IN 1234/2012)
    ret_federal_codigo_receita: str | None = None
    inss_cessao_mao_obra: bool = False       # INSS (IN 2110/2022)
    inss_aliquota: str | None = None         # "11" | "3.5"
    inss_base_minima_pct: str | None = None  # ver BASES_MINIMAS
    iss_retido_tomador: bool = False
    iss_aliquota: str | None = None
    observacoes: str | None = None
    # --- Auditoria (I-4) ---
    criado_por: str = "operador"
    criado_em: str | None = None
    atualizado_em: str | None = None
    id: int | None = None

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


_CAMPOS = [f.name for f in fields(Contrato) if f.name != "id"]
_BOOLS = {"ret_federal_sujeito", "inss_cessao_mao_obra", "iss_retido_tomador"}


class StoreContratos:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO) -> None:
        self._conn = sqlite3.connect(str(caminho))
        self._conn.row_factory = sqlite3.Row
        colunas = ",\n                ".join(f"{c} TEXT" for c in _CAMPOS)
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS contratos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {colunas},
                UNIQUE (prest_documento, numero, ano)
            )
            """
        )
        self._conn.commit()

    def _do_row(self, row: sqlite3.Row) -> Contrato:
        d = {c: row[c] for c in _CAMPOS}
        for b in _BOOLS:
            d[b] = bool(row[b])              # SQLite guarda 0/1
        return Contrato(id=row["id"], **d)

    def salvar(self, c: Contrato) -> int:
        """Insere (id None) ou atualiza. Mantém criado_em; atualiza atualizado_em.
        A UNIQUE(documento, número, ano) impede contrato duplicado (estoura
        IntegrityError, tratado pela rota — I-6, visível)."""
        agora = datetime.now(timezone.utc).isoformat()
        c.atualizado_em = agora
        if c.id is None:
            c.criado_em = agora
            valores = [_sql(getattr(c, k)) for k in _CAMPOS]
            cur = self._conn.execute(
                f"INSERT INTO contratos ({', '.join(_CAMPOS)}) "
                f"VALUES ({', '.join('?' for _ in _CAMPOS)})",
                valores,
            )
            self._conn.commit()
            c.id = cur.lastrowid
            return c.id
        sets = ", ".join(f"{k} = ?" for k in _CAMPOS if k != "criado_em")
        valores = [_sql(getattr(c, k)) for k in _CAMPOS if k != "criado_em"]
        self._conn.execute(f"UPDATE contratos SET {sets} WHERE id = ?", [*valores, c.id])
        self._conn.commit()
        return c.id

    def listar(self) -> list[Contrato]:
        cur = self._conn.execute(
            "SELECT * FROM contratos ORDER BY prest_identificacao, ano DESC, numero")
        return [self._do_row(r) for r in cur.fetchall()]

    def obter(self, id_: int) -> Contrato | None:
        cur = self._conn.execute("SELECT * FROM contratos WHERE id = ?", (id_,))
        row = cur.fetchone()
        return self._do_row(row) if row else None

    def remover(self, id_: int) -> None:
        self._conn.execute("DELETE FROM contratos WHERE id = ?", (id_,))
        self._conn.commit()

    def fechar(self) -> None:
        self._conn.close()


def _sql(v):
    """Bool -> 0/1; resto inalterado (None vira NULL)."""
    if isinstance(v, bool):
        return 1 if v else 0
    return v
