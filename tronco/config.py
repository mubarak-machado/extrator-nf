"""
Configuração de ambiente — onde ficam os RECURSOS e onde ficam os DADOS.

Ao empacotar com PyInstaller esses dois lugares deixam de coincidir, e tratá-los
igual quebra o app distribuído:

- **recursos** (templates / static / exemplos): só leitura, vivem junto do código.
  No executável são extraídos para uma pasta temporária (``sys._MEIPASS``), apagada
  a cada execução — nada gravável pode morar aí.
- **dados** (os ``*.sqlite`` e as exportações): precisam de um lugar **gravável e
  persistente**, que sobreviva à troca do binário por uma versão nova. No executável
  **não** pode ser ao lado do .exe (pode estar em pasta só-leitura, e a atualização
  apagaria os dados) — vai para a pasta de dados do usuário no SO.

Em desenvolvimento (rodando do código-fonte, não empacotado), tudo continua na raiz
do repositório — idêntico ao comportamento anterior, e compatível com os testes (que
passam caminhos explícitos para os stores).

Overrides por ambiente:
- ``EXTRATOR_NF_DATA``  — força o diretório de dados (backup, pen drive, testes);
- ``EXTRATOR_NF_SECRET``— secret key do Flask (senão é gerada e guardada nos dados);
- ``EXTRATOR_NF_DEBUG`` — liga o debug do Flask (nunca ligado por padrão).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_RAIZ_REPO = Path(__file__).resolve().parent.parent


def empacotado() -> bool:
    """True quando rodando como executável PyInstaller (atributo que ele injeta)."""
    return bool(getattr(sys, "frozen", False))


def raiz_recursos() -> Path:
    """Diretório dos recursos só-leitura (templates, static, exemplos): pasta de
    extração (``sys._MEIPASS``) no executável; raiz do repositório em dev."""
    if empacotado():
        return Path(getattr(sys, "_MEIPASS", _RAIZ_REPO))
    return _RAIZ_REPO


def _dados_do_so() -> Path:
    """Pasta de dados por usuário, conforme o SO (sem dependência externa)."""
    if sys.platform.startswith("win"):
        raiz = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(raiz) / "ExtratorNF"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ExtratorNF"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "extrator-nf"


def diretorio_dados() -> Path:
    """Diretório gravável e persistente dos dados, criado se não existir. Ordem:
    ``EXTRATOR_NF_DATA`` > (empacotado) pasta do SO > (dev) raiz do repositório."""
    env = os.environ.get("EXTRATOR_NF_DATA")
    if env:
        base = Path(env)
    elif empacotado():
        base = _dados_do_so()
    else:
        base = _RAIZ_REPO
    base.mkdir(parents=True, exist_ok=True)
    return base


def caminho_dado(nome: str) -> Path:
    """Caminho de um arquivo de dado (ex.: ``'notas.sqlite'``) no diretório de dados."""
    return diretorio_dados() / nome


def chave_secreta() -> str:
    """Secret key do Flask: do ambiente, ou gerada uma vez e guardada no diretório de
    dados — nunca fixa no código. App local de um usuário; serve a sessão/flash."""
    env = os.environ.get("EXTRATOR_NF_SECRET")
    if env:
        return env
    arq = diretorio_dados() / "secret.key"
    if arq.exists():
        return arq.read_text(encoding="utf-8").strip()
    import secrets
    chave = secrets.token_hex(32)
    try:
        arq.write_text(chave, encoding="utf-8")
    except OSError:
        pass  # sem persistir, vale para esta execução (I-6: não quebra por isso)
    return chave


def debug_ativo() -> bool:
    """Debug do Flask só quando explicitamente pedido (``EXTRATOR_NF_DEBUG=1``).
    Num app distribuído fica desligado — o debugger do Werkzeug executa código."""
    return os.environ.get("EXTRATOR_NF_DEBUG", "").strip().lower() in ("1", "true", "sim")
