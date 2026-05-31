# 01 — Visão de Arquitetura

> A forma do sistema: um **tronco comum** construído uma vez, e **dois galhos
> independentes** (NF-e e NFS-e) sobre ele. Conteúdo de design; nomes de
> componentes são negociáveis, a forma não.

---

## 1. A forma geral: tronco e galhos

```
                    ┌─────────────────────────────────────┐
                    │           TRONCO COMUM               │
                    │  (construído UMA vez, antes dos galhos)│
                    │                                       │
                    │  • ingestão de XML                    │
                    │  • identificação do tipo (NF-e/NFS-e) │
                    │  • idempotência por chave (I-1)       │
                    │  • exibição em tela                   │
                    │  • exportação p/ planilha nova (I-5)  │
                    └───────────────┬───────────────────────┘
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
        ┌───────────────────┐             ┌───────────────────────┐
        │   GALHO NF-e       │             │   GALHO NFS-e          │
        │   (mercantil)      │             │   (serviço)            │
        │                    │             │                        │
        │ Fase 1: extração   │             │ Fase 1: extração       │
        │ Fase 2: sugestão   │             │ Fase 2: sugestão       │
        │  de retenção       │             │  de retenção           │
        │  (lógica simples)  │             │  (lógica complexa,     │
        │                    │             │   LC 116/2003)         │
        └───────────────────┘             └───────────────────────┘
```

**Regra de construção do "paralelo":** o tronco vem primeiro, inteiro. Só depois os
dois galhos avançam em paralelo. "Paralelo" não significa construir duas leituras de
XML ou dois exportadores — significa que, sobre o tronco pronto, os dois galhos
tributários evoluem independentes e sem se interferir.

---

## 2. As duas fases (vale para os dois galhos)

| | **Fase 1 — Extração fiel** | **Fase 2 — Sugestão de retenção** |
|---|---|---|
| O que faz | Lê XML, extrai campos, exibe, exporta | Sugere retenções sob regras do especialista |
| Compromisso tributário | **Nenhum** (I-2) | Sugere, humano aprova (I-3) |
| De onde vêm as regras | — | Ditadas pelo especialista humano, uma a uma |
| Entrega valor sozinha? | **Sim** | Depende da Fase 1 |
| Retenções destacadas | Lidas como "destaque do emitente" | Comparáveis à regra (sinaliza divergência) |

A Fase 1 é o foco atual. A Fase 2 está registrada como objetivo, fora do escopo de
agora. A extração sempre precede a sugestão dentro de cada galho.

---

## 3. Os campos da Fase 1, por tipo (os quatro blocos marcados)

> Lista de partida, a refinar com os XMLs reais. Todos são campos de cabeçalho,
> escalares — **uma nota = uma linha** (sem itens, sem parcelas).

### Galho NF-e (mercantil)
- **Identificação:** chave de acesso (44díg, = chave de idempotência), número, série,
  modelo (55/65), data de emissão, natureza da operação.
- **Emitente:** CNPJ, razão social, **indicador de optante pelo Simples Nacional**
  (decisivo para a Fase 2: optante → dispensa LC 123/2006; não optante → base p/ a
  sugestão de 5,85% no cód. 6147), inscrição estadual, município/UF.
- **Destinatário (o órgão):** CNPJ, razão social.
- **Valores totais:** valor total da nota, valor dos produtos, descontos, outras
  despesas.
- **Tributos (como destacados):** ICMS, IPI, PIS, COFINS, valor aproximado de
  tributos.

### Galho NFS-e (serviço)
- **Identificação:** número da NFS-e, código de verificação, chave (padrão nacional),
  data de emissão.
- **Prestador:** CNPJ, razão social, inscrição municipal, **indicador de optante pelo
  Simples**, município do prestador.
- **Tomador (o órgão):** CNPJ, razão social.
- **Serviço (decisivo para Fase 2):** discriminação, **código do serviço (lista LC
  116/2003)**, **local da prestação** e **local do prestador** (determinam o
  tratamento do ISSQN), código de tributação municipal.
- **Valores e retenções (como destacadas):** valor dos serviços, deduções, base de
  cálculo, ISS (alíquota, valor, indicador de retido), retenções federais (IR, PIS,
  COFINS, CSLL, INSS), valor líquido.
- **Campo especial — material aplicado:** texto livre não padronizado (ver doc `00`,
  "Caso especial"). Fase 1 detecta, exibe e o usuário marca; nunca interpreta.

---

## 4. O modelo de dados (plano, por galho)

Como não há itens nem parcelas, cada nota é um **registro plano**. Cada galho tem seu
próprio modelo (Caminho B), com os campos da seção 3. Campos de retenção carregam
rótulo de procedência: `destaque_emitente` (lido na Fase 1) vs, futuramente,
`sugestao_regra` (Fase 2). A marcação de material aplicado é um campo persistido do
registro (I-4), não estado de tela.

---

## 5. Idempotência (tronco, vale para os dois)

`RegistroDeExportacao` em SQLite: a chave de acesso é PRIMARY KEY (o banco recusa
duplicata por construção). Antes de montar lote: nota já registrada → exibida como
JÁ_EXPORTADA (não é erro, é status). Gravação no registro **após** confirmação de
sucesso da exportação, nunca antes.
