# Capturas de tela da interface

Referência visual do redesign (contraste relevante, dado exato, acessibilidade).
Geradas a partir dos XMLs **sintéticos** de `exemplos/` — os números não saíram de
nota real (ver nota grau-POC no `CLAUDE.md`).

Cada tela em tema **claro** e **escuro** (o tema `auto` segue o sistema):

| Tela          | Claro                     | Escuro                   |
| ------------- | ------------------------- | ------------------------ |
| Lista         | `lista_light.png`         | `lista_dark.png`         |
| Detalhe NF-e  | `detalhe_nfe_light.png`   | `detalhe_nfe_dark.png`   |
| Detalhe NFS-e | `detalhe_nfse_light.png`  | `detalhe_nfse_dark.png`  |
| Consolidado   | `consolidado_light.png`   | `consolidado_dark.png`   |

Para regenerar: `uv run python -m tronco.app` e capturar as telas
(`/`, `/nota/<chave>`, `/consolidado/<cnpj>/<competencia>`).
