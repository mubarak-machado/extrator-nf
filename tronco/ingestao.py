"""
Ingestão — porta de entrada do tronco (etapa 1 do 02_MAPA).

Lê um XML, identifica se é NF-e ou NFS-e pelo elemento-raiz, e roteia para o
extrator do galho certo. Não faz nada tributário (I-2).

Identificação por raiz (sem depender de extensão de arquivo):
  - nfeProc / NFe ............ NF-e (mercantil)
  - NFSe ..................... NFS-e (serviço, padrão nacional emitido)

Layouts municipais antigos de NFS-e (Abrasf/Ginfes/Betha) NÃO são tratados aqui:
decisão de escopo do MVP (só padrão nacional, via nfelib). Um XML não reconhecido
não é "engolido" — vira ResultadoIngestao com erro visível (I-6).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ResultadoIngestao:
    tipo: str | None            # "NFE", "NFSE" ou None
    registro: Any = None        # RegistroNFe | RegistroNFSe | None
    origem: str = ""            # nome do arquivo
    erro: str | None = None     # mensagem legível se algo falhou (I-6)


def _localname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def identificar_tipo(caminho_xml: str | Path) -> str | None:
    try:
        raiz = ET.parse(str(caminho_xml)).getroot()
    except ET.ParseError:
        return None
    nome = _localname(raiz.tag)
    if nome in ("nfeProc", "NFe"):
        return "NFE"
    if nome in ("NFSe", "nfseProc"):
        return "NFSE"
    return None


def ingerir(caminho_xml: str | Path) -> ResultadoIngestao:
    caminho = Path(caminho_xml)
    origem = caminho.name
    tipo = identificar_tipo(caminho)

    if tipo is None:
        return ResultadoIngestao(
            tipo=None, origem=origem,
            erro="XML não reconhecido como NF-e ou NFS-e (padrão nacional). "
                 "Layouts municipais antigos estão fora do escopo do MVP.",
        )

    try:
        if tipo == "NFE":
            from nfelib.nfe.bindings.v4_0.proc_nfe_v4_00 import NfeProc
            from nfelib.nfe.bindings.v4_0.nfe_v4_00 import Nfe
            from galho_nfe.extracao import extrair_nfe
            raiz_nome = _localname(ET.parse(str(caminho)).getroot().tag)
            if raiz_nome == "nfeProc":
                inf = NfeProc.from_path(str(caminho)).NFe.infNFe
            else:
                inf = Nfe.from_path(str(caminho)).infNFe
            reg = extrair_nfe(inf)
        else:  # NFSE
            from nfelib.nfse.bindings.v1_0.nfse_v1_00 import Nfse
            from galho_nfse.extracao import extrair_nfse
            inf = Nfse.from_path(str(caminho)).infNFSe
            reg = extrair_nfse(inf)
    except Exception as exc:  # qualquer falha de parse vira erro visível, não silêncio
        return ResultadoIngestao(tipo=tipo, origem=origem,
                                 erro=f"Falha ao ler o XML ({type(exc).__name__}): {exc}")

    if not reg.chave:
        return ResultadoIngestao(
            tipo=tipo, registro=reg, origem=origem,
            erro="Nota sem chave de acesso — não pode entrar em lote sem violar I-1.",
        )
    return ResultadoIngestao(tipo=tipo, registro=reg, origem=origem)


def ingerir_pasta(pasta: str | Path) -> list[ResultadoIngestao]:
    pasta = Path(pasta)
    arquivos = sorted(p for p in pasta.glob("*.xml"))
    return [ingerir(p) for p in arquivos]
