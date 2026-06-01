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


def _tipo_de_raiz(nome: str) -> str | None:
    if nome in ("nfeProc", "NFe"):
        return "NFE"
    if nome in ("NFSe", "nfseProc"):
        return "NFSE"
    return None


def identificar_tipo(caminho_xml: str | Path) -> str | None:
    try:
        raiz = ET.parse(str(caminho_xml)).getroot()
    except ET.ParseError:
        return None
    return _tipo_de_raiz(_localname(raiz.tag))


# Assinatura digital (XMLDSig). NÃO é dado fiscal — é metadado criptográfico — e
# sua validação estrita de esquema (valores fixos de algoritmo de canonicalização)
# trava a leitura de notas REAIS na nfelib. Removê-la antes do binding não altera
# nenhum campo que extraímos (I-2: extração fiel do dado fiscal, não da assinatura).
_TAG_ASSINATURA = "{http://www.w3.org/2000/09/xmldsig#}Signature"


def _remover_assinatura(elem) -> None:
    for filho in list(elem):
        if filho.tag == _TAG_ASSINATURA:
            elem.remove(filho)
        else:
            _remover_assinatura(filho)


_parser_cache = None


def _parser():
    """XmlParser tolerante: ignora atributos/elementos desconhecidos que notas
    reais costumam trazer, em vez de abortar a nota inteira. Não fabrica dado —
    campos esperados ausentes continuam virando `campos_faltantes` na extração,
    portanto a ausência segue VISÍVEL (I-6)."""
    global _parser_cache
    if _parser_cache is None:
        from xsdata.formats.dataclass.parsers import XmlParser
        from xsdata.formats.dataclass.parsers.config import ParserConfig
        _parser_cache = XmlParser(config=ParserConfig(
            fail_on_unknown_properties=False, fail_on_unknown_attributes=False))
    return _parser_cache


def ingerir(caminho_xml: str | Path) -> ResultadoIngestao:
    caminho = Path(caminho_xml)
    origem = caminho.name

    try:
        raiz = ET.parse(str(caminho)).getroot()
    except ET.ParseError as exc:
        return ResultadoIngestao(tipo=None, origem=origem,
                                 erro=f"XML malformado ({type(exc).__name__}): {exc}")

    raiz_nome = _localname(raiz.tag)
    tipo = _tipo_de_raiz(raiz_nome)
    if tipo is None:
        return ResultadoIngestao(
            tipo=None, origem=origem,
            erro="XML não reconhecido como NF-e ou NFS-e (padrão nacional). "
                 "Layouts municipais antigos estão fora do escopo do MVP.",
        )

    # Remove a assinatura digital e serializa: a leitura é sobre o XML limpo.
    _remover_assinatura(raiz)
    xml_limpo = ET.tostring(raiz, encoding="unicode")

    try:
        if tipo == "NFE":
            from nfelib.nfe.bindings.v4_0.proc_nfe_v4_00 import NfeProc
            from nfelib.nfe.bindings.v4_0.nfe_v4_00 import Nfe
            from galho_nfe.extracao import extrair_nfe
            if raiz_nome == "nfeProc":
                inf = _parser().from_string(xml_limpo, NfeProc).NFe.infNFe
            else:
                inf = _parser().from_string(xml_limpo, Nfe).infNFe
            reg = extrair_nfe(inf)
        else:  # NFSE
            from nfelib.nfse.bindings.v1_0.nfse_v1_00 import Nfse
            from galho_nfse.extracao import extrair_nfse
            inf = _parser().from_string(xml_limpo, Nfse).infNFSe
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
