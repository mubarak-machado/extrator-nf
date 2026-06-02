# -*- mode: python ; coding: utf-8 -*-
"""
Spec do PyInstaller — gera o executável de duplo-clique (Windows: ExtratorNF.exe).

Build (no Windows, onde o .exe é gerado — PyInstaller não faz cross-compile):
    uv sync --group empacotamento
    uv run pyinstaller extrator-nf.spec
Saída: dist/ExtratorNF.exe (onefile).

- datas: recursos só-leitura embutidos (templates/static/exemplos). Em runtime o
  app os lê de sys._MEIPASS via tronco.config.raiz_recursos().
- collect_all('nfelib'/'xsdata'): os bindings da nfelib são gerados e carregados de
  forma ampla; coletamos submódulos + dados de schema para nada faltar no exe.
- console=True: mantém a janelinha "rodando — feche para encerrar".
Os dados do usuário (*.sqlite, exportações) NÃO entram aqui — vão para a pasta de
dados do SO em runtime (tronco.config.diretorio_dados()).
"""
from PyInstaller.utils.hooks import collect_all

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("exemplos", "exemplos"),
]
binaries = []
hiddenimports = ["waitress"]

for _pacote in ("nfelib", "xsdata"):
    _d, _b, _h = collect_all(_pacote)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# onefile: binaries + datas embutidos no próprio EXE (sem COLLECT separado).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ExtratorNF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
