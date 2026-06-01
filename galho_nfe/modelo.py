"""
Registro plano da NF-e mercantil (galho NF-e, Fase 1).

Uma nota = uma linha (01_ARQUITETURA §3/§4): só campos de cabeçalho, escalares,
sem itens nem parcelas. Os tributos são guardados COMO DESTACADOS pelo emitente
— o nome do campo carrega esse rótulo de procedência (`_destaque_emitente`) para
deixar inequívoco que NÃO é apuração (I-2). A Fase 2, quando existir, encaixa
`_sugestao_regra` por cima sem ambiguidade.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class RegistroNFe:
    # --- Identificação ---
    chave: str                      # 44 dígitos — chave de idempotência (I-1)
    numero: str | None = None
    serie: str | None = None
    modelo: str | None = None       # 55 ou 65
    data_emissao: str | None = None
    natureza_operacao: str | None = None

    # --- Emitente ---
    emit_cnpj: str | None = None
    emit_nome: str | None = None
    emit_optante_simples: bool | None = None  # derivado de CRT==1 (decisivo p/ Fase 2)
    emit_crt: str | None = None               # valor cru do CRT, p/ rastreio
    emit_uf: str | None = None
    emit_municipio: str | None = None

    # --- Destinatário (o órgão) ---
    dest_cnpj: str | None = None
    dest_nome: str | None = None

    # --- Valores totais ---
    valor_total: str | None = None
    valor_produtos: str | None = None
    valor_desconto: str | None = None
    valor_outras_despesas: str | None = None

    # --- Tributos COMO DESTACADOS pelo emitente (não é apuração — I-2) ---
    icms_destaque_emitente: str | None = None
    ipi_destaque_emitente: str | None = None
    pis_destaque_emitente: str | None = None
    cofins_destaque_emitente: str | None = None
    trib_aprox_destaque_emitente: str | None = None

    # --- Meta de qualidade (I-6) ---
    campos_faltantes: list[str] = field(default_factory=list)

    tipo: str = "NFE"

    def to_dict(self) -> dict:
        return asdict(self)

    # Especificação de exportação (append-only, I-5), orientada ao lançamento no
    # SIAFI: (campo, cabeçalho humano, formato). O exportador monta o cabeçalho e
    # formata cada coluna reusando tronco.formato (apresentação, não apuração —
    # I-2). Retenções rotuladas "(destaque do emitente)". "Campos a conferir"
    # mantém a ausência visível (I-6).
    EXPORT_SPEC = [
        ("chave", "Chave de acesso", "cru"),
        ("numero", "Número", "texto"),
        ("serie", "Série", "texto"),
        ("modelo", "Modelo", "texto"),
        ("data_emissao", "Emissão", "data"),
        ("natureza_operacao", "Natureza da operação", "texto"),
        ("emit_cnpj", "CNPJ do emitente", "cnpj"),
        ("emit_nome", "Emitente (fornecedor)", "texto"),
        ("emit_optante_simples", "Optante Simples", "simnao"),
        ("dest_cnpj", "CNPJ do destinatário (órgão)", "cnpj"),
        ("dest_nome", "Destinatário (órgão)", "texto"),
        ("valor_total", "Valor total da nota", "moeda"),
        ("valor_produtos", "Valor dos produtos", "moeda"),
        ("valor_desconto", "Desconto", "moeda"),
        ("trib_aprox_destaque_emitente", "Tributos aprox. (destaque do emitente)", "moeda"),
        ("icms_destaque_emitente", "ICMS (destaque do emitente)", "moeda"),
        ("ipi_destaque_emitente", "IPI (destaque do emitente)", "moeda"),
        ("pis_destaque_emitente", "PIS (destaque do emitente)", "moeda"),
        ("cofins_destaque_emitente", "COFINS (destaque do emitente)", "moeda"),
        ("campos_faltantes", "Campos a conferir", "faltantes"),
    ]
