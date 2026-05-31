# 00 — Princípios e Invariantes

> **Autoridade máxima do projeto.** Tudo aqui é inviolável. Detalhes de *como*
> implementar vivem nos docs `01` e `02` e são negociáveis; o que *nunca pode
> acontecer* vive aqui. Se uma tarefa parecer exigir violar um invariante, a tarefa
> está errada — pare e reporte, não contorne.

---

## Contexto em uma frase

Sistema que lê o **XML** de notas fiscais (NF-e mercantil e NFS-e de serviço),
extrai os campos relevantes para lançamento de pagamento por um órgão público
federal, exibe os dados ao usuário, e — sob demanda — exporta um lote para uma
planilha nova do Google Sheets que alimentará os sistemas de contabilização e
pagamento.

**O dado extraído sustenta uma decisão de retenção tributária.** Esta frase governa
os invariantes. O custo de um erro não é estético; é uma retenção errada, com
consequência real em órgão público.

---

## Decisões de escopo já fechadas (leia antes dos invariantes)

- **Entrada é só XML.** PDF e OCR estão fora do projeto, não como "depois" — como
  decisão. Não há cascata de fontes, não há sistema de confiança por origem.
- **Dois fluxos independentes (NF-e e NFS-e).** Não há modelo unificado. Cada tipo
  tem lógica de negócio própria; compartilham apenas o tronco comum (ver doc `01`).
- **Duas fases.** Fase 1 = extração fiel. Fase 2 = sugestão de retenção sob regras
  ditadas pelo especialista humano. A Fase 1 não depende da Fase 2 e entrega valor
  sozinha.
- **Sigilo fiscal não é restrição.** Os dados também constam em portais públicos
  (PNCP e transparência). Não há invariante de sigilo. *Porém:* envio a serviço de
  terceiros, se algum dia proposto, volta a ser decisão consciente registrada.

---

## Os invariantes (I-1 a I-6)

### I-1 — Idempotência por chave antes de qualquer exportação
Nenhuma nota entra num lote de exportação sem verificar, contra memória persistente,
se já foi exportada. Chave: a chave de acesso da NF-e (44 dígitos) ou o
identificador único da NFS-e. Duplicação inter-lote é o erro de maior custo
(pagamento em duplicidade) e o sistema existe, em parte, para impedi-lo.

### I-2 — Extração é fiel, nunca interpretativa (na Fase 1)
Na Fase 1, o sistema transcreve o que está estruturado no XML. Não decide o que
*deveria* ser retido, não calcula, não interpreta texto livre. Campos de retenção
que vêm destacados no XML são lidos **como destaque do emitente**, não como verdade
apurada — rotulados como tal, para que a Fase 2 encaixe por cima sem ambiguidade.

### I-3 — Retenção é sempre sugestão, nunca decisão automática (na Fase 2)
Quando a Fase 2 existir, toda apuração de retenção é **sugestão exibida para
aprovação humana**, acompanhada da regra de negócio que a gerou. O sistema nunca
aplica uma retenção sozinho. As regras de negócio são ditadas pelo especialista
humano; o sistema as estrutura, não as inventa.

### I-4 — Marcação humana que altera retenção é dado persistido e rastreável
Quando o usuário marca algo que afeta a apuração (ex.: "houve emprego de material"),
essa marcação é gravada junto com a nota, com autoria e data — nunca um estado
efímero de tela. Se uma retenção foi calculada com base numa marcação, a marcação
precisa estar auditável depois.

### I-5 — A extração nunca escreve em planilha preexistente
A exportação sempre cria planilha nova (ou escreve em estrutura controlada só pela
máquina). Nunca altera, reordena ou insere em planilha que humanos editam à mão.
Append-only, artefato imutável por lote.

### I-6 — Falha e ambiguidade são visíveis, nunca silenciosas
Se um campo esperado falta, se um total não fecha, ou se há texto livre ambíguo que
pode conter valor de material — o sistema **mostra**, não esconde nem chuta. Prefere
admitir "confira isto" a inventar um valor plausível. Pagamento errado é pior que
pagamento conferido.

---

## Caso especial documentado: o campo de material aplicado

Existe na NFS-e um campo de **descrição em texto livre, não padronizado**, que em
alguns casos informa o valor de material aplicado no serviço. Esse valor importa
porque afeta a base de cálculo do INSS e decide a alíquota de IR (1,2% vs 4,8%,
IN RFB 1234/2012). É o **único ponto do sistema onde o dado não é estruturado**.

Tratamento obrigatório, por fase:
- **Fase 1:** o sistema **detecta e exibe** o texto, sinalizado ("pode conter valor
  de material — confira"). **Não interpreta.** O usuário lê e **marca** se houve ou
  não emprego de material (resolve a ambiguidade "aplicado" vs "não aplicado", que é
  trivial para o humano e traiçoeira para a máquina). A marcação é persistida (I-4).
- **Fase 2:** a apuração usa a marcação do usuário como input das regras de retenção.
- **Versão futura (não agora):** dicionário de palavras-chave/combinações para
  *sugerir* a classificação — destilado dos exemplos reais que a marcação manual
  acumular, nunca adivinhado antes de ver os dados.

Nunca, em fase alguma: interpretar o texto e usar o valor automaticamente sem o
usuário ver o original.

---

## Como o Claude Code usa este documento

1. Antes de planejar qualquer feature, releia estes invariantes.
2. Ao planejar, cite quais invariantes a feature toca e como os respeita.
3. Conflito entre requisito e invariante → **o invariante vence**; reporte ao humano.
4. Estes invariantes só mudam por decisão humana explícita, datada e justificada.
