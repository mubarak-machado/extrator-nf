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

    # Padrão CONSOLIDADO de exportação — ESPELHA a tabela da tela (consolidado.html):
    # uma linha por NFS-e/município, mesmas colunas e ordem da tela, MAIS o "Valor
    # dos materiais" (validado pelo operador, que não aparece na tela). Append-only
    # (I-5); reusa tronco.formato (I-2). `valor_material` NÃO é campo do registro:
    # é o valor VALIDADO pelo operador (vem da marcação, I-4), injetado na exportação.
    # Retenções individualizadas, rotuladas "(destaque do emitente)" (I-2).
    EXPORT_SPEC_CONSOLIDADO = [
        ("municipio_nome", "Município", "texto"),
        ("numero", "Nº", "texto"),
        ("valor_servicos", "Valor serviços", "moeda"),
        ("valor_material", "Valor dos materiais (validado pelo operador)", "moeda"),
        ("iss_valor_destaque_emitente", "ISS (destaque do emitente)", "moeda"),
        ("ir_destaque_emitente", "IR (destaque do emitente)", "moeda"),
        ("pis_destaque_emitente", "PIS (destaque do emitente)", "moeda"),
        ("cofins_destaque_emitente", "COFINS (destaque do emitente)", "moeda"),
        ("csll_destaque_emitente", "CSLL (destaque do emitente)", "moeda"),
        ("inss_destaque_emitente", "INSS (destaque do emitente)", "moeda"),
        ("valor_liquido", "Líquido", "moeda"),
    ]
