# Estado atual e próximos passos

> Ponto de partida para tocar o projeto no Claude Code. O backlog abaixo é um
> **rascunho meu, para você editar** — suas prioridades reais entram aqui.

## O que já existe e funciona (Fase 1)

- **Tronco:** ingestão de XML, identificação de tipo (NF-e/NFS-e), idempotência
  por chave (SQLite), tela de conferência (Flask), exportação plugável.
- **Galho NF-e (Fase 1):** extração dos campos de cabeçalho via `nfelib`.
- **Galho NFS-e (Fase 1):** extração + discriminação (texto livre) + marcação
  humana de material aplicado (persistida com autor e data — I-4).
- **UI:** design system (IBM Plex), modo claro/escuro, escala de fonte acessível,
  formatação pt-BR (moeda/CNPJ/data), painel com KPIs, e **tabela consolidada por
  prestador + competência** (serviço continuado em vários municípios).
- **Testes:** 9 passando, organizados por invariante.

## O que é grau-POC (ver CLAUDE.md para a lista)

Resumo: exportador é CSV local (não Sheets real), XMLs são sintéticos, sem auth,
`debug=True` e `secret_key` fixa, SQLite no repo. Nada disso pode ir a dado real
sem revisão.

## Implementação em andamento — branch `feat/modelagem-npp` (2026-06-02)

Modelagem por NPP em construção (de dentro para fora; ver
`docs/planos/modelagem-npp.md` § "Ordem de implementação"). **Passos 1–6 prontos e
commitados** (módulo federal comum, conferência federal da NF-e, identidade do operador,
`StoreNPP`, vínculo `npp_id`, validação de retenção). **55 testes verdes.**

Passo 7 (UI) fatiado em **7a** (bootstrap do operador + CRUD da NPP + importação escopada),
**7b** (detalhe em duas seções + validar/retificar), **7c** (exportação por NPP + remoção do
fluxo individual/consolidado). **Plano NPP concluído (passos 1–8).** Jornada por NPP completa:
operador, CRUD/importação escopada, detalhe com Grupos de impostos (3 camadas) +
validar/retificar, **exportação por NPP** (idempotente, artefato novo) e **reset** incluindo
`npps.sqlite`+`validacoes_retencao.sqlite` (preservando `operador.sqlite` e a configuração). O
**fluxo antigo foi removido** (individual/consolidado, heurística por CNPJ, importação global);
a nav é só "NPPs". **61 testes verdes.** Falta mergear a branch e seguir para os próximos temas
(exportador Sheets real — decisão #4; endurecimento de dado real). Detalhe no plano.

## Mudança de fase — 2026-06-02

O projeto **cruzou para a Fase 2**, mas só na metade de **validação/aprovação humana**
(I-3): o operador passa a **confirmar ou retificar** os valores de retenção destacados na
nota (o destaque pode estar equivocado), e é isso que alimenta o **valor líquido confiável**.
A **apuração/aplicação autônoma de regra pelo software continua fora de escopo** — o
software exibe destaque (Fase 1) e sugestão (`conferir_retencao`, só leitura) e **registra
a decisão humana** (persistida com autor+data, I-4, no padrão de `tronco/marcacoes.py`).
Detalhe em `docs/planos/modelagem-npp.md` (§5–§6). Memórias: `fase2-validacao-humana`,
`fronteira-fase1-fase2`.

## Revisão de UX — 2026-06-02 (fases de melhoria da interface)

Revisão completa do front-end (design/estrutura/UX/jornada), ancorada em boas práticas
(gov.br Design System / e-PWG; padrões de fluxo financeiro humano-no-circuito). Veredito:
base já madura (WCAG AA, dark/auto, escala de fonte, invariantes expressos em tokens) —
**refino, não reescrita**. Identidade visual: **manter o DS próprio** (decisão do humano).
Roadmap em 4 fases:

- **Fase 0 — Higiene: FEITA** (commit `d7c2d5a`). Corrige `--radius-md` inexistente;
  define `.ok-chip`/`.revalidar` (eram usados sem estilo na validação da NPP); remove JS/CSS
  morto do fluxo antigo (triagem `#tabela-notas`, `.nav-dropdown`, `.flash`); troca estilos
  inline que corroíam o DS por classes (`.flag.warn`, `.ml-auto`, `.group-label`,
  `.figure.nome`, `.mt-4`); renomeia `.consol-card`→`.list-row`.
- **Fase 1 — Jornada de validação: FEITA** (commit `f2c68fb`). Rota
  `POST /npp/<id>/confirmar-destaques` (ateste do destaque do emitente em lote; seleção
  **mecânica**, nunca por conformidade com a sugestão — linha vermelha I-3; valor recomputado
  no servidor I-2; autor+data I-4; divergências/sem-destaque reportados I-6). Barra de
  progresso "validados X de Y" na NPP. Coluna Material + aviso de material não conferido.
  Teste de ponta a ponta da rota de lote. **65 testes verdes.**
- **Fase 2 — Validação inline: FEITA.** Confirmar/retificar grava sem recarregar a página:
  `npp_validar` responde JSON (fragmentos renderizados pelo SERVIDOR) quando chamada via fetch
  (`X-Requested-With: fetch`), ou mantém flash+redirect sem JS — mesmo caminho de gravação.
  IIFE em `app.js` intercepta por delegação (pega até os forms de "Revalidar" que entram via
  innerHTML) e troca só a linha, o progresso, o total do grupo, o "Total retido"/líquido e o
  contador do lote; sem rede, degrada para o POST normal. Partials reusados como fragmentos:
  `_validar_celula.html`, `_situacao_celula.html`, `_progresso_validacao.html`; helper
  `_contexto_validacao` unifica o recálculo da página e do JSON. **Guardas mantidas:** destaque
  recomputado no servidor (I-2 — o "confirmar" não envia valor); gravação com autor+data (I-4);
  campo de retificar nasce vazio (I-3); erro inválido volta `422 ok:false` exibido inline e o
  caminho sem-JS segue intacto (I-6). Teste de rota cobre os quatro casos. **66 testes verdes.**
- **Fase 3 — Arquitetura de informação: PENDENTE (replanejada 2026-06-03).** Duas frentes,
  nenhuma toca invariante:
  1. **Agrupar "Configuração" na nav: FEITA.** Contratos + Regras (+ futuro Backup/Sync) saíram
     da fila plana de `base.html` para um `details.dropdown` recolhido ("Configuração"), reusando
     o IIFE e o CSS do menu "Exibição" (abre no clique mesmo sem JS; abre por padrão e marca
     `on` quando a página atual é de configuração). A nav de fluxo ficou enxuta: Início · NPPs ·
     Histórico.
  2. **Busca/filtro na lista de NPPs (próximo)** (`npps.html`), por contrato/competência/situação.
     Progressive enhancement (sem JS, a lista completa aparece); **não agrega nem soma valores**
     (não encosta em I-2) — é só encontrabilidade quando muitas NPPs se acumulam no mês.
     Reaproveitar o padrão de triagem acessível removido na Fase 0 (`aria-selected`/`aria-sort`).

## Ajustes de UI + horário local + federal por nota: FEITO (2026-06-03)

Lote de ajustes pedido pelo humano (só Fase 1/apresentação e UX da validação Fase 2;
nenhum invariante tocado). **71 testes verdes.**

- **Horário da máquina do operador:** novo helper `tronco/util.agora()`
  (`datetime.now().astimezone()` — fuso local com offset). Todos os registros
  (marcações, validações, NPP, exportações, contratos, idempotência, operador, catálogo)
  passaram de UTC para o relógio local que o operador lê (I-4 segue auditável).
- **Tela de detalhes:** "Local da prestação"/"Local do prestador" exibem o **nome** do
  município (`xLocPrestacao`/`xLocEmi` do próprio XML), não o código; aviso de material
  removido da seção de conferência; razão social canônica do tomador por CNPJ via novo
  `tronco/orgaos.py` + filtro Jinja `orgao` (ex.: `26.989.715/0016-99` →
  "Procuradoria da República de Minas Gerais") — **só exibição, extração fiel intacta (I-2)**;
  cards `dl.grid` ganharam **zebra** ligando rótulo↔valor.
- **Etiqueta "inédita" → "nova"** em toda a UI (e comentários de código).
- **Guia Documentos de origem:** **município** como 1ª coluna; situação "nova".
- **Tributos federais reorganizados POR NOTA (substitui o "por código" abaixo):** cada nota
  é **uma linha** com código + alíquota agregada (`6190 · 9,45%`), Σ destacado, Σ sugerido,
  ação e situação. Fechada → botão **"Confirmar agregado"** (confirma os tributos federais
  pendentes da nota pelo destaque do emitente, gravando **cada um individualmente** — I-4;
  rota `npp_confirmar_agregado`); aberta → retificar tributo a tributo (campo nunca
  pré-preenchido, I-3). Divergência destaque≠sugestão em qualquer tributo **realça a linha**
  e mostra **tooltip** de conferência (I-6). `_agregar_federal` agrupa por `chave`; partial
  novo `_linha_tributo_federal.html`; swap inline por nota (`data-federal-chave`).

## Revisão geral da interface — apresentação das NPPs: FEITO (2026-06-04) — branch `refit/revisao-interface`

Rodada de refino visual/UX da jornada por NPP pedida pelo humano. **Só Fase 1/apresentação;
nenhum invariante quebrado.** **77 testes verdes.**

- **Rótulo compacto da NPP (`npp_curto`):** o `numero`
  `NPP_<iniciais>_<AAAAMMDD>_<NNNN>` é identidade/nome de arquivo, não rótulo de UI. Na
  tela mostra só `dia/mês · sequencial` (ex.: `04/06 · 0001`) — some prefixo e iniciais.
  Só apresentação (I-2): o `numero` segue **imutável** no banco e **inteiro** no artefato
  exportado; autoria das iniciais persistida em `criada_por`/Responsável (I-4). Aplicado
  na lista, no detalhe da NPP/nota e no form.
- **Filtro `competencia` tolerante a `AAAA-MM`** (a NPP guarda a competência sem dia):
  `2026-05 → 05/2026` em toda a app (antes vinha cru).
- **Cards de importação (detalhe da NPP) refeitos:** mais compactos/harmônicos/modernos —
  chip de ícone estilizado (antes sem estilo fora de `.module-card`), header título+descrição
  e **dropzone tracejada** para a pasta espelhando o input nativo. Ganchos de JS preservados.
- **Linha de NPP em duas linhas (`.npp-row`, compartilhada por lista e histórico):** 1ª
  linha = `data·seq` + **nome completo do prestador**; 2ª = competência · nº de notas ·
  situação; **total mescla as duas** à direita; **botão "Abrir NPP"** em vez de
  linha-inteira-link (o valor não herda mais a cor de link).
- **DECISÃO (arquitetura): menu "Histórico" removido — fundido na lista de NPPs.** Desde
  que o histórico passou a ser agrupado por NPP, ele era apenas "as NPPs filtradas por
  exportadas". A lista de NPPs ganhou **filtro Todas/Abertas/Exportadas** e passou a exibir
  a **data de exportação** nas exportadas. **I-1 intacto:** a idempotência vive no
  `RegistroDeExportacao` (chave = PK) + checagem `ja_exportada()` antes de cada lote, nunca
  na tela — remover o menu não a toca. `/historico` → **redirect** p/ `/npps?ver=exportadas`;
  `historico.html` removido; nav enxuta (Início · NPPs · Configuração); o card do Início
  virou **"NPPs exportadas"**. *Ressalva:* nota exportada sem NPP (órfã de base legada)
  deixaria de ter tela — não há nenhuma hoje e o modelo novo não cria mais; reavaliar se um
  dia importar base legada.

## Refit visual da aba de Impostos da NPP: FEITO (2026-06-04) — branch `refit-grupo-impostos` (mergeada+removida)

Refino visual da aba "Grupos de impostos" pedido pelo humano (direção escolhida:
**grupos fechados com resumo no cabeçalho** + **reorganização moderada**). **Só Fase 1/
apresentação e UX da validação Fase 2; nenhum invariante quebrado.** **71 testes verdes.**

- **Grupos viraram cartões colapsáveis fechados por padrão.** O cabeçalho resume status e
  total para o operador abrir só o que precisa (I-6: pendência/divergência visíveis com o
  grupo fechado). Cabeçalho em **duas linhas fixas** — título na 1ª, chips + total na 2ª —
  para os cartões não desequilibrarem (um em 1 linha, outro estourando p/ 2).
- **Chips de status no cabeçalho:** `N divergências encontradas` / `N divergências tratadas`
  / `N a validar` / `validado`. "encontradas" só fica amarelo (`.alarme`) enquanto houver
  alguma **não tratada** — amarelo reservado ao que ainda exige conferência (I-6). Contadores
  por grupo no backend (`n_total/n_pendentes/n_diverge_total/n_diverge_tratadas` em
  `_grupos_impostos`); o JS recomputa os chips por DOM na validação inline via marca
  persistente `data-diverge` (não some ao validar).
- **Acento de cor por camada** nas thead das 3 colunas (borda inferior, sem recolorir o
  texto — preserva AA): destaque = `--declarado` (I-2), sugestão = `--ink-3`/referência
  (I-3), validação = `--primary` (ação do operador).
- **Resumo federal retraído harmonizado com INSS/ISS:** o agregado por nota deixou o flex
  solto e virou **grade de células rotuladas** (rótulo em cima, valor embaixo) espelhando as
  colunas e a densidade das tabelas (Município/Nota/Tributo/Destacado/Sugerido/Situação),
  duas linhas por item; colunas de identidade em `fr` + valor/ação fixas → alinham na
  vertical entre as linhas. Fallback empilhado < 820px.
- **Célula do tributo sem duplicação:** a `regra` começava pelo nome (ex.: "INSS 11%"),
  então a exibição mostra só o detalhe ("11%") nos três grupos.
- **Carimbo de validação sem autor** (operador único; segue persistido/rastreável no
  store/histórico/exportação — I-4); também harmoniza a altura da linha entre os grupos.
- **Removidos da aba:** banner "N nota(s) com material não conferido" e a legenda das três
  camadas. A pendência de material continua visível na aba "Documentos de origem" (I-6).

## Redesenho da NPP — abas + federal agregado por código: FEITA (2026-06-03) — federal superado pelo "por nota" acima

Referência: tela "Grupo de Imposto" do Cosmos MPU. Detalhe da NPP reorganizado em
**cabeçalho de identificação** (sempre visível) + **duas abas**: "Documentos de origem"
(notas + importar) e "Grupos de impostos". Na aba de impostos, três grupos rotulados —
**INSS**, **Tributos federais**, **ISS**:
- **Tributos federais agregados por código de receita** (linha-resumo estilo "TRIB FED":
  `6190 · 9,45% · N docs · Σ destaque · X de Y validados`), que **expande** (`<details>`) para
  validar IR/CSLL/COFINS/PIS por nota. Agrupamento **automático** (o sistema deriva da nota +
  contrato; o operador não monta itens como no Cosmos).
- **INSS e ISS por nota** (ISS com município). Validação **continua por `(chave, tributo)`**.
Abas e federal são progressive enhancement (abas = links `?aba=`; federal = `<details>` nativo).
**Só apresentação** — nenhum invariante tocado (somas = conferência I-2; nada adotado I-3;
gravação inalterada I-4; dispensado/indefinido em bucket visível I-6). 68 testes verdes.
Plano: o federal etiqueta cada achado com o código (`tronco/retencao_federal.py`); a agregação
e a aba vivem em `tronco/app.py` (`_agregar_federal`, `_federal_agregada_pct`, `npp_detalhe`).

**Próxima fase (decidida, não implementada):** operacionalização do federal por material —
contrato com **duas regras** (6190 sem material / 6147 com material), roteando cada nota pela
**marcação humana** de material (I-4); validação segue por `(chave, tributo)`.

  **Hub-dashboard: descartado (decisão do humano, 2026-06-03).** A ideia original (hub vira
  painel com líquido pendente / tributos a validar somando NPPs / NPPs prontas p/ exportar) foi
  recusada: a jornada é **finita e fechada por NPP** (abre → importa → confere → exporta/paga),
  sem estado de pendência acumulada entre sessões que um painel de acompanhamento resolveria; e
  a agregação de valores entre NPPs esbarrava em I-2 (decisão #3). O hub segue orientado à ação
  por NPP, como está.

## Decisões em aberto (resolver com o humano, não sozinho)

1. **Layout da NFS-e:** só padrão nacional, ou chegam municípios em layout antigo
   (Abrasf/Ginfes/Betha)? O segundo caso adiciona outra biblioteca e outro parser.
2. ~~**Vínculo de contrato**~~ → **RESOLVIDO** pela modelagem NPP: vínculo explícito
   nota → NPP → contrato, escolhido pelo operador (substitui a heurística por CNPJ).
3. ~~**Somatório na consolidação**~~ → **RESOLVIDO**: o líquido/totais somam **valores
   validados pelo operador** (não destaque cru), o que tira a tensão com o I-2.
4. **Destino de exportação:** quando e como plugar o Google Sheets real (OAuth,
   conta de serviço?).
5. ~~**Como a tela é entregue / backup e sincronização**~~ → **RESOLVIDO**: app local por
   máquina (confirmado); backup e sincronização entre máquinas via **snapshot JSON no Google
   Drive** — **backup pessoal por operador** (config compartilhada, trabalho restaurável) e
   **transporte manual** na Fase A (API só na Fase B, junto da #4). Detalhe em
   `docs/planos/backup-e-sincronizacao.md`.
6. **Lista final de campos** por tipo — refinar contra XMLs reais.
7. ~~**NF-e e valor líquido**~~ → **RESOLVIDO**: NF-e tem retenção **federal**
   (IR/CSLL/COFINS/PIS, IN 1234/2012) quando o fornecedor **não** é optante do Simples;
   optante → dispensa, líquido = bruto. INSS/ISS **não se aplicam** à NF-e. Mesmo fluxo de
   validação da NFS-e, só muda o conjunto de tributos.
8. ~~**Reset apaga o cadastro do operador?**~~ → **RESOLVIDO**: **não apaga**;
   preservação/portabilidade do operador definidas na etapa de backup e sincronização — o
   `operador.sqlite` fica fora do pacote da equipe e só entra no escopo `pessoal`. Detalhe em
   `docs/planos/backup-e-sincronizacao.md`.
9. ~~**Suporte federal da NF-e — compartilhar ou espelhar?**~~ → **RESOLVIDO**: NF-e tem
   **paridade total** com a NFS-e (sugestão + validação). A regra federal (IN 1234/2012)
   vira módulo **comum** `tronco/retencao_federal.py`, chamado pelos dois galhos — comum =
   infraestrutura, sem dependência galho↔galho (respeita a "forma" do `01`).
10. **NPP de tipos mistos** (NFS-e + NF-e na mesma NPP) **é suportada**: bruto = soma de
    todas; líquido = Σbruto − Σretenções validadas; federal agrega os dois tipos, INSS/ISS
    só NFS-e. Pendente só o **layout do artefato de exportação misto** (seção por tipo) —
    detalhe de implementação, não muda os totais.

## Backlog inicial — RASCUNHO, edite

> Agrupado por tema. Cada item deve, ao ser pego, passar pelo protocolo do CLAUDE.md
> (declarar invariantes tocados antes de codar). A coluna "toca" ajuda a lembrar.

### A. Endurecimento para dado real
- [ ] Trocar `ExportadorCsvLocal` por exportador Google Sheets (planilha nova). *(toca I-5)*
- [ ] Tirar `secret_key` fixa e `debug=True`; configuração via ambiente.
- [ ] Definir onde mora o SQLite e política de backup. *(toca I-1, I-4)* — política de
      backup/sincronização planejada em `docs/planos/backup-e-sincronizacao.md` (snapshot
      JSON por operador); falta decidir o **local de moradia** do SQLite em produção.
- [ ] Ingestão de XML real: validar contra os bindings, varrer campos que rendam objeto. *(toca I-2, I-6)*

### B. NFS-e e variações
- [ ] Confirmar/decidir suporte a layout municipal antigo. *(decisão #1)*
- [ ] Refinar lista de campos contra XMLs reais. *(decisão #6)*

### C. Vínculo de contrato e consolidação
- [ ] Definir identificador de contrato e substituir a heurística atual. *(decisão #2)*
- [ ] Decidir tratamento do somatório na consolidação. *(decisão #3, toca I-2)*

### D. UI / jornada do operador
- [ ] (seus itens de melhoria de UI entram aqui)

### E. Fase 2
**E1 — Validação humana (EM ESCOPO desde 2026-06-02, via plano NPP):**
- [ ] Operador confirma/retifica os valores de retenção por tributo (toggle + campo),
      persistido com autor+data; líquido sobre validados. *(toca I-2, I-3, I-4, I-6)*

**E2 — Apuração por regra (FORA DE ESCOPO — não começar; exige decisão humana explícita):**
- [ ] Estruturar regras de retenção ditadas pelo especialista, uma a uma. *(toca I-3)*
- [ ] Usar a marcação de material como input da apuração automática. *(toca I-3, I-4)*

## Sugestão de primeiro passo no Claude Code

1. `git init` no repositório (hoje não há git) e primeiro commit do estado atual.
2. Confirmar que `uv run pytest` dá 9/9 na sua máquina — é o sinal de que o
   ambiente está sadio.
3. Pegar **um** item do backlog, rodar o protocolo do CLAUDE.md, e só então codar.
