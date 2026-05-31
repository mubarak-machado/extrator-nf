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

## Decisões em aberto (resolver com o humano, não sozinho)

1. **Layout da NFS-e:** só padrão nacional, ou chegam municípios em layout antigo
   (Abrasf/Ginfes/Betha)? O segundo caso adiciona outra biblioteca e outro parser.
2. **Vínculo de contrato:** hoje a consolidação agrupa por *prestador + competência*
   (heurística), porque o número do contrato do órgão **não vem no XML**. Como
   amarrar o contrato de verdade? (identificador do lado do órgão, entrada manual?)
3. **Somatório na consolidação:** somar destaques é apresentação, mas encosta em I-2.
   Manter como "soma de conferência" ou não totalizar? (decisão sua)
4. **Destino de exportação:** quando e como plugar o Google Sheets real (OAuth,
   conta de serviço?).
5. **Como a tela é entregue** em produção (app local? web interna?).
6. **Lista final de campos** por tipo — refinar contra XMLs reais.

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

### E. Fase 2 (só depois da Fase 1 provada — não começar agora)
- [ ] Estruturar regras de retenção ditadas pelo especialista, uma a uma. *(toca I-3)*
- [ ] Usar a marcação de material como input da apuração. *(toca I-3, I-4)*

## Sugestão de primeiro passo no Claude Code

1. `git init` no repositório (hoje não há git) e primeiro commit do estado atual.
2. Confirmar que `uv run pytest` dá 9/9 na sua máquina — é o sinal de que o
   ambiente está sadio.
3. Pegar **um** item do backlog, rodar o protocolo do CLAUDE.md, e só então codar.
