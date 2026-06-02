# Plano — Modelagem por NPP (Nota de Pré-Pagamento)

> **Status:** planejado e revisado; **aguardando implementação**. As decisões do humano
> (seção Context) estão **travadas** — uma nova sessão pode começar a implementar direto.
> Base de código: `main` após o commit `d3314da` (catálogo de enquadramento federal).
> Esta é a cópia **versionada no git** do plano (portátil entre máquinas).
> Para retomar: ler este arquivo inteiro, conferir que as decisões ainda valem, e seguir a
> ordem de build (seções 1→7 de Design). Antes de codar, reler `docs/00_PRINCIPIOS.md` e
> declarar por escrito como cada invariante tocado é respeitado (protocolo do CLAUDE.md).
>
> **⚠️ Mudança de fase (decidida em 2026-06-02):** este plano **cruza para a Fase 2**, mas
> só na metade de **validação/aprovação humana** (I-3): o operador confirma ou retifica os
> valores de retenção (§5). Apuração/aplicação autônoma de regra **segue fora de escopo**.
> Ver `ESTADO_E_PROXIMOS_PASSOS.md` e a memória `fase2-validacao-humana`.

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

Uma NPP pode conter **tipos mistos** — NFS-e **e** NF-e juntas (um serviço que recebe
peças/componentes faturados à parte em nota mercantil). Isso muda pouco: o **bruto** é a
soma de todas as notas (serviço ou material) e o **líquido** é Σbruto − Σretenções, sejam
quais forem as retenções; as categorias de imposto só agregam o que cada nota tem.

**Nova jornada:** o operador **cria a NPP** (escolhe prestador/contrato + competência),
e **importa a(s) nota(s) para dentro dela**. Não existe nota solta. A distinção
"individual vs consolidada" desaparece — todo pagamento é uma NPP (com 1 ou N notas).

**A tela da NPP espelha (simplificada) a do Cosmos:** um **cabeçalho** com os campos que
*já temos* (e só eles — ver §3) e as duas "abas" do Cosmos, que aqui renderizamos como
**duas seções empilhadas** (ver §4):
1. **Documentos de origem** — a(s) nota(s) fiscal(is) importada(s) na NPP.
2. **Grupos de impostos** — os tributos organizados por categoria (Contribuição
   previdenciária / Tributos federais / ISS).

O Cosmos traz dezenas de campos de pagamento (Nº do Processo, glosa, recolhimento
patronal, banco/agência/conta, OB, datas de atesto/liquidação, código do vínculo, tipo
de documento hábil Siafi…). **Nada disso entra**: é mundo SIAFI, fora do nosso escopo.
Só replicamos o que o nosso código já produz.

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
- **I-2 / I-3 (a seção "Grupos de impostos" é a fronteira sensível — ler §4 e §5):** a
  seção tem **três camadas explicitamente separadas e rotuladas**:
  - *Camada Fase 1 (sempre):* o **destaque do emitente** somado por tributo — transcrição
    fiel (I-2), reusa `_soma`. Rótulo "destacado pelo emitente". É aritmética sobre o que
    a nota declarou, **não** apuração. **Nunca é sobrescrito.**
  - *Camada sugestão (Fase 2, só exibição):* o `esperado` da regra (federal via
    `tronco/retencao_federal.py`; INSS/ISS no `galho_nfse`). Rótulo "sugestão para
    conferência humana" (I-3); **o software nunca a grava nem a adota sozinho** — nem
    pré-preenche a retificação com ela (linha vermelha, §5).
  - *Camada validação humana (Fase 2 — a que entra agora; §5):* o operador **confirma ou
    retifica** o valor; essa decisão **é gravada** com autor + data (I-4), em store
    separado. É o **único** valor que o sistema grava como retenção — e só por ação
    explícita do humano (I-3). Alimenta o "Total retido"/"Líquido".
- **I-6 (ambiguidade visível):** a feature **remove** a maior fonte de ambiguidade (o
  casamento por CNPJ); o contrato vem da NPP, sem chute. Checagens visíveis novas:
  (a) se o CNPJ da nota importada **divergir** do prestador do contrato da NPP, marca
  divergência; (b) **NF-e e NFS-e seguem o mesmo fluxo de validação, mudando só quais
  tributos aplicam** (ver §4-Seção 2): a NF-e tem o **bloco federal** (IR/CSLL/COFINS/PIS,
  IN 1234/2012) sujeito a retenção quando o fornecedor **não** é optante do Simples; é
  **dispensado** quando optante (LC 123/2006); **INSS e ISS não se aplicam à NF-e**. O
  gatilho (optante do Simples) já vem da Fase 1 (`emit_optante_simples`/CRT==1). Tributo
  aplicável e não validado → `indefinido` visível; tributo que não se aplica → marcado
  "não se aplica", nunca em branco ambíguo.
- **I-4 (rastreável):** a NPP guarda autor e data de criação/edição; a **validação de
  retenção** do operador é persistida com autor + data (store próprio, append — §5),
  generalizando o padrão de `tronco/marcacoes.py`. Marcação de material segue como está.
- **I-5:** inalterado. A exportação segue criando artefato novo append-only por lote —
  agora um lote = uma NPP.

## Design

### 1. Entidade NPP — `tronco/npp.py` (novo, espelha `tronco/contratos.py`)

```python
@dataclass
class NPP:
    numero: str = ""                    # NPP_IO_YYYYMMDD_XXXX — id estável e portátil (ver abaixo)
    contrato_id: int | None = None      # FK → contratos.id (obrigatório na criação)
    competencia: str = ""               # "AAAA-MM" (mesma forma do dCompet da nota)
    rotulo: str | None = None           # rótulo humano opcional (o `numero` já desambigua)
    observacoes: str | None = None
    criada_por: str = "operador"        # I-4 (alimentado pelas iniciais do operador, ver abaixo)
    criada_em: str | None = None
    atualizada_em: str | None = None
    id: int | None = None
```

`StoreNPP` (SQLite `npps.sqlite`): `salvar`, `listar`, `obter`, `remover`,
`listar_por_contrato`. Mesmo padrão de `StoreContratos` (migração de colunas, audit).
**`(contrato_id, competencia)` NÃO é UNIQUE** — várias NPPs no mesmo par são válidas.
Status da NPP (aberta/exportada/vazia) é **derivado** das notas (não armazenado), como
hoje `_resumo_consolidacoes` deriva `novas`.

**Número da NPP — `numero` (gerado e gravado na criação; NÃO derivado).** Formato
`NPP_<IniciaisDoOperador>_<YYYYMMDD>_<XXXX>`, ex.: `NPP_MNM_20260602_0001`. Precisa ser
estável e portátil porque a app roda **local em cada máquina** e haverá **export/import de
NPPs entre operadores** (a sincronização fica para depois — fora deste plano). Regras:
- `IniciaisDoOperador`: vem do **cadastro local do operador** (ver bloco abaixo);
  alimenta também `criada_por` (I-4), unificando a identidade.
- `YYYYMMDD`: data de criação.
- `XXXX`: **sequência por dia** (reinicia a cada dia), 4 dígitos zero-padded, contada no
  `StoreNPP` local. Como cada máquina é independente, a unicidade é **local** por ora;
  colisão entre máquinas (mesmas iniciais + data + sequência) só vira problema na futura
  sincronização, tratada lá.

**Identidade do operador (decidido):** as iniciais vêm de um **cadastro básico na primeira
inicialização** do sistema, salvo **localmente** na máquina; esses dados entram numa
**futura função de backup** da aplicação (fora deste plano). Esse cadastro alimenta tanto
`numero` quanto `criada_por` (I-4) — identidade unificada. Implica um
passo novo de bootstrap: na 1ª execução, sem cadastro local → tela de cadastro do operador
(iniciais + nome); persiste em store local próprio (ex.: `operador.sqlite` ou config). Substitui
o `criada_por="operador"` fixo por essa identidade real.

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
- `GET /npp/<id>` — detalhe da NPP (ver §4): cabeçalho + duas seções empilhadas.
  Substitui `consolidado`.
- Importação **escopada à NPP**: `POST /npp/<id>/importar/arquivo|pasta|exemplos`
  (adapta `importar_arquivo`/`importar_pasta`/`importar_exemplos`). `_persistir` passa a
  receber `npp_id` e grava o vínculo; valida CNPJ da nota × prestador do contrato (I-6).
- `POST /npp/<id>/exportar` — exporta as notas inéditas da NPP (reusa `_exportar` +
  `RegistroDeExportacao`). Artefato nomeado por NPP. **NPP de tipos mistos (NFS-e + NF-e):**
  exporta cada nota com as colunas do seu tipo — uma **seção/aba por tipo** no artefato
  (NFS-e com `EXPORT_SPEC_CONSOLIDADO`; NF-e com o spec da NF-e), ou duas faixas na mesma
  planilha. Os **totais da NPP** (bruto, retido, líquido) são por NPP, somando os dois
  tipos. (Layout exato do artefato misto: detalhe de implementação, não muda os totais.)

**Cabeçalho da NPP (só campos que já temos)** — montado em `GET /npp/<id>`, todos
**derivados** (nada novo armazenado além dos campos da §1):

| Rótulo na tela | Origem no código |
|---|---|
| Número da NPP | `npp.numero` (gerado na criação — ver §1) |
| Contrato | `retencao.rotulo_contrato(contrato)` |
| Objeto | `contrato.objeto` |
| Credor (prestador) | `contrato.prest_documento` + `contrato.prest_identificacao` |
| Competência | `npp.competencia` |
| Total dos documentos (bruto) | Σ `valor_servicos` (NFS-e) / `valor_total` (NF-e) via `_soma` |
| Total retido (validado pelo operador) | Σ das retenções **validadas** (ver §4-Seção 2 e §5) |
| Valor líquido | **calculado**: total bruto − total retido validado (ver nota abaixo) |
| Observações | `npp.observacoes` |
| Responsável / datas | `npp.criada_por`, `criada_em`, `atualizada_em` (I-4) |

**Valor líquido — definição e fronteira (I-2/I-3/I-4).** É `Σ valor bruto − Σ retenções`,
e as retenções são as **validadas pelo operador** (confirmadas ou retificadas — ver §5),
não o destaque cru nem uma apuração automática. O destaque do emitente segue preservado e
intocado (I-2); o líquido só aparece **completo/confiável** quando o operador validou os
tributos da nota. Enquanto houver tributo não validado, a tela marca o líquido como
**provisório/indefinido** (I-6), nunca chuta. (Antes de validar, pode-se exibir um líquido
"com base no destaque do emitente", claramente rotulado como ainda-não-validado.)
*NF-e:* o líquido é `bruto − retenções federais validadas` (IR/CSLL/COFINS/PIS). Se o
fornecedor é **optante do Simples**, as retenções são **zero** (dispensa) → líquido =
bruto; se **não** optante, o órgão retém o federal e o líquido reflete isso. INSS/ISS não
entram (não se aplicam à NF-e). É o mesmo cálculo da NFS-e, só com o conjunto de tributos
da NF-e.

Campos do Cosmos **deliberadamente fora** (mundo SIAFI / sem fonte aqui): Nº do Processo,
Valor de Glosa, Recolhimento Patronal, Tipo/Forma de Pagamento, Banco/Agência/Conta,
Ordem Bancária, Documento Hábil, datas de Atesto/Liquidação/Recebimento, Código do
Vínculo, Tipo de Documento Hábil Siafi.

**Conferência via NPP** — `_conferencia(item)` deixa de usar `casar_contratos`: lê
`item` → `npp_id` → `StoreNPP.obter` → `contrato_id` → `StoreContratos.obter` e **despacha
por tipo**: NFS-e → `galho_nfse.retencao.conferir_retencao`; NF-e →
`galho_nfe.retencao.conferir_retencao`. Some o estado `varios`; o contrato é sempre único.
O bloco federal de ambos vem de `tronco/retencao_federal.py` (mesmo `Achado`). A
assinatura `conferir_retencao(reg, contrato, material_marcado)` é preservada; muda a
origem do contrato (NPP) e o federal passa a delegar ao módulo comum.

**Remoções (substituídas pelo fluxo NPP):**
- Rotas `individuais`, `consolidados`, `consolidado`, `exportar` (individual),
  `exportar_grupo`, e a `importar` global (a importação agora é dentro da NPP).
- Funções `_grupos`, `_resumo_consolidacoes`, `_chaves_consolidadas` (heurística) e o uso
  de `casar_contratos` no fluxo.

### 4. Telas — `templates/` (detalhe da NPP em duas seções)

A tela `npp.html` reproduz, simplificada, o layout do Cosmos: **cabeçalho** (tabela acima)
+ **duas seções empilhadas** na mesma página (sem JS) — "Documentos de origem" e depois
"Grupos de impostos". (Começamos por seções empilhadas; abas com alternância via JS ficam
como evolução futura, se a página crescer.)

**Seção 1 — Documentos de origem** (Fase 1 fiel). Uma linha por nota da NPP:

| Coluna | Origem | Observação |
|---|---|---|
| Nº | `reg.numero` | |
| Série | `reg.serie` (NF-e) / `—` (NFS-e) | NFS-e não tem série |
| Data de emissão | `reg.data_emissao` | |
| Valor | `valor_servicos` (NFS-e) / `valor_total` (NF-e) | |
| Conferência | badge de status (`confere`/`diverge`/`indefinido`/`—`) | link → `detalhe` |

Rodapé com **Total** (Σ valor). Botão **Importar notas para esta NPP** (o "+ Adicionar"
do Cosmos) → `POST /npp/<id>/importar/...`.

**Seção 2 — Grupos de impostos** (a fronteira I-2/I-3/I-4 — ler invariantes acima e §5).
Tributos agrupados nas **três categorias** que mapeiam 1:1 nos `Achado` que já produzimos:

- **Contribuição previdenciária:** INSS
- **Tributos federais:** IR, CSLL, COFINS, PIS
- **ISS:** ISS

Cada categoria é uma tabela com colunas **explicitamente rotuladas por procedência**:

| Tributo | Destacado pelo emitente (Fase 1, fiel) | Sugerido pela regra do contrato (Fase 2 — só exibição) | **Validar / retificar (operador)** | Situação |
|---|---|---|---|---|

**Quais tributos aparecem, por tipo de nota** (numa NPP **mista**, as categorias agregam
todas as notas; cada nota contribui só com o que se aplica a ela):
- **NFS-e:** as três categorias conforme o contrato (federal + INSS + ISS).
- **NF-e:** **só Tributos federais** (IR/CSLL/COFINS/PIS, IN 1234/2012), e mesmo esses
  **só quando o fornecedor não é optante do Simples** (optante → dispensa, LC 123/2006,
  todas as retenções = "não se aplica / dispensado"). **INSS e ISS:** sempre "não se
  aplica" para NF-e. O gatilho optante usa `emit_optante_simples`/CRT==1 (Fase 1).
- Assim, numa NPP mista, **Tributos federais** soma NFS-e + NF-e (não-optantes);
  **INSS** e **ISS** só recebem as NFS-e. O líquido = Σbruto − Σretenções validadas,
  independente do tipo (conforme decidido).

Colunas:
- **Destacado pelo emitente:** soma o `_destaque_emitente` por tributo na NPP (`_soma`).
  Transcrição fiel (I-2), **nunca sobrescrita**. ⚠️ **Cuidado na NF-e:** os campos
  `pis_destaque_emitente`/`cofins_destaque_emitente` do `RegistroNFe` são os tributos
  **próprios do vendedor** na operação mercantil, **não** a retenção que o órgão fará — não
  mapear um no outro. A NF-e em geral **não** traz a retenção federal destacada; o operador
  a **insere via retificação** (coluna de validação). Por isso a coluna de destaque da
  retenção, na NF-e, tende a ficar vazia (≠ dos campos PIS/COFINS do vendedor).
- **Sugerido pela regra:** o `esperado` da regra — **só exibição para o humano comparar**
  (I-3); o sistema **não** adota o valor sozinho nem o joga no campo de retificação. NFS-e
  e NF-e têm **paridade**: cada galho tem seu `conferir_retencao`, e o bloco federal
  (IN 1234/2012) é o mesmo, vindo de `tronco/retencao_federal.py` (§Arquivos).
- **Validar / retificar (operador) — o novo passo (Fase 2, validação humana; ver §5):**
  um **toggle** por tributo. *Confirmar* = o operador atesta que o destaque do emitente
  está correto (valor validado := destaque). *Retificar* = ao acionar, abre um **campo
  próprio** para o operador digitar o valor correto (o destaque pode estar equivocado na
  nota). O valor validado é **persistido com autor + data** (I-4), em store separado; o
  destaque original permanece intocado (I-2). Enquanto o tributo não for validado →
  `indefinido` visível (I-6).
- **Situação:** `confere`/`diverge` (validado × destaque, e/ou × sugestão) /
  `indefinido` (ainda não validado) — rótulo de conferência, nunca decisão gravada.

A soma da coluna **validada** é o que alimenta o "Total retido" e o "Valor líquido" do
cabeçalho. Nenhuma regra tributária é aplicada pelo software aqui: ele exibe (Fase 1 +
sugestão Fase 2) e **registra a decisão do operador** (I-3/I-4).

**Demais telas:**
- **Novas:** `npps.html` (lista, com "Nova NPP" e estado vazio — padrão já usado em
  contratos/regras), `npp_form.html` (criar/editar: seletor de contrato + competência +
  rótulo), `npp.html` (detalhe: cabeçalho + seções Documentos de origem / Grupos de impostos).
- **Ajustadas:** `importar.html` vira parcial/escopada à NPP (recebe `npp`); `detalhe.html`
  ganha breadcrumb da NPP e conferência via contrato da NPP; `hub.html` troca os cards
  individuais/consolidados por **NPPs abertas** (valor/contagem) + **Histórico**, com CTA
  "Nova NPP"; `historico.html` passa a exibir o lote junto da NPP de origem.
- **Removidas:** `individuais.html`, `consolidados.html`, `consolidado.html`.
- **Navegação (`base.html`):** o menu "Notas Fiscais → Individuais/Consolidadas" vira
  **"NPPs"** (lista). "Importar" sai da nav global (passa a ser ação dentro da NPP).

### 5. Validação de retenção pelo operador — `tronco/validacao_retencao.py` (novo) — **Fase 2 (validação humana)**

O novo passo que cruza para a Fase 2 (ler o ⚠️ do topo e os invariantes). **Espelha
exatamente `tronco/marcacoes.py`** — que já guarda `valor_material` "validado pelo
operador" com autor + data. Generaliza o padrão de material para os **valores de
retenção** por tributo.

`StoreValidacaoRetencao` (SQLite `validacoes_retencao.sqlite`), append-only (histórico,
nunca sobrescreve — auditável depois, como `marcacoes.py`):

```
validacoes_retencao(
    id INTEGER PK AUTOINCREMENT,
    chave    TEXT NOT NULL,     -- nota
    tributo  TEXT NOT NULL,     -- 'IR'|'CSLL'|'COFINS'|'PIS'|'INSS'|'ISS'
    acao     TEXT NOT NULL,     -- 'confirmado' (= destaque) | 'retificado'
    valor    TEXT NOT NULL,     -- valor VALIDADO (decimal canônico)
    autor    TEXT NOT NULL,     -- identidade do operador (I-4)
    validado_em TEXT NOT NULL   -- ISO-8601 UTC
)
```
API: `validar(chave, tributo, acao, valor, autor)`, `atual(chave, tributo)` (última
vigente), `atuais(chave)` (mapa tributo→validação). Rota nova
`POST /npp/<id>/validar/<chave>/<tributo>` grava a ação do operador. O conjunto de
tributos válidos por nota respeita o tipo: NFS-e = federal+INSS+ISS (conforme contrato);
NF-e = só federal, e só se não-optante do Simples (ver §4-Seção 2).

**Fronteira (releitura do `00`):**
- **I-2:** o `_destaque_emitente` da nota **não é tocado**; a validação é um dado humano
  *separado*, sobreposto. A extração segue fiel.
- **I-3:** o software **não aplica regra**. Ele exibe o destaque (Fase 1) e a sugestão
  (`conferir_retencao.esperado`, Fase 2 — só leitura) e **registra a decisão do operador**.
  *Linha vermelha:* o campo de retificação **nunca** é pré-preenchido com o `esperado` (isso
  seria o software adotando a regra sozinho). O operador digita; pode olhar a sugestão.
- **I-4:** valor validado + autor + data, persistido e auditável (append).
- **I-6:** tributo não validado → `indefinido` visível; líquido provisório, nunca chutado.

### 6. Bootstrap de identidade do operador — `tronco/operador.py` (novo)

Cadastro básico na 1ª inicialização (iniciais + nome), salvo localmente
(`operador.sqlite` ou config). Alimenta `numero` da NPP (§1), `criada_por`/`atualizada_em`
e o `autor` da validação de retenção (§5) — identidade unificada (I-4). Sem cadastro →
tela de cadastro antes de usar. (Entra na futura função de backup da aplicação.)

### 7. Reset do piloto — `tronco/redefinicao.py`

Incluir `npps.sqlite` **e `validacoes_retencao.sqlite`** na redefinição e zerar `npp_id`
junto das notas. (O usuário autorizou zerar o banco.) **O cadastro do operador
(`operador.sqlite`) NÃO é apagado pelo reset** (decidido) — é identidade da máquina, não
dado de teste. Os detalhes (preservação, portabilidade) serão tratados junto com **backup
e sincronização**, em etapa futura.

### Arquivos

| Arquivo | Mudança |
|---|---|
| `tronco/npp.py` | **novo** — `NPP` + `StoreNPP` (gera `numero`) |
| `tronco/validacao_retencao.py` | **novo** — `StoreValidacaoRetencao` (espelha `marcacoes.py`; Fase 2 validação humana) |
| `tronco/operador.py` | **novo** — cadastro/identidade local do operador (bootstrap) |
| `tronco/notas.py` | coluna `npp_id` + migração + `listar_por_npp` + conflito de chave entre NPPs |
| `tronco/app.py` | rotas de NPP (CRUD, importar-na-NPP, exportar-NPP), validar-retenção, bootstrap do operador, cabeçalho derivado, `_conferencia` via NPP, dados das duas seções, hub/nav; remove rotas/funções de individual/consolidado |
| `tronco/retencao_federal.py` | **novo (comum)** — cálculo federal IN 1234/2012 (IR/CSLL/COFINS/PIS) extraído de `galho_nfse` (`_achado_ir`/`_achado_contrib`). Recebe entradas normalizadas (base, percentual, optante, destaques) e devolve `Achado`s. Os dois galhos o chamam; não cria dependência galho↔galho (respeita "dois galhos independentes") |
| `galho_nfse/retencao.py` | `casar_contratos` sai do fluxo (contrato vem da NPP); federal passa a delegar a `tronco/retencao_federal.py`; INSS/ISS seguem aqui. `conferir_retencao` continua **só exibição** |
| `galho_nfe/retencao.py` | **novo** — `conferir_retencao` da NF-e: bloco **federal** via `tronco/retencao_federal.py`, com gatilho optante-Simples (`emit_optante_simples`/CRT==1); INSS/ISS = "não se aplica". **Paridade total com a NFS-e** (sugestão + validação do operador). Só exibição (sugestão) |
| `tronco/redefinicao.py` | inclui `npps.sqlite` + `validacoes_retencao.sqlite` no reset |
| `templates/` | novos `npps.html`/`npp.html` (cabeçalho + 2 seções, com toggle validar/retificar)/`npp_form.html`/`operador_form.html`; ajusta `importar.html`/`detalhe.html`/`hub.html`/`historico.html`/`base.html`; remove `individuais/consolidados/consolidado.html` |
| `tests/test_mvp.py` | testes de NPP (CRUD, vínculo, conferência via NPP, exportação, conflito de chave) + **validação de retenção** (confirmar/retificar, autor+data, líquido sobre validados) + **federal comum** (NFS-e e NF-e dão o mesmo `Achado` federal via `tronco/retencao_federal.py`; NF-e optante → dispensado) + **NPP mista** (totais agregam os dois tipos) + remover testes da heurística |

## Verificação

1. **Testes (`uv run pytest`)**, no estilo por invariante:
   - `StoreNPP` CRUD + audit (I-4); `(contrato, competência)` permite duplicatas.
   - Vínculo: `notas.salvar(..., npp_id)` e `listar_por_npp`; reimportar a mesma chave na
     mesma NPP é idempotente, em outra NPP é conflito (I-1).
   - Conferência via NPP: dado uma NPP com contrato, `_conferencia` devolve a conferência
     do contrato certo sem heurística; CNPJ divergente da nota é marcado (I-6).
   - Seção "Grupos de impostos": a coluna destaque (`_soma`) aparece sempre; **NF-e** mostra
     só Tributos federais (IR/CSLL/COFINS/PIS) e, se optante do Simples, todas "não se
     aplica/dispensado"; INSS/ISS sempre "não se aplica" na NF-e; nada de valor inventado
     (I-2/I-3/I-6).
   - **Validação de retenção (Fase 2 humana):** `validar(..., 'confirmado'|'retificado')`
     grava valor + autor + data (I-4); o `_destaque_emitente` permanece intocado (I-2); o
     campo de retificação **não** nasce com o `esperado` (I-3); tributo não validado fica
     `indefinido` (I-6); o líquido só fecha sobre valores validados.
   - Exportação por NPP: só notas inéditas entram no lote; `RegistroDeExportacao` registra;
     reexportar não duplica (I-1); artefato novo (I-5).
2. **Ponta a ponta (`uv run python -m tronco.app`)**:
   - Criar contrato (já existe) → criar **NPP** escolhendo esse contrato + competência →
     dentro da NPP, **importar** 1+ notas (de exemplos) → ver a seção **Documentos de
     origem** com as notas → ver a seção **Grupos de impostos** com as 3 categorias
     (destaque do emitente + sugestão por contrato) → **confirmar/retificar** cada tributo
     (toggle) → ver o líquido fechar sobre os validados → **exportar a NPP** → **Histórico**.
   - Importar uma nota cujo CNPJ diverge do prestador do contrato → ver o aviso de
     divergência (I-6). Reimportar a mesma nota → ver o aviso de duplicidade (I-1).
   - **NF-e não optante** → "Grupos de impostos" mostra Tributos federais com **sugestão**
     (via `tronco/retencao_federal.py`) + validação do operador; INSS/ISS "não se aplica".
     **NF-e optante do Simples** → tudo "dispensado", líquido = bruto.
   - **NPP mista (NFS-e + NF-e):** bruto = soma de todas; federal agrega os dois tipos,
     INSS/ISS só das NFS-e; líquido = Σbruto − Σretenções validadas; exporta cada tipo com
     suas colunas.
   - Criar duas NPPs no mesmo contrato/competência → ambas coexistem.
3. **Reset**: `redefinir` zera notas + NPPs; a lista de NPPs volta vazia.

## Fora de escopo

- **Apuração/aplicação autônoma de retenção pelo software** — a Fase 2 que entra aqui é
  **só a validação humana** (I-3). O software nunca decide nem aplica a regra sozinho, nem
  pré-preenche a retificação com o `esperado`. Isso continua exigindo decisão humana futura.
- Integração real com SIAFI (o Cosmos integra; aqui seguimos exportando artefato — a
  interface `Exportador` já isola o destino, I-5). Os campos de pagamento do Cosmos
  (banco, OB, datas de liquidação, código do vínculo etc.) ficam de fora por isso.
- Sincronização / export-import de NPPs entre máquinas (o `numero` já é desenhado para ser
  portátil, mas o mecanismo de troca e a resolução de colisão ficam para depois).
- Função de backup da aplicação (que levará o cadastro do operador) — desenho futuro.
- Geração automática da NPP a partir de notas soltas (a jornada é criar-NPP-primeiro).
- INSS/ISS no catálogo de enquadramento (trabalho anterior; segue como está).

## Ordem de implementação (status — branch `feat/modelagem-npp`)

Construção de dentro para fora (dados → lógica → UI), cada passo com testes e
`uv run pytest` verde; a UI (acoplada) fica por último. Estado em 2026-06-02:

- [x] **Passo 1 — `tronco/retencao_federal.py`** (refactor do bloco federal comum). *commit `9fb2bfe`*
- [x] **Passo 2 — `galho_nfe/retencao.py`** (conferência federal da NF-e + tipos comuns no tronco). *commit `0f926d7`*
- [x] **Passo 3 — `tronco/operador.py`** (identidade local do operador, I-4). *commit `aff4662`*
- [x] **Passo 4 — `tronco/npp.py`** (`NPP` + `StoreNPP`, geração do `numero`). *commit `eb53349`*
- [x] **Passo 5 — `tronco/notas.py`** (coluna `npp_id` + `listar_por_npp` + `ConflitoDeChave`). *commit `47abaca`*
- [x] **Passo 6 — `tronco/validacao_retencao.py`** (confirmar/retificar, I-3/I-4). *commit `71d7449`*
- [ ] **Passo 7 — `tronco/app.py` + `templates/`** — fatiado (ver abaixo). **7a feito**; faltam 7b, 7c.
- [ ] **Passo 8 — `tronco/redefinicao.py`** — incluir `npps.sqlite` + `validacoes_retencao.sqlite` no reset; **preservar** `operador.sqlite`.

55 testes verdes até o passo 6; **57 após o 7a**.

### Divisão do passo 7 (UI) — fazer em sessão nova (janela de contexto)

Cada subetapa termina com `pytest` verde e o app de pé; o fluxo antigo
(individual/consolidado) só é removido na 7c.

- [x] **7a — Fundação da jornada (app segue funcionando, nada removido):** **FEITO** (57 testes).
  - *Bootstrap do operador:* sem cadastro local → `before_request` desvia para
    `operador_form.html` (`StoreOperador`); `criada_por`/`autor` usam a identidade real.
    Identidade exibida no rodapé (`base.html`, via context processor).
  - *CRUD da NPP:* `GET /npps`, `GET /npps/nova`, `POST /npps`, `GET /npp/<id>`,
    `GET /npp/<id>/editar`, `POST /npp/<id>`, `POST /npp/<id>/remover`; templates
    `npps.html`, `npp_form.html`, `npp.html` (detalhe enxuto: cabeçalho + Documentos de
    origem + importação; "Grupos de impostos" fica para o 7b). Nav ganhou "NPPs".
    Remover só NPP vazia (I-6). Contrato/numero imutáveis na edição.
  - *Importação escopada à NPP:* `POST /npp/<id>/importar/arquivo|pasta|exemplos`;
    `_persistir(resultados, npp_id)` trata `ConflitoDeChave` ("já consta na NPP nº X")
    e `_divergencias_cnpj` sinaliza CNPJ × prestador do contrato (I-6, não bloqueia).
  - *Verificado:* `uv run pytest` 57 verdes + smoke ponta-a-ponta das 11 etapas do fluxo.
- **7b — Detalhe da NPP (duas seções) + validar/retificar:**
  - `GET /npp/<id>`: cabeçalho derivado (tabela do §3) + Seção 1 (Documentos de origem)
    + Seção 2 (Grupos de impostos), seções empilhadas.
  - `_conferencia` despacha por tipo: NFS-e → `galho_nfse`, NF-e → `galho_nfe` (contrato da NPP).
  - Validar/retificar: `POST /npp/<id>/validar/<chave>/<tributo>` → `StoreValidacaoRetencao`;
    toggle confirmar / campo retificar — **nunca** pré-preencher com o `esperado` (linha vermelha).
  - Total retido / líquido derivados das validações.
- **7c — Exportação por NPP + remoção do fluxo antigo:**
  - `POST /npp/<id>/exportar` (reusa `_exportar` + `RegistroDeExportacao`); NPP mista
    exporta cada tipo com suas colunas.
  - Hub/nav: `hub.html` → NPPs abertas + Histórico; `base.html` → "NPPs"; `historico.html`
    mostra a NPP de origem.
  - **Remover:** rotas `individuais`/`consolidados`/`consolidado`/`exportar`/`exportar_grupo`/
    `importar` global; funções `_grupos`/`_resumo_consolidacoes`/`_chaves_consolidadas`; uso
    de `casar_contratos` no fluxo; templates `individuais/consolidados/consolidado.html`.
    Remover testes da heurística; (se viável) adicionar testes de rota da NPP.
