# CLAUDE.md — guia de trabalho neste repositório

> Este arquivo é lido automaticamente pelo Claude Code a cada sessão. Ele resume
> **como trabalhar aqui**. A autoridade de *o que nunca pode acontecer* é o
> `docs/00_PRINCIPIOS.md` — em conflito, o `00` vence.

## O que é

Sistema que lê o **XML** de notas fiscais (NF-e mercantil e NFS-e nacional de
serviço), extrai fielmente os campos para lançamento de pagamento por órgão
público federal (MPF/DEOF-PR/MG), exibe para conferência e exporta um lote.
**O dado sustenta uma decisão de retenção tributária** — erro custa pagamento
errado, não estética.

**Escopo atual = Fase 1 (extração fiel).** Fase 2 (sugestão de retenção) está
documentada como objetivo, mas **não se constrói agora**.

Estado: começou como prova de conceito (sandbox). Caminha para uso real — trate
as partes grau-POC (ver fim deste arquivo) como provisórias.

## Protocolo NÃO negociável (antes de qualquer feature)

Isto existe porque a fronteira Fase 1 / Fase 2 é fácil de borrar. Siga nesta ordem:

1. **Releia `docs/00_PRINCIPIOS.md`.** Liste os invariantes (I-1…I-6) que a feature toca.
2. **Declare por escrito como cada invariante tocado é respeitado** — antes de codar.
3. **Confira contra `docs/01_ARQUITETURA.md`**: respeita tronco vs galho? Está na fase certa (não faz apuração na Fase 1)?
4. **Decisão em aberto?** (ver `docs/02_MAPA.md` §3 e `ESTADO_E_PROXIMOS_PASSOS.md`). Se a feature depende de uma decisão não tomada → **pergunte ao humano**, não escolha sozinho.
5. Só então: plano e código.
6. **No fim:** nenhum invariante quebrado por conveniência? Nenhuma interpretação tributária vazou para a Fase 1?

Qualquer código que **decida** algo tributário (o que reter, se houve material
aplicado) é Fase 2 e exige aprovação humana (I-3). Na dúvida: **detectar e exibir,
nunca decidir.**

## Invariantes (resumo — fonte é `docs/00`)

- **I-1** Idempotência por chave antes de exportar (duplicata = pior erro).
- **I-2** Extração fiel, nunca interpretativa, na Fase 1. Tributos vêm rotulados `_destaque_emitente`.
- **I-3** Retenção é sempre sugestão para aprovação humana (Fase 2), nunca automática.
- **I-4** Marcação humana que afeta retenção é persistida e rastreável (autor + data).
- **I-5** Exportação cria artefato novo, append-only. Nunca escreve em planilha editada à mão.
- **I-6** Falha e ambiguidade são visíveis, nunca silenciosas nem "chutadas".

## Convenções

- **Python + `uv` sempre.** `uv run python -m tronco.app` e `uv run pytest`. Nunca
  pip no Python do sistema, nunca venv manual (salvo pedido explícito). O `.venv` é
  isolado e gerenciado pelo `uv`.
- **Português** em código, comentários, UI e mensagens.
- **Uma nota = uma linha** (registro plano, sem itens/parcelas).
- **Dois galhos independentes** (NF-e / NFS-e) sobre um **tronco comum**. Não criar
  modelo unificado nem segunda leitura de XML.
- **Só NFS-e padrão nacional** (`nfelib`). Layout municipal antigo (Abrasf/Ginfes/
  Betha) usaria outra lib (`nfselib`) e está fora do escopo — decisão em aberto.

## Como rodar e testar

```bash
uv run python -m tronco.app     # sobe em http://localhost:5000
uv run pytest                   # 9 testes, organizados por invariante
```

## Mapa do repositório

```
docs/                  00/01/02 — princípios, arquitetura, mapa (AUTORIDADE)
tronco/                ingestao, idempotencia, marcacoes, exportador, formato, app (Flask), util
galho_nfe/             modelo + extracao (Fase 1)         (retencao.py = Fase 2, futuro)
galho_nfse/            modelo + extracao (Fase 1, inclui detecção de material)
templates/ static/     UI (base, lista, consolidado, detalhe; CSS/JS do design system)
exemplos/              XMLs de teste (1 NF-e real + NFS-e sintéticas, inclui 6 de serviço continuado)
tests/                 test_mvp.py (por invariante)
```

## Conhecimento caro sobre `nfelib` (não re-descobrir)

- NF-e: `nfelib.nfe.bindings.v4_0.proc_nfe_v4_00.NfeProc` → `.NFe.infNFe`. Casing
  preservado (`infNFe`, `ICMSTot`, `CNPJ`, `CRT`, `vNF`). Chave = `inf.Id` sem
  prefixo "NFe" (44 díg). Optante Simples = `CRT.value == "1"`. Enums precisam `.value`.
- NFS-e nacional: `nfelib.nfse.bindings.v1_0.nfse_v1_00.Nfse` → `.infNFSe`. DPS
  embutida em `infNFSe.DPS.infDPS`. **`vDedRed` é estrutura (`TcinfoDedRed`), o
  valor está em `vDedRed.vDR`** — não é escalar (já mordeu uma vez).
- Vários campos de valor da NFS-e são estruturas aninhadas, não escalares. Ao ligar
  XML real, varrer por campos que rendam repr de objeto (`Tc...(...)`) antes de exibir.

## Grau-POC — substituir antes de tocar em dado real

- `ExportadorCsvLocal` é stub: o destino real é planilha **nova** no Google Sheets
  (a interface `Exportador` já isola isso — I-5 vive na interface, não no destino).
- `secret_key` do Flask está fixa no código.
- `debug=True` no `app.run`.
- XMLs de `exemplos/` são sintéticos (os de serviço continuado têm valores
  fabricados); os números **não** saíram de nota real.
- SQLite mora no próprio repo; definir local/backup para uso real.
- Fontes via CDN (Google Fonts) — empacotar localmente se precisar rodar offline.
- Sem autenticação/controle de acesso (POC local de um usuário).
