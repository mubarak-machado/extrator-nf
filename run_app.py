"""
Ponto de entrada do app distribuído (duplo-clique no .exe).

Sobe o servidor local em 127.0.0.1, abre o navegador padrão na tela e mantém o
processo vivo até a janela do console ser fechada. É este o alvo do PyInstaller
(ver ``extrator-nf.spec``). Em desenvolvimento também roda: ``uv run python run_app.py``.

Não expõe nada na rede: escuta só em loopback — é um app local de um usuário, sem
autenticação. Serve via waitress (WSGI de produção, puro Python) quando disponível;
sem ele, cai no servidor embutido do Flask (sem reloader).
"""
from __future__ import annotations

import socket
import threading
import webbrowser

HOST = "127.0.0.1"


def _porta_livre(preferida: int = 5000) -> int:
    """Usa a porta preferida; se estiver ocupada, deixa o SO escolher uma livre."""
    for porta in (preferida, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, porta))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferida


def main() -> None:
    # Import tardio: ao importar, tronco.app já resolve recursos/dados via tronco.config.
    from tronco.app import app

    porta = _porta_livre()
    url = f"http://{HOST}:{porta}/"
    # Abre o navegador um instante depois de o servidor começar a subir.
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print("=" * 64)
    print("  Extrator NF está rodando.")
    print(f"  Se o navegador não abrir sozinho, acesse:  {url}")
    print("  Feche esta janela para encerrar o programa.")
    print("=" * 64, flush=True)
    try:
        from waitress import serve
        serve(app, host=HOST, port=porta, threads=4)
    except ImportError:
        app.run(host=HOST, port=porta, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
