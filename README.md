# Extrator NF — MVP (prova de conceito)

Demonstra a **viabilidade** do sistema descrito em `docs/00..02`: ler o XML de
notas fiscais (NF-e mercantil e NFS-e nacional de serviço), extrair fielmente os
campos de lançamento, exibir para conferência, marcar material aplicado e
exportar um lote idempotente.

> **Escopo deste MVP = Fase 1.** Não há apuração de retenção (Fase 2). Os valores
> tributários exibidos são **o que o emitente destacou**, nunca uma decisão do
> sistema. É uma prova de conceito local (sandbox), não software de produção.

## O que já funciona

- **Tronco:** ingestão de XML, identificação de tipo (NF-e/NFS-e), idempotência
  por chave (SQLite), tela de conferência (Flask), exportação plugável.
- **Galho NF-e (Fase 1):** extração dos campos de cabeçalho via `nfelib`.
- **Galho NFS-e (Fase 1):** idem, mais a exibição da discriminação (texto livre)
  e a marcação humana de material aplicado.

## Como rodar (com `uv`)

O projeto traz um `pyproject.toml`. Com [`uv`](https://docs.astral.sh/uv/) você
**não toca no Python do sistema** nem precisa ativar venv: o `uv` cria e gerencia
um `.venv` isolado automaticamente.

```bash
uv run python -m tronco.app     # cria o .venv (1ª vez), instala deps e sobe em http://localhost:5000
uv run pytest                   # roda os testes no mesmo ambiente isolado
```

Se preferir materializar o ambiente antes (opcional), `uv sync` cria o `.venv` e
instala tudo; depois `uv run ...` reaproveita. Para produção sem as deps de teste:
`uv sync --no-dev`.

> O `requirements.txt` no projeto é apenas um **espelho das dependências para
> consulta** (e para ferramentas que o leiam). A fonte de verdade é o
> `pyproject.toml`/`uv.lock`; o fluxo suportado é via `uv`.

Na tela: confira as notas, abra uma NFS-e para marcar material aplicado, e use
"Exportar lote". Os artefatos saem em `exportacoes/` (um CSV novo por lote/tipo).

Os XMLs em `exemplos/` são: uma NF-e real (sample da `nfelib`, com destinatário
estrangeiro **sem CNPJ** — bom para ver o aviso de campo faltante) e duas NFS-e
nacionais sintéticas (uma cita material na discriminação; a outra é de optante
pelo Simples). Substitua por XMLs reais quando chegarem; nada no código depende
desses exemplos específicos.

## Mapa de invariantes (onde cada um vive no código)

| Invariante | Onde | Como |
|---|---|---|
| **I-1** idempotência | `tronco/idempotencia.py`, `app.exportar` | chave = PRIMARY KEY; filtra antes; grava só após sucesso |
| **I-2** extração fiel | `galho_*/extracao.py` | só transcreve; tributos como `_destaque_emitente` |
| **I-4** marcação rastreável | `tronco/marcacoes.py` | persiste valor + autor + data; histórico append |
| **I-5** planilha nova | `tronco/exportador.py` | artefato novo por lote; recusa sobrescrever |
| **I-6** falha visível | `tronco/util.py`, `campos_faltantes`, `ingestao` | ausência vira aviso, nunca exceção nem chute |

## A fronteira Fase 1 / Fase 2 (importante)

Sobre **material aplicado**: este MVP **exibe** a discriminação com aviso fixo e
deixa o humano **marcar** sim/não. Não há detecção por palavra-chave de
propósito — classificar o texto é a "versão futura" do `00`, só depois de ver
dados reais. Toda apuração que **usa** essa marcação (base de INSS, alíquota de
IR 1,2% vs 4,8%) é Fase 2 e exige aprovação humana (I-3) — fora deste MVP.

## Trocar o destino de exportação (Google Sheets)

`tronco/exportador.py` define a interface `Exportador`. O MVP usa
`ExportadorCsvLocal`. Para Sheets, basta uma classe que implemente
`exportar(...)` criando uma **planilha nova** (I-5) — a regra do invariante vive
na interface, então trocar o destino não pode reintroduzir escrita em planilha
editada à mão.

## Decisões assumidas neste MVP (revisar com o humano)

- **Só NFS-e padrão nacional** (via `nfelib`). Layout municipal antigo
  (Abrasf/Ginfes/Betha) usaria outra biblioteca (`nfselib`) e fica fora.
- **Exportação local** em vez de Google Sheets real (sem credencial no sandbox).
- **Lista de campos** = ponto de partida do `01` §3; refinar contra XMLs reais.
