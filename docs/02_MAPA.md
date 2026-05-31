# 02 — Mapa de Implementação e Protocolo para o Claude Code

> Conecta os princípios (`00`) e a arquitetura (`01`) ao trabalho concreto. Muito
> aqui é negociável (bibliotecas, pastas, ordem fina). O **protocolo de planejamento**
> da seção final não é.

---

## 1. Ordem de construção

A ordem reflete a regra "tronco primeiro, galhos em paralelo depois".

| # | Etapa | Observação |
|---|-------|-----------|
| 0 | **Processo: garantir XML na origem** | Não é código. Conseguir que fornecedores/emitentes enviem XML. O padrão nacional da NFS-e (obrigatório desde jan/2026) ajuda. Roda em paralelo a tudo. |
| 1 | **Tronco — ingestão + identificação de tipo** | Lê XML, decide se é NF-e ou NFS-e, roteia para o galho certo. |
| 2 | **Tronco — idempotência (SQLite)** | Antes de qualquer exportação (I-1). |
| 3 | **Tronco — exibição em tela** | Destino padrão; onde o usuário confere e (na NFS-e) marca material aplicado. |
| 4 | **Tronco — exportador Google Sheets** | Cria planilha nova (I-5). Plugável. |
| 5a | **Galho NF-e — Fase 1 (extração)** | Em paralelo com 5b. Campos da seção 3 do doc `01`. |
| 5b | **Galho NFS-e — Fase 1 (extração)** | Em paralelo com 5a. Inclui detecção do campo de material (exibir, não interpretar). |
| 6 | **Fase 2 — sugestão de retenção** | Só depois da Fase 1 provada. Regras ditadas pelo especialista humano, uma a uma. Fora do escopo atual. |

> A Fase 1 (etapas 1–5) é o foco. A etapa 6 está registrada como objetivo declarado
> para que o "depois" tenha endereço — mas não se constrói agora.

---

## 2. Esboço de estrutura (negociável)

```
extrator-nf/
├── docs/
│   ├── 00_PRINCIPIOS.md
│   ├── 01_ARQUITETURA.md
│   └── 02_MAPA.md          ← este arquivo
├── tronco/
│   ├── ingestao.py         ← lê XML, identifica tipo, roteia
│   ├── idempotencia.py     ← RegistroDeExportacao (SQLite)
│   ├── tela.py             ← exibição + marcação de material (NFS-e)
│   └── exportador_sheets.py← cria planilha nova
├── galho_nfe/
│   ├── modelo.py           ← registro plano NF-e
│   └── extracao.py         ← Fase 1
│   └── (retencao.py)       ← Fase 2, futuro
├── galho_nfse/
│   ├── modelo.py           ← registro plano NFS-e
│   ├── extracao.py         ← Fase 1 (inclui detecção de material)
│   └── (retencao.py)       ← Fase 2, futuro
└── tests/
```

**Candidatos de biblioteca** (verificar versão atual ao usar): `nfelib` (lê NF-e e
NFS-e nacional a partir dos XSD oficiais), `google-api-python-client` (Sheets),
`sqlite3` (stdlib). Linguagem: Python, pelo ecossistema fiscal brasileiro.

---

## 3. Decisões em aberto (resolver com o humano, não sozinho)

- **Lista final de campos** por tipo — refinar contra XMLs reais (a seção 3 do `01` é
  ponto de partida).
- **Variações de layout da NFS-e** — se chegam só no padrão nacional ou se há
  municípios em layout antigo (afeta o parser do galho NFS-e).
- **Como a tela é entregue** (app local? web interna?) — afeta etapa 3.
- **Regras de retenção** — toda a Fase 2; ditadas pelo especialista, uma a uma.

---

## 4. Protocolo de planejamento de feature (NÃO negociável)

Ao planejar ou implementar qualquer feature, o Claude Code deve, nesta ordem:

1. **Reler `00_PRINCIPIOS.md`.** Listar os invariantes (I-1…I-6) que a feature toca.
2. **Declarar como cada invariante tocado é respeitado** — por escrito, antes de codar.
3. **Conferir contra `01_ARQUITETURA.md`**: a feature respeita tronco vs galho? Está
   na fase certa (não está fazendo apuração na Fase 1)?
4. **Identificar decisões em aberto** (seção 3) das quais a feature depende. Se
   depende de uma decisão não tomada → **perguntar ao humano**, não escolher sozinho.
5. **Só então** produzir plano e código.
6. **Verificar ao fim:** nenhum invariante foi quebrado por conveniência? Nenhuma
   interpretação tributária vazou para a Fase 1?

> Atenção especial: a fronteira Fase 1 / Fase 2 é fácil de borrar. Qualquer código que
> "decida" algo tributário (o que reter, se há material aplicado) pertence à Fase 2 e
> exige aprovação humana (I-3). Na dúvida, detectar e exibir — nunca decidir.
