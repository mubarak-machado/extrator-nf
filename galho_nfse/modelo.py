"""
Registro plano da NFS-e de serviço (galho NFS-e, Fase 1).

Uma nota = uma linha. Retenções federais guardadas COMO DESTACADAS (I-2).

Caso especial — material aplicado (00_PRINCIPIOS):
- `discriminacao` é texto livre não padronizado. É o ÚNICO ponto não estruturado.
- A Fase 1 EXIBE esse texto sinalizado e deixa o usuário MARCAR se houve emprego
  de material. NÃO interpreta, não extrai valor, não decide alíquota.
- `material_marcado` e `material_marcado_por`/`_em` são o registro persistido da
  marcação humana (semente do I-4). Começam vazios; a tela os preenche.
- Nenhuma palavra-chave/heurística aqui de propósito: classificar por dicionário
  é "versão futura" (00), só depois de ver dados reais. Por ora: exibir + marcar.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class RegistroNFSe:
    # --- Identificação ---
    chave: str                      # id único da NFS-e — chave de idempotência (I-1)
    numero: str | None = None
    codigo_verificacao: str | None = None
    data_emissao: str | None = None
    competencia: str | None = None              # dCompet — mês de competência (consolidação)
    municipio_nome: str | None = None           # xLocPrestacao — "Betim/MG" (consolidação)

    # --- Prestador ---
    prest_cnpj: str | None = None
    prest_nome: str | None = None
    prest_im: str | None = None
    prest_optante_simples: bool | None = None  # opSimpNac (decisivo p/ Fase 2)
    prest_municipio: str | None = None

    # --- Tomador (o órgão) ---
    toma_cnpj: str | None = None
    toma_nome: str | None = None

    # --- Serviço (decisivo p/ Fase 2; aqui só transcrito) ---
    discriminacao: str | None = None            # TEXTO LIVRE — ver caso especial
    codigo_servico: str | None = None           # cTribNac / lista LC 116
    local_prestacao: str | None = None
    local_prestador: str | None = None

    # --- Valores e retenções COMO DESTACADAS (não é apuração — I-2) ---
    valor_servicos: str | None = None
    deducoes: str | None = None
    base_calculo: str | None = None
    iss_aliquota_destaque_emitente: str | None = None
    iss_valor_destaque_emitente: str | None = None
    iss_retido_destaque_emitente: str | None = None
    ir_destaque_emitente: str | None = None
    pis_destaque_emitente: str | None = None
    cofins_destaque_emitente: str | None = None
    csll_destaque_emitente: str | None = None
    inss_destaque_emitente: str | None = None
    valor_liquido: str | None = None

    # --- Caso especial: material aplicado (I-4 / I-6) ---
    material_aviso: str = "Pode conter valor de material aplicado — confira a discriminação."
    material_marcado: str | None = None         # None = não conferido; "sim"/"nao"
    material_marcado_por: str | None = None
    material_marcado_em: str | None = None

    # --- Meta de qualidade (I-6) ---
    campos_faltantes: list[str] = field(default_factory=list)

    tipo: str = "NFSE"

    def to_dict(self) -> dict:
        return asdict(self)

    COLUNAS = [
        "tipo", "chave", "numero", "codigo_verificacao", "data_emissao",
        "competencia", "municipio_nome",
        "prest_cnpj", "prest_nome", "prest_im", "prest_optante_simples",
        "prest_municipio", "toma_cnpj", "toma_nome", "discriminacao",
        "codigo_servico", "local_prestacao", "local_prestador", "valor_servicos",
        "deducoes", "base_calculo", "iss_aliquota_destaque_emitente",
        "iss_valor_destaque_emitente", "iss_retido_destaque_emitente",
        "ir_destaque_emitente", "pis_destaque_emitente", "cofins_destaque_emitente",
        "csll_destaque_emitente", "inss_destaque_emitente", "valor_liquido",
        "material_marcado", "material_marcado_por", "material_marcado_em",
        "campos_faltantes",
    ]

    def linha_export(self) -> list:
        d = self.to_dict()
        return [
            ";".join(d["campos_faltantes"]) if c == "campos_faltantes" else d.get(c)
            for c in self.COLUNAS
        ]
