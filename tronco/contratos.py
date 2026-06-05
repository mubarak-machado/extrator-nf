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
from dataclasses import dataclass, field, fields
from pathlib import Path

from tronco.util import agora as agora_maquina

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "contratos.sqlite"

# Vocabulários (apresentação na tela). Apenas rótulos — não decidem nada.
NATUREZAS = {
    "nao_optante": "PJ não optante do Simples Nacional",
    "simples": "PJ optante do Simples Nacional",
    "mei": "Microempreendedor Individual (MEI)",
    "pessoa_fisica": "Pessoa física",
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
# Percentual de IR pela natureza do bem/serviço (IN 1234/2012, Anexo I, col. 06).
IR_PERCENTUAIS = {"1.2": "1,2% — com material/empreitada", "4.8": "4,8% — serviço sem material",
                  "9.45": "9,45% — profissionais/demais", "7.05": "7,05% — transporte de passageiros",
                  "5.85": "5,85% — hospitalar", "1.5": "1,5% — mercadorias/bens"}
# Adicional de retenção para aposentadoria especial (IN 2110/2022) — sobre a alíquota base.
INSS_ADICIONAL = {"": "Sem adicional", "4": "+4% — exposição 15 anos",
                  "3": "+3% — 20 anos", "2": "+2% — 25 anos"}
# Local de incidência do ISS (LC 116/2003, art. 3º).
ISS_LOCAL = {"estabelecimento_prestador": "Estab. do prestador (regra geral)",
             "local_prestacao": "Local da prestação (exceção art. 3º)"}
# Forma de recolhimento do ISS retido — varia por município (depende do convênio).
ISS_RECOLHIMENTO = {"guia": "Guia", "dar": "DAR"}


@dataclass
class MunicipioIss:
    """Uma linha de ISS por município contemplado pelo contrato. O ISS é o único
    tributo configurado DIRETO no contrato (varia por município); o que muda de um
    para outro é a **alíquota**, **se é retido** (depende de a lei municipal nomear o
    tomador substituto tributário) e a **forma de recolhimento** (guia da prefeitura
    ou DAR via convênio SIAFI). Persistida na tabela filha `contrato_municipios`."""
    municipio: str = ""
    uf: str | None = None
    iss_aliquota: str | None = None          # 2%–5% (LC 116/2003)
    iss_retido: bool = False                 # tomador é substituto tributário neste município?
    iss_recolhimento: str | None = None      # ver ISS_RECOLHIMENTO ("guia" | "dar")
    id: int | None = None
    contrato_id: int | None = None


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
    # PGEA = processo do Sistema Único do MPF onde moram os documentos. O da
    # contratação guarda o contrato e a documentação da contratação; o da liquidação
    # é anual e junta os documentos de pagamento ao longo da execução.
    pgea_contratacao: str | None = None
    pgea_liquidacao: str | None = None
    categoria_servico: str = "geral"         # ver CATEGORIAS
    material_previsao: str = "nao"           # ver MATERIAL_PREVISAO
    # --- Enquadramento de retenção (declarado pelo especialista — base p/ Fase 2) ---
    ret_federal_sujeito: bool = False        # IR/CSLL/COFINS/PIS (IN 1234/2012)
    ret_federal_codigo_receita: str | None = None
    ret_federal_ir_pct: str | None = None    # ver IR_PERCENTUAIS
    ret_federal_csll: bool = True            # CSLL 1% incide?
    ret_federal_cofins: bool = True          # COFINS 3% incide?
    ret_federal_pis: bool = True             # PIS 0,65% incide?
    # Procedência do enquadramento federal: derivado do catálogo (galho_nfse.
    # enquadramento) ou ajustado à mão pelo operador, com justificativa (I-4).
    ret_federal_regra_codigo: str | None = None   # "TF-002" — regra que gerou
    ret_federal_origem: str = "derivado"          # "derivado" | "ajustado"
    ret_federal_justificativa: str | None = None  # obrigatória quando "ajustado" (I-6)
    ret_federal_ajustado_por: str | None = None   # autor do override (I-4)
    ret_federal_ajustado_em: str | None = None    # data ISO-8601 do override (I-4)
    # INSS (IN 2110/2022) — como o federal, vem de uma regra do catálogo selecionada
    # (origem 'derivado') ou ajustada à mão (origem 'ajustado', com justificativa). Os
    # campos abaixo guardam o EFEITO da regra escolhida (espelha os ret_federal_*).
    inss_cessao_mao_obra: bool = False       # INSS incide (cessão de mão de obra/empreitada)?
    inss_aliquota: str | None = None         # "11" | "3.5"
    inss_base_minima_pct: str | None = None  # ver BASES_MINIMAS
    inss_adicional_pct: str | None = None    # ver INSS_ADICIONAL ("4"/"3"/"2")
    inss_regra_codigo: str | None = None     # "INSS-001" — regra do catálogo que gerou
    inss_origem: str = "derivado"            # "derivado" | "ajustado"
    inss_justificativa: str | None = None    # obrigatória quando "ajustado" (I-6)
    inss_ajustado_por: str | None = None     # autor do override (I-4)
    inss_ajustado_em: str | None = None      # data ISO-8601 do override (I-4)
    # ISS (LC 116/2003) — único tributo configurado DIRETO no contrato; a alíquota,
    # o "retido" e a forma de recolhimento variam por município (ver `municipios`).
    # Os campos abaixo valem para o contrato todo (não variam por município).
    iss_subitem_lista: str | None = None     # subitem da lista LC 116 (ex. "7.02")
    iss_local_incidencia: str = "estabelecimento_prestador"  # ver ISS_LOCAL
    iss_deduz_material: bool = False         # dedução de material (subitens 7.02/7.05)
    # Escalares de ISS legados (contrato município-único, pré-multi-município). Mantidos
    # para não perder dado na migração; `linhas_iss()` os materializa quando não há
    # linhas filhas. A entrada nova passa por `municipios`.
    iss_retido_tomador: bool = False
    iss_aliquota: str | None = None
    iss_municipio: str | None = None
    observacoes: str | None = None
    # --- Auditoria (I-4) ---
    criado_por: str = "operador"
    criado_em: str | None = None
    atualizado_em: str | None = None
    id: int | None = None
    # Linhas de ISS por município (tabela filha; não é coluna — fora de _CAMPOS).
    municipios: list[MunicipioIss] = field(default_factory=list)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    def linhas_iss(self) -> list[MunicipioIss]:
        """Linhas de ISS por município. Se não houver linhas filhas mas o contrato
        legado tiver o ISS escalar marcado, materializa uma linha única — assim a
        conferência (galho NFS-e) funciona para contratos antigos sem reentrada."""
        if self.municipios:
            return self.municipios
        if self.iss_retido_tomador and self.iss_aliquota:
            return [MunicipioIss(municipio=self.iss_municipio or "",
                                 iss_aliquota=self.iss_aliquota, iss_retido=True)]
        return []


_CAMPOS = [f.name for f in fields(Contrato) if f.name not in ("id", "municipios")]
_BOOLS = {"ret_federal_sujeito", "ret_federal_csll", "ret_federal_cofins",
          "ret_federal_pis", "inss_cessao_mao_obra", "iss_retido_tomador",
          "iss_deduz_material"}
# Contribuições federais que, em contrato pré-existente, devem manter o trio 4,65%
# ao migrar o schema (sem coluna = NULL = False quebraria o histórico).
_BOOLS_DEFAULT_1 = {"ret_federal_csll", "ret_federal_cofins", "ret_federal_pis"}


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
        # Tabela filha: ISS por município (o único tributo configurado direto no
        # contrato). ON DELETE CASCADE casa com a remoção do contrato.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contrato_municipios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contrato_id INTEGER NOT NULL REFERENCES contratos(id) ON DELETE CASCADE,
                municipio TEXT,
                uf TEXT,
                iss_aliquota TEXT,
                iss_retido TEXT,
                iss_recolhimento TEXT
            )
            """
        )
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrar_colunas()
        self._conn.commit()

    def _migrar_colunas(self) -> None:
        """Adiciona colunas de `_CAMPOS` ausentes num banco já existente — o
        CREATE TABLE IF NOT EXISTS não altera tabela criada por versão anterior.
        Falha silenciosa aqui significaria campo novo não persistido (I-6)."""
        existentes = {r["name"] for r in
                      self._conn.execute("PRAGMA table_info(contratos)").fetchall()}
        for c in _CAMPOS:
            if c in existentes:
                continue
            default = " DEFAULT '1'" if c in _BOOLS_DEFAULT_1 else ""
            self._conn.execute(f"ALTER TABLE contratos ADD COLUMN {c} TEXT{default}")

    def _do_row(self, row: sqlite3.Row) -> Contrato:
        d = {c: row[c] for c in _CAMPOS}
        for b in _BOOLS:
            d[b] = _ler_bool(row[b])
        return Contrato(id=row["id"], municipios=self._municipios_de(row["id"]), **d)

    def _municipios_de(self, contrato_id) -> list[MunicipioIss]:
        cur = self._conn.execute(
            "SELECT * FROM contrato_municipios WHERE contrato_id = ? ORDER BY uf, municipio, id",
            (contrato_id,))
        return [MunicipioIss(id=r["id"], contrato_id=r["contrato_id"],
                             municipio=r["municipio"] or "", uf=r["uf"],
                             iss_aliquota=r["iss_aliquota"], iss_retido=_ler_bool(r["iss_retido"]),
                             iss_recolhimento=r["iss_recolhimento"]) for r in cur.fetchall()]

    def _gravar_municipios(self, contrato_id, municipios) -> None:
        """Regrava as linhas de ISS do contrato (delete+insert). Só persiste linhas com
        município preenchido — linha em branco do form é ignorada, não vira lixo (I-6)."""
        self._conn.execute("DELETE FROM contrato_municipios WHERE contrato_id = ?", (contrato_id,))
        for m in municipios or []:
            if not (m.municipio or "").strip():
                continue
            self._conn.execute(
                "INSERT INTO contrato_municipios "
                "(contrato_id, municipio, uf, iss_aliquota, iss_retido, iss_recolhimento) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (contrato_id, m.municipio.strip(), m.uf, m.iss_aliquota,
                 _sql(m.iss_retido), m.iss_recolhimento))

    def salvar(self, c: Contrato) -> int:
        """Insere (id None) ou atualiza. Mantém criado_em; atualiza atualizado_em.
        A UNIQUE(documento, número, ano) impede contrato duplicado (estoura
        IntegrityError, tratado pela rota — I-6, visível)."""
        agora = agora_maquina().isoformat()
        c.atualizado_em = agora
        if c.id is None:
            c.criado_em = agora
            valores = [_sql(getattr(c, k)) for k in _CAMPOS]
            cur = self._conn.execute(
                f"INSERT INTO contratos ({', '.join(_CAMPOS)}) "
                f"VALUES ({', '.join('?' for _ in _CAMPOS)})",
                valores,
            )
            c.id = cur.lastrowid
            self._gravar_municipios(c.id, c.municipios)
            self._conn.commit()
            return c.id
        sets = ", ".join(f"{k} = ?" for k in _CAMPOS if k != "criado_em")
        valores = [_sql(getattr(c, k)) for k in _CAMPOS if k != "criado_em"]
        self._conn.execute(f"UPDATE contratos SET {sets} WHERE id = ?", [*valores, c.id])
        self._gravar_municipios(c.id, c.municipios)
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

    def obter_por_chave_natural(self, prest_documento: str, numero: str,
                                ano: str) -> Contrato | None:
        """Busca pela chave natural (doc, número, ano) — a UNIQUE da tabela. É por ela
        que a NPP referencia o contrato num snapshot (o rowid local não é portátil)."""
        cur = self._conn.execute(
            "SELECT * FROM contratos WHERE prest_documento = ? AND numero = ? AND ano = ?",
            (prest_documento, numero, ano))
        row = cur.fetchone()
        return self._do_row(row) if row else None

    def remover(self, id_: int) -> None:
        # Apaga as linhas filhas explicitamente (não depender do PRAGMA da conexão).
        self._conn.execute("DELETE FROM contrato_municipios WHERE contrato_id = ?", (id_,))
        self._conn.execute("DELETE FROM contratos WHERE id = ?", (id_,))
        self._conn.commit()

    def fechar(self) -> None:
        self._conn.close()


def _sql(v):
    """Bool -> 0/1; resto inalterado (None vira NULL)."""
    if isinstance(v, bool):
        return 1 if v else 0
    return v


def _ler_bool(v) -> bool:
    """Lê um boolean de volta. A coluna é TEXT: 0/1 viram '0'/'1', e bool('0') é
    True — por isso interpretamos o numérico em vez de truncar para bool direto.
    NULL/'' (coluna nunca preenchida, ex. após migração) = False."""
    if v in (None, ""):
        return False
    try:
        return bool(int(v))
    except (TypeError, ValueError):
        return bool(v)
