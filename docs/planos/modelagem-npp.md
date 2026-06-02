# Plano — Modelagem por NPP (Nota de Pré-Pagamento)

> **Status:** planejado e revisado; **aguardando implementação**. As 4 decisões do humano
> (seção Context) estão **travadas** — uma nova sessão pode começar a implementar direto.
> Base de código: `main` após o commit `d3314da` (catálogo de enquadramento federal).
> Esta é a cópia **versionada no git** do plano (portátil entre máquinas).
> Para retomar: ler este arquivo inteiro, conferir que as decisões ainda valem, e seguir a
> ordem de build (seções 1→5 de Design). Antes de codar, reler `docs/00_PRINCIPIOS.md` e
> declarar por escrito como cada invariante tocado é respeitado (protocolo do CLAUDE.md).

## Context

Hoje o vínculo nota↔contrato é uma **heurística frágil**: as notas são importadas soltas
(globais), agrupadas em "consolidados" por `(prest_cnpj, competencia)` calculado em tempo
de tela (`tronco/app.py::_grupos`, `_resumo_consolidacoes`, `_chaves_consolidadas`), e o
contrato é casado por CNPJ na conferência (`galho_nfse/retencao.py::casar_contratos`),
o que gera ambiguidade ("vários contratos para o mesmo prestador" → estado `varios`).

Inspirado no **Cosmos (MPU)**, queremos uma entidade explícita: a **NPP (Nota de
Pré-Pagamento)**. A NPP pertence a **um contrato** e a **uma competência**, e agrupa
**uma ou mais notas**. O vínculo passa a ser **nota → NPP → contrato** (explícito,
escolhido pelo operador), substituindo as duas heurísticas. Pode haver **várias NPPs
para o mesmo (contrato, competência)** — contratos sob demanda com notas emitidas/pagas
em momentos diferentes do mês.

**Nova jornada:** o operador **cria a NPP** (escolhe prestador/contrato + competência),
e **importa a(s) nota(s) para dentro dela**. Não existe nota solta. A distinção
"individual vs consolidada" desaparece — todo pagamento é uma NPP (com 1 ou N notas).

**Decisões do humano (já tomadas):**
1. Toda nota (NF-e e NFS-e) vive numa NPP; fim do individual/consolidado.
2. NPP = contrato + competência; `(contrato, competência)` **não** é único (várias NPPs
   permitidas no mesmo par).
3. Jornada estrita: cria NPP → importa notas dentro dela. Sem nota solta.
4. É piloto: **pode zerar o banco**; sem migração dos dados atuais.

## Invariantes tocados (protocolo CLAUDE.md / docs/00)

- **I-1 (idempotência por chave):** `chave` segue PK em `notas` — uma nota = uma linha =
  uma NPP. Importar uma chave já registrada (em qualquer NPP) é **detectado e exibido**
  ("já consta na NPP nº X"), nunca duplicado nem movido em silêncio. Exportação mantém a
  idempotência por chave (`RegistroDeExportacao`) intacta.
- **I-6 (ambiguidade visível):** a feature **remove** a maior fonte de ambiguidade (o
  casamento por CNPJ); o contrato vem da NPP, sem chute. Nova checagem visível: se o
  CNPJ da nota importada **divergir** do prestador do contrato da NPP, marca divergência
  (não bloqueia em silêncio, não aceita em silêncio).
- **I-4 (rastreável):** a NPP guarda autor e data de criação/edição. Marcação de material
  segue como está.
- **I-3 / I-2 / I-5:** inalterados. A conferência continua **sugestão** (I-3) lendo a
  extração fiel (I-2); a exportação segue criando artefato novo append-only por lote (I-5)
  — agora um lote = uma NPP.

## Design

### 1. Entidade NPP — `tronco/npp.py` (novo, espelha `tronco/contratos.py`)

```python
@dataclass
class NPP:
    contrato_id: int | None = None      # FK → contratos.id (obrigatório na criação)
    competencia: str = ""               # "AAAA-MM" (mesma forma do dCompet da nota)
    rotulo: str | None = None           # distingue NPPs do mesmo contrato/competência
    observacoes: str | None = None
    criada_por: str = "operador"        # I-4
    criada_em: str | None = None
    atualizada_em: str | None = None
    id: int | None = None
```

`StoreNPP` (SQLite `npps.sqlite`): `salvar`, `listar`, `obter`, `remover`,
`listar_por_contrato`. Mesmo padrão de `StoreContratos` (migração de colunas, audit).
**`(contrato_id, competencia)` NÃO é UNIQUE** — várias NPPs no mesmo par são válidas.
Status da NPP (aberta/exportada/vazia) é **derivado** das notas (não armazenado), como
hoje `_resumo_consolidacoes` deriva `novas`.

### 2. Vínculo nota → NPP — `tronco/notas.py`

Adicionar coluna `npp_id` à tabela `notas` (com migração no estilo
`contratos.py::_migrar_colunas`). `salvar(chave, tipo, dados, origem, npp_id)` grava o
vínculo; `listar()` devolve `npp_id`; novo `listar_por_npp(npp_id)`. A chave segue PK
(I-1). Em re-importação da mesma chave: se já existe na **mesma** NPP → idempotente; em
**outra** NPP → conflito exibido (I-1/I-6), não sobrescreve.

### 3. Jornada e rotas — `tronco/app.py`

**Novas rotas (espelham contratos/consolidados):**
- `GET /npps` — lista de NPPs (abertas e exportadas). Substitui `consolidados`.
- `GET /npps/nova`, `POST /npps` , `GET /npp/<id>/editar`, `POST /npp/<id>`,
  `POST /npp/<id>/remover` — CRUD da NPP. O form escolhe **contrato** (de
  `StoreContratos.listar()`, agrupado por prestador) + competência + rótulo.
- `GET /npp/<id>` — detalhe da NPP: cabeçalho (contrato, prestador, competência), lista
  de notas com status de conferência, botão **Importar notas para esta NPP** e botão
  **Exportar NPP**. Substitui `consolidado`.
- Importação **escopada à NPP**: `POST /npp/<id>/importar/arquivo|pasta|exemplos`
  (adapta `importar_arquivo`/`importar_pasta`/`importar_exemplos`). `_persistir` passa a
  receber `npp_id` e grava o vínculo; valida CNPJ da nota × prestador do contrato (I-6).
- `POST /npp/<id>/exportar` — exporta as notas inéditas da NPP (reusa `_exportar` +
  `RegistroDeExportacao`). Spec por tipo: `EXPORT_SPEC_CONSOLIDADO` (galho_nfse/modelo.py)
  quando a NPP é toda NFS-e; `SPEC_INDIVIDUAL` caso contenha NF-e. Artefato nomeado por NPP.

**Conferência via NPP** — `_conferencia(item)` deixa de usar `casar_contratos`: lê
`item` → `npp_id` → `StoreNPP.obter` → `contrato_id` → `StoreContratos.obter` →
`conferir_retencao(reg, contrato, material_marcado)`. Some o estado `varios`; o contrato
é sempre único. `conferir_retencao` (galho_nfse/retencao.py) fica **inalterada** — só
muda a origem do contrato.

**Remoções (substituídas pelo fluxo NPP):**
- Rotas `individuais`, `consolidados`, `consolidado`, `exportar` (individual),
  `exportar_grupo`, e a `importar` global (a importação agora é dentro da NPP).
- Funções `_grupos`, `_resumo_consolidacoes`, `_chaves_consolidadas` (heurística) e o uso
  de `casar_contratos` no fluxo.

### 4. Telas — `templates/`

- **Novas:** `npps.html` (lista, com "Nova NPP" e estado vazio — padrão já usado em
  contratos/regras), `npp_form.html` (criar/editar: seletor de contrato + competência +
  rótulo), `npp.html` (detalhe: notas da NPP + importar + exportar).
- **Ajustadas:** `importar.html` vira parcial/escopada à NPP (recebe `npp`); `detalhe.html`
  ganha breadcrumb da NPP e conferência via contrato da NPP; `hub.html` troca os cards
  individuais/consolidados por **NPPs abertas** (valor/contagem) + **Histórico**, com CTA
  "Nova NPP"; `historico.html` passa a exibir o lote junto da NPP de origem.
- **Removidas:** `individuais.html`, `consolidados.html`, `consolidado.html`.
- **Navegação (`base.html`):** o menu "Notas Fiscais → Individuais/Consolidadas" vira
  **"NPPs"** (lista). "Importar" sai da nav global (passa a ser ação dentro da NPP).

### 5. Reset do piloto — `tronco/redefinicao.py`

Incluir `npps.sqlite` na redefinição e zerar `npp_id` junto das notas. (O usuário
autorizou zerar o banco.)

### Arquivos

| Arquivo | Mudança |
|---|---|
| `tronco/npp.py` | **novo** — `NPP` + `StoreNPP` |
| `tronco/notas.py` | coluna `npp_id` + migração + `listar_por_npp` + conflito de chave entre NPPs |
| `tronco/app.py` | rotas de NPP (CRUD, importar-na-NPP, exportar-NPP), `_conferencia` via NPP, hub/nav; remove rotas/funções de individual/consolidado |
| `galho_nfse/retencao.py` | `casar_contratos` sai do fluxo (contrato vem da NPP); `conferir_retencao` inalterada |
| `tronco/redefinicao.py` | inclui `npps.sqlite` no reset |
| `templates/` | novos `npps.html`/`npp.html`/`npp_form.html`; ajusta `importar.html`/`detalhe.html`/`hub.html`/`historico.html`/`base.html`; remove `individuais/consolidados/consolidado.html` |
| `tests/test_mvp.py` | testes de NPP (CRUD, vínculo nota↔NPP, conferência via NPP, exportação por NPP, conflito de chave) + remover testes da heurística |

## Verificação

1. **Testes (`uv run pytest`)**, no estilo por invariante:
   - `StoreNPP` CRUD + audit (I-4); `(contrato, competência)` permite duplicatas.
   - Vínculo: `notas.salvar(..., npp_id)` e `listar_por_npp`; reimportar a mesma chave na
     mesma NPP é idempotente, em outra NPP é conflito (I-1).
   - Conferência via NPP: dado uma NPP com contrato, `_conferencia` devolve a conferência
     do contrato certo sem heurística; CNPJ divergente da nota é marcado (I-6).
   - Exportação por NPP: só notas inéditas entram no lote; `RegistroDeExportacao` registra;
     reexportar não duplica (I-1); artefato novo (I-5).
2. **Ponta a ponta (`uv run python -m tronco.app`)**:
   - Criar contrato (já existe) → criar **NPP** escolhendo esse contrato + competência →
     dentro da NPP, **importar** 1+ notas (de exemplos) → conferir (material + retenção
     contra o contrato da NPP) → **exportar a NPP** → ver no **Histórico**.
   - Importar uma nota cujo CNPJ diverge do prestador do contrato → ver o aviso de
     divergência (I-6). Reimportar a mesma nota → ver o aviso de duplicidade (I-1).
   - Criar duas NPPs no mesmo contrato/competência → ambas coexistem.
3. **Reset**: `redefinir` zera notas + NPPs; a lista de NPPs volta vazia.

## Fora de escopo

- Integração real com SIAFI (o Cosmos integra; aqui seguimos exportando artefato — a
  interface `Exportador` já isola o destino, I-5).
- Geração automática da NPP a partir de notas soltas (a jornada é criar-NPP-primeiro).
- INSS/ISS no catálogo de enquadramento (trabalho anterior; segue como está).
