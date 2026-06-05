# Plano — Backup e Sincronização (snapshot JSON via Google Drive)

> **Status:** planejado e revisado; **aguardando implementação**. As decisões do humano
> (seção Context → Decisões travadas) estão **fixadas em 2026-06-02**. Esta é a cópia
> versionada no git (portátil entre máquinas).
> Para retomar: ler este arquivo inteiro, confirmar que as decisões ainda valem, reler
> `docs/00_PRINCIPIOS.md` e declarar por escrito como cada invariante tocado é respeitado
> (protocolo do CLAUDE.md), e seguir a Ordem de implementação (§9).
>
> Resolve as **decisões #5 e #8** de `ESTADO_E_PROXIMOS_PASSOS.md`. Continuação direta das
> notas já deixadas no código: `tronco/npp.py` ("export/import de NPPs entre operadores é
> etapa futura"; `numero` é "estável e portátil") e `tronco/operador.py` ("esses dados
> entram, no futuro, na função de backup/sincronização").

## Context

A `app` roda **local em cada máquina, um usuário, sem autenticação** (POC). Hoje todo o
estado mora em 8 bancos SQLite na raiz do repo (todos no `.gitignore`). Falta uma forma de
(a) **proteger** o trabalho de um operador contra perda/troca de máquina e (b) **propagar
a configuração** (contratos e regras) para a equipe. A ideia do humano: **exportar e
importar arquivos JSON usando o Google Drive da equipe**.

Dois módulos, do tronco (infraestrutura comum, como idempotência e exportador):
- **Backup** — lê os bancos e produz um snapshot JSON autocontido e versionado.
- **Sincronização** — lê um snapshot, planeja o que entra, mostra para conferência e aplica
  com merge seguro por invariante.

### Decisões travadas (humano, 2026-06-02)

1. **Direção do sync = backup pessoal por operador.** A **configuração** (contratos+regras)
   é **compartilhada** pela equipe via Drive; os **dados de trabalho** (notas, NPPs,
   marcações, validações, ledger de exportação) são **backup pessoal restaurável** — não um
   pool coletivo editado por vários simultaneamente. Isso contém o risco de I-1: o ledger de
   exportação só é unido entre **máquinas do mesmo operador**, nunca entre operadores
   diferentes. (Pool coletivo de trabalho fica fora deste plano; exigiria ledger I-1 central
   unido, bem mais complexo.)
2. **Transporte = manual primeiro, API depois.** Fase A: o app **só gera e consome o `.json`**;
   o operador sobe/baixa manualmente na pasta do Drive da equipe — **zero credencial no
   código** (respeita o grau-POC). Fase B (futura): integração via API
   (`google-api-python-client`), com a escolha de auth (conta de serviço × OAuth por
   operador) resolvida **junto da decisão #4** (destino Sheets).

## Protocolo — invariantes tocados e como são respeitados

A feature toca **I-1, I-2, I-4, I-5, I-6** (I-3 só indiretamente: validações importadas são
preservadas como decisão humana, nunca regeradas).

| Inv. | Risco que a feature cria | Como o plano respeita |
|---|---|---|
| **I-1** (idempotência) | Restaurar um snapshot sem o `registro_exportacao` faria uma nota já paga voltar a "exportável" → **pagamento em duplicidade**. | O ledger é **memória de união append-only**: a importação só **acrescenta** chaves exportadas, **nunca remove** (`INSERT OR IGNORE`, já é o padrão do store). Como o sync é pessoal (decisão #1), o ledger só se une entre máquinas do mesmo operador. |
| **I-2** (extração fiel) | Round-trip poderia reinterpretar/normalizar `dados_json`. | O backup **transcreve o `dados_json` byte-a-byte**; a importação **não re-extrai XML** nem normaliza. O registro plano volta idêntico. |
| **I-4** (rastreabilidade) | Import poderia regravar `autor`/data como sendo de quem importou. | Marcações e validações entram **preservando `autor` e timestamp originais**; histórico append-only mantido. Quem importou fica em **metadado do snapshot**, nunca sobre a autoria do fato. |
| **I-5** (artefato novo) | Confundir o JSON de backup com o artefato de exportação (o "lote"). | São distintos — o backup **não** é o artefato do I-5. Mesmo assim adoto o espírito: cada snapshot é **arquivo novo, imutável, carimbado**; nunca reescreve um anterior (igual a `redefinicao.py`). |
| **I-6** (ambiguidade visível) | Merge automático sobrescreveria/inventaria em silêncio. | Toda colisão (mesma `chave` em NPP diferente, contrato/regra divergente, versão de schema incompatível, hash que não bate) é **relatada e barrada**, resolvida por escolha humana. Reusa o padrão `ConflitoDeChave` de `notas.py`. |

**Contra `01_ARQUITETURA`:** ambos os módulos são **tronco puro** — não tocam galhos, não
fazem segunda leitura de XML, não criam modelo unificado. **Fase 1/infra:** não apuram nada
tributário (só movem dado já gravado). A fronteira Fase 1/2 não é cruzada.

## Inventário dos dados (3 classes, tratamento distinto)

**A. Configuração (compartilhável — Drive da equipe)**
- `contratos.sqlite` — chave natural `(prest_documento, numero, ano)` (UNIQUE no store).
  **Inclui a tabela filha `contrato_municipios`** (ISS por município, adicionada 2026-06-04):
  vai junto, sem rowid, na serialização do contrato.
- `catalogo_federal.sqlite` — chave natural `codigo` (UNIQUE).
- `catalogo_inss.sqlite` — chave natural `codigo` (UNIQUE), adicionado 2026-06-04. "Regras"
  no escopo `configuracao` = federais **+** INSS.

**B. Dados de trabalho (backup pessoal — sensível a I-1)**
- `notas.sqlite` — chave natural `chave` (44 díg / id NFS-e), **globalmente única e portátil**.
- `npps.sqlite` — chave natural `numero` (`NPP_<iniciais>_<AAAAMMDD>_<NNNN>`), **estável/portátil por construção**.
- `marcacoes.sqlite` — append-only por `chave` (I-4).
- `validacoes_retencao.sqlite` — append-only por `(chave, tributo)` (I-4).
- `registro_exportacao.sqlite` — ledger I-1 por `chave`.

**C. Identidade local (NÃO entra no pacote da equipe)**
- `operador.sqlite` — por máquina; o reset já o preserva. Entra só no escopo `pessoal`.

> `static/dados/municipios_ibge.json` é referência estática versionada no git — fora do backup.

## O problema central: ID local × chave natural

Os vínculos hoje usam **`rowid` autoincrement local**: `nota.npp_id → npps.id` e
`npp.contrato_id → contratos.id`. Esses inteiros **não são portáveis** entre máquinas. Um
backup que copiasse os inteiros **corromperia os vínculos** ao importar (I-6 silencioso).

**Regra de ouro:** o JSON **nunca serializa FK por `rowid`**. Todo vínculo vai por **chave
natural**:
- nota → NPP por **`npp.numero`**;
- NPP → contrato por **`(prest_documento, numero, ano)`**.

Na importação, os `rowid` locais são **resolvidos/recriados** a partir dessas chaves. É o
que torna o snapshot robusto entre máquinas.

## Módulo 1 — Backup (`tronco/backup.py`)

Responsabilidade única: ler os bancos (via API pública dos stores, **não SQL cru**) e
produzir o snapshot. Não decide nada.

- `exportar_snapshot(escopo) -> dict` — lê cada store, traduz FK→chave natural, monta o
  envelope (§ Esquema).
- **Escopos** (alinhados às 3 classes):
  - `configuracao` — só contratos + regras (propagar config pela equipe);
  - `trabalho` — notas, NPPs, marcações, validações, ledger de exportação;
  - `completo` — A + B (sem operador);
  - `pessoal` — completo + `operador` (backup da própria máquina).
- **Saída:** `backups/snapshot_<carimbo>_<escopo>.json` (mesma pasta que `redefinicao.py` já
  usa). Imutável, append-only (espírito I-5).
- **Integridade:** envelope com `gerado_em`, `gerado_por`, `schema_versao`, `contagem` por
  entidade e `hash_conteudo` (sha256 sobre o bloco `dados` canônico) — para a importação
  detectar truncamento/corrupção (I-6).

## Módulo 2 — Sincronização (`tronco/sincronizacao.py`)

Fluxo em **2 passos** (espelha a barreira do `redefinir`):

1. `planejar_importacao(snapshot) -> Plano` (**dry-run, não grava**): valida
   schema/versão/hash; resolve chaves naturais → FKs locais; classifica cada item em
   **novo / idêntico (no-op) / conflito**; lista divergências. Devolve relatório para a tela.
2. `aplicar_importacao(plano, resolucoes) -> Resumo`: grava só o aprovado, em **transação**,
   preservando autoria e o ledger (§ Merge). **Antes de tocar qualquer banco**, faz backup
   automático do estado atual (como o reset) — desfazer é sempre possível (I-6).

Conflitos **nunca** são auto-resolvidos: a tela oferece "manter local" / "usar do snapshot"
/ "pular", e a escolha é registrada (I-3/I-4/I-6).

## Esquema do JSON (envelope versionado)

```jsonc
{
  "formato": "extrator-nf/snapshot",
  "schema_versao": 1,
  "escopo": "completo",
  "gerado_em": "2026-06-02T18:00:00Z",
  "gerado_por": {"iniciais": "MNM", "nome": "..."},
  "hash_conteudo": "sha256:...",            // sobre "dados" canônico
  "contagem": {"contratos": 4, "regras_federais": 12, "notas": 30, "npps": 6},
  "dados": {
    "contratos":   [ { /* campos do dataclass */, "_chave_natural": ["<doc>","<num>","<ano>"] } ],
    "regras_federais": [ { /* campos */, "codigo": "TF0007" } ],
    "npps": [ { "numero": "NPP_MNM_20260602_0001",
                "contrato_ref": ["<doc>","<num>","<ano>"],     // FK por chave natural
                "competencia": "...", "criada_por": "...", "criada_em": "..." } ],
    "notas": [ { "chave": "...", "tipo": "NFSE", "origem": "...",
                 "npp_ref": "NPP_MNM_20260602_0001",            // FK por numero
                 "dados": { /* dados_json transcrito fielmente (I-2) */ } } ],
    "marcacoes":   [ { "chave": "...", "valor": "sim", "valor_material": "...",
                       "autor": "...", "marcado_em": "..." } ],   // I-4 preservado
    "validacoes":  [ { "chave": "...", "tributo": "ISS", "acao": "retificado",
                       "valor": "...", "autor": "...", "validado_em": "..." } ],
    "exportacoes": [ { "chave": "...", "tipo": "NFSE",
                       "lote_id": "...", "exportado_em": "..." } ]  // ledger I-1
  }
}
```

`schema_versao` desconhecida = **barra com mensagem** (I-6), nunca adivinha.

## Merge, por entidade (o que protege os invariantes)

Não existe "last-write-wins" global. Cada classe tem regra própria:

- **`registro_exportacao` (I-1)** → **UNIÃO append-only**: só adiciona, jamais remove. **Item
  mais crítico.**
- **`marcacoes` / `validacoes` (I-4)** → merge por **append idempotente**: registro já presente
  (mesma tupla autor+timestamp+valor) = no-op; novos entram preservando autoria. Histórico
  nunca é truncado.
- **`notas`** → por `chave`. Mesma chave na **mesma** NPP = idempotente (já é o `salvar`).
  Mesma chave em **NPP diferente** = `ConflitoDeChave` exibido (reusa o existente). `dados`
  divergentes p/ a mesma chave = conflito visível, nunca sobrescreve (I-2/I-6).
- **`npps`** → por `numero` (UNIQUE/portátil). Novo entra; igual com campos divergentes =
  conflito exibido.
- **`contratos` / `regras_federais`** → chave natural. Novo entra; idêntico = no-op;
  divergente = conflito com **diff campo-a-campo** (config compartilhada é onde dois editam
  a mesma coisa).
- **`operador`** → nunca importado do pacote de equipe; só restaurável de um backup `pessoal`
  na própria máquina.

## O Google Drive (Fase A, manual)

O app gera o `.json` em `backups/` e o operador o sobe na pasta do Drive da equipe; para
importar, baixa e seleciona o arquivo. Sem credencial no código. UI: tela **"Backup e
sincronização"** com "Gerar snapshot" (escolhe escopo, baixa `.json`) e "Importar snapshot"
(mostra o **plano**: X novos / Y idênticos / Z conflitos detalhados → confirma).

> **Sigilo:** o `00` não tem invariante de sigilo (dados também em portais públicos), **mas**
> "envio a serviço de terceiros volta a ser decisão consciente registrada". Subir snapshots
> ao Drive **é** isso — ratificado aqui como decisão.

## Ordem de implementação

1. `tronco/backup.py` — `exportar_snapshot(escopo)` + testes de round-trip por invariante
   (snapshot→import→estado idêntico; FK por chave natural; `dados_json` byte-idêntico).
2. `tronco/sincronizacao.py` — `planejar_importacao` (dry-run) com classificação
   novo/idêntico/conflito + testes de merge (união do ledger I-1; preservação de autoria I-4;
   conflito de chave/contrato visível I-6).
3. `aplicar_importacao` transacional + backup automático pré-import.
4. UI — tela "Backup e sincronização" (gerar / importar com plano e resolução de conflito).
5. (Fase B) integração Drive via API, conforme a decisão de auth (junto da #4 Sheets).

Cada passo passa pelo protocolo do CLAUDE.md e mantém os testes verdes (hoje 61).

## Refinamentos e decisões do humano — 2026-06-05

Ao iniciar a implementação (branch `feat/backup-export-import`), o humano refinou o plano
(decisões registradas via pergunta direta):

1. **Export/import item-a-item, além dos pacotes em bloco.** Cada arquivo que compõe o
   sistema pode ser exportado/importado individualmente: **uma** NPP, **um** contrato, **uma**
   regra (federal ou INSS) — somado ao backup completo e ao pacote `configuracao`. O envelope
   é único; cada ponto de exportação preenche um subconjunto do bloco `dados`; o importador é
   genérico (classifica o que estiver presente).
2. **NPP individual carrega o contrato EMBUTIDO** (não só a referência por chave natural):
   o arquivo é 100% portátil. Em quem importa, o contrato novo entra; idêntico é no-op;
   divergente vira conflito visível (I-6).
3. **Ledger de exportação viaja sempre junto e se une append-only em QUALQUER máquina**
   (supera a redação original da decisão #1, que uniria o ledger só entre máquinas do mesmo
   operador). Motivo, levantado e ratificado com o humano: ao entregar a outro operador uma
   NPP já exportada, **não** unir o ledger deixaria as notas reaparecerem como exportáveis no
   destino → risco de pagamento em duplicidade (I-1, o pior erro). Marcar uma chave como já
   exportada só pode **impedir** um pagamento, nunca causá-lo — logo unir é seguro por
   construção. A procedência (quem/quando exportou) fica visível.
4. **Nome do arquivo de NPP herda o `numero`** (`NPP_<iniciais>_<AAAAMMDD>_<NNNN>.json`) — as
   iniciais do operador no nome evitam que NPPs de operadores diferentes se confundam na pasta
   do Drive.

## Estado de implementação — 2026-06-05 (branch `feat/backup-export-import`)

- **Passos 1–3 do plano: FEITOS e testados.** `tronco/backup.py` (envelope + exportações
  individuais e em bloco; FK por chave natural; hash) e `tronco/sincronizacao.py`
  (`planejar_importacao` dry-run + `aplicar_importacao` transacional com backup automático
  pré-import e resolução de conflito). Métodos novos nos stores: `historico`/`importar`
  preservando autoria (`marcacoes`, `validacoes_retencao`); `obter_por_chave_natural`
  (`contratos`), `obter_por_codigo` (catálogos), `obter_por_numero`/`importar` (`npp`),
  `importar` (união do ledger, `idempotencia`). **+17 testes por invariante (102 verdes).**
- **Passo 4 (UI): FEITO** (branch `feat/backup-ui`). Tela "Backup e sincronização" no menu
  Configuração: exportar por escopo (`configuracao`/`completo`/`pessoal`, download `.json`) e
  importar via upload, que mostra o **plano** (novos/idênticos/conflitos com diff campo-a-campo
  e resolução por conflito: pular/usar do arquivo/manter local) **antes** de gravar; aplicar faz
  backup automático do estado atual antes (I-6). Botão **Exportar** item-a-item nas telas de
  NPPs, Contratos e Regras (rotas `GET /backup/exportar/...`). Rotas em `tronco/app.py`; telas
  `templates/backup.html` + `templates/backup_plano.html`. Correção de comparação:
  `sincronizacao._diff` normaliza os dois lados via JSON (tupla×lista não é mais falso conflito)
  — coberto por `test_config_com_listas_reimporta_sem_falso_conflito`. **103 testes verdes.**
- **Passo 5 (API Drive): futuro**, junto da decisão #4 (Sheets).

## Riscos sinalizados

- **Crítico:** ledger I-1 dessincronizado → duplicidade. Mitigado por "união append-only,
  nunca subtrai" + sync pessoal (decisão #1).
- **Edição concorrente de config** na pasta compartilhada: resolvida por conflito-visível,
  não por relógio.
- **Sigilo/Drive:** ver nota acima — decisão consciente registrada.
