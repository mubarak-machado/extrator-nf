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

**Próximo: passo 7 (UI) — começar em sessão nova** (janela de contexto), fatiado em
**7a** (bootstrap do operador + CRUD da NPP + importação escopada), **7b** (detalhe em duas
seções + validar/retificar), **7c** (exportação por NPP + remoção do fluxo
individual/consolidado). Depois o **passo 8** (reset). Detalhe no plano.

## Mudança de fase — 2026-06-02

O projeto **cruzou para a Fase 2**, mas só na metade de **validação/aprovação humana**
(I-3): o operador passa a **confirmar ou retificar** os valores de retenção destacados na
nota (o destaque pode estar equivocado), e é isso que alimenta o **valor líquido confiável**.
A **apuração/aplicação autônoma de regra pelo software continua fora de escopo** — o
software exibe destaque (Fase 1) e sugestão (`conferir_retencao`, só leitura) e **registra
a decisão humana** (persistida com autor+data, I-4, no padrão de `tronco/marcacoes.py`).
Detalhe em `docs/planos/modelagem-npp.md` (§5–§6). Memórias: `fase2-validacao-humana`,
`fronteira-fase1-fase2`.

## Decisões em aberto (resolver com o humano, não sozinho)

1. **Layout da NFS-e:** só padrão nacional, ou chegam municípios em layout antigo
   (Abrasf/Ginfes/Betha)? O segundo caso adiciona outra biblioteca e outro parser.
2. ~~**Vínculo de contrato**~~ → **RESOLVIDO** pela modelagem NPP: vínculo explícito
   nota → NPP → contrato, escolhido pelo operador (substitui a heurística por CNPJ).
3. ~~**Somatório na consolidação**~~ → **RESOLVIDO**: o líquido/totais somam **valores
   validados pelo operador** (não destaque cru), o que tira a tensão com o I-2.
4. **Destino de exportação:** quando e como plugar o Google Sheets real (OAuth,
   conta de serviço?).
5. **Como a tela é entregue** em produção (app local por servidor — confirmado; backup e
   sincronização entre máquinas ficam para depois).
6. **Lista final de campos** por tipo — refinar contra XMLs reais.
7. ~~**NF-e e valor líquido**~~ → **RESOLVIDO**: NF-e tem retenção **federal**
   (IR/CSLL/COFINS/PIS, IN 1234/2012) quando o fornecedor **não** é optante do Simples;
   optante → dispensa, líquido = bruto. INSS/ISS **não se aplicam** à NF-e. Mesmo fluxo de
   validação da NFS-e, só muda o conjunto de tributos.
8. ~~**Reset apaga o cadastro do operador?**~~ → **RESOLVIDO**: **não apaga**; detalhes
   (preservação/portabilidade) ficam para a etapa de backup e sincronização.
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
- [ ] Definir onde mora o SQLite e política de backup. *(toca I-1, I-4)*
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
