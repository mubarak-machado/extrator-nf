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

    # Colunas estáveis para exportação (append-only, I-5).
    COLUNAS = [
        "tipo", "chave", "numero", "serie", "modelo", "data_emissao",
        "natureza_operacao", "emit_cnpj", "emit_nome", "emit_optante_simples",
        "emit_crt", "emit_uf", "emit_municipio", "dest_cnpj", "dest_nome",
        "valor_total", "valor_produtos", "valor_desconto", "valor_outras_despesas",
        "icms_destaque_emitente", "ipi_destaque_emitente", "pis_destaque_emitente",
        "cofins_destaque_emitente", "trib_aprox_destaque_emitente",
        "campos_faltantes",
    ]

    def linha_export(self) -> list:
        d = self.to_dict()
        return [
            ";".join(d["campos_faltantes"]) if c == "campos_faltantes" else d.get(c)
            for c in self.COLUNAS
        ]
