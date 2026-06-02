"""
Redefinição dos dados — reset de demonstração ao estado inicial.

Apaga as memórias persistentes que o sistema acumula: notas importadas, o registro de
idempotência (I-1), as marcações de material (I-4), as **NPPs** e as **validações de
retenção** do operador (I-4). Tudo isso é dado de uso/teste, recriável; a identidade do
operador (`operador.sqlite`) e a configuração (contratos, catálogo de regras) **não** são
tocadas — não constam na lista de bancos a zerar.

Por que isto convive com I-1 e I-4 (memórias que existem justamente para não se
perder): a operação é de demonstração e cercada de barreiras. Como prática contra
deleção acidental e contra destruição silenciosa (I-6):

- antes de apagar, cada banco é COPIADO para `backups/<carimbo>/` — a memória
  apagada continua recuperável e auditável, não some de verdade;
- a função relata exatamente o que apagou e onde ficou o backup;
- quem chama (a rota) exige uma frase de confirmação digitada e método POST.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from tronco.idempotencia import CAMINHO_PADRAO as BD_EXPORTACAO
from tronco.marcacoes import CAMINHO_PADRAO as BD_MARCACOES
from tronco.notas import CAMINHO_PADRAO as BD_NOTAS
from tronco.npp import CAMINHO_PADRAO as BD_NPPS
from tronco.validacao_retencao import CAMINHO_PADRAO as BD_VALIDACOES

# Frase que o usuário precisa digitar para confirmar. Exigir transcrição exata é
# uma barreira deliberada: um clique distraído não basta para apagar dados.
FRASE_CONFIRMACAO = "REDEFINIR"

# Bancos do tronco que a redefinição zera: notas importadas (o vínculo `npp_id` vai
# junto), registro de exportação, marcações, NPPs e validações de retenção. Ordem só
# afeta onde fica a pasta de backup (irmã do primeiro banco). Redefinir esvazia tudo;
# reimportar é manual depois. NÃO inclui `operador.sqlite` (identidade da máquina,
# decisão do humano) nem a configuração (contratos / catálogo de regras).
BANCOS_PADRAO: tuple[Path, ...] = (BD_NOTAS, BD_EXPORTACAO, BD_MARCACOES,
                                   BD_NPPS, BD_VALIDACOES)

# Pastas cujo conteúdo é arquivado e limpo no reset. `exportacoes/` guarda os
# artefatos de lote (CSV). Limpá-los no reset é uma decisão consciente da
# demonstração: I-5 diz que o artefato é imutável e append-only, então não
# editamos nem reescrevemos — apenas ARQUIVAMOS o lote inteiro no backup datado
# antes de remover, mantendo-o recuperável e auditável.
PASTA_EXPORTACOES = Path(__file__).resolve().parent.parent / "exportacoes"
PASTAS_PADRAO: tuple[Path, ...] = (PASTA_EXPORTACOES,)


def redefinir_dados(bancos: tuple[Path, ...] = BANCOS_PADRAO,
                    pastas: tuple[Path, ...] = PASTAS_PADRAO,
                    pasta_backup: str | Path | None = None) -> dict:
    """Faz backup datado e apaga os bancos + esvazia as pastas de artefatos.

    Cada banco existente é copiado para `backups/<carimbo>/` e só então removido;
    a próxima conexão recria a tabela vazia (CREATE TABLE IF NOT EXISTS). O
    conteúdo de cada pasta (ex.: `exportacoes/`) é copiado para
    `backups/<carimbo>/<pasta>/` e então removido — a pasta em si permanece. Itens
    inexistentes são ignorados em silêncio: redefinir o que já está limpo não é erro.

    Retorna ``{"backup": <pasta ou None>, "apagados": [nomes], "artefatos_limpos": n}``.
    """
    caminhos = [Path(b) for b in bancos]
    raiz = caminhos[0].resolve().parent if caminhos else Path.cwd()
    base = Path(pasta_backup) if pasta_backup is not None else raiz / "backups"
    destino = base / datetime.now().strftime("%Y%m%d-%H%M%S")

    def _garantir_destino() -> None:
        destino.mkdir(parents=True, exist_ok=True)

    apagados: list[str] = []
    for banco in caminhos:
        if not banco.exists():
            continue
        _garantir_destino()
        shutil.copy2(banco, destino / banco.name)   # backup antes de remover
        banco.unlink()
        apagados.append(banco.name)

    artefatos_limpos = 0
    for pasta in (Path(p) for p in pastas):
        if not pasta.is_dir():
            continue
        arquivos = [f for f in pasta.iterdir() if f.is_file()]
        if not arquivos:
            continue
        _garantir_destino()
        dest_pasta = destino / pasta.name
        dest_pasta.mkdir(parents=True, exist_ok=True)
        for arq in arquivos:
            shutil.copy2(arq, dest_pasta / arq.name)  # arquiva o lote (I-5: não edita, só move)
            arq.unlink()
            artefatos_limpos += 1

    houve = bool(apagados) or artefatos_limpos > 0
    return {"backup": str(destino) if houve else None,
            "apagados": apagados, "artefatos_limpos": artefatos_limpos}
