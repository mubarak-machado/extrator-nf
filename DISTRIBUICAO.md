# Distribuição — executável Windows (piloto)

Como empacotar o Extrator NF num **executável de duplo-clique** para um colega usar
no Windows, sem instalar Python nem terminal. Esta é uma versão **de piloto**: serve
para **importar notas e conferir na tela** (Fase 1, extração fiel). Veja os limites
no fim.

## O que esta branch prepara

- **`tronco/config.py`** — separa *recursos* (templates/static/exemplos, só-leitura,
  embutidos no .exe) de *dados* (os `*.sqlite` e as exportações, que vão para uma
  pasta **gravável e persistente** do usuário). Sem isso, o app empacotado perderia
  os dados a cada execução/atualização.
- **`debug` desligado** por padrão e **secret key** gerada (não mais fixa no código).
- **`run_app.py`** — ponto de entrada: sobe o servidor em `127.0.0.1`, **abre o
  navegador sozinho** e mantém uma janelinha de console aberta.
- **`extrator-nf.spec`** — receita do PyInstaller (onefile).
- **`.github/workflows/build-windows.yml`** — builda o `.exe` na nuvem (runner
  Windows), porque o PyInstaller **não faz cross-compile** (de um Mac não sai `.exe`).

## Onde ficam os dados do usuário

No Windows empacotado: `%LOCALAPPDATA%\ExtratorNF\` (ex.:
`C:\Users\<usuário>\AppData\Local\ExtratorNF`). Lá vivem `notas.sqlite`,
`contratos.sqlite`, `registro_exportacao.sqlite`, `marcacoes.sqlite`,
`catalogo_federal.sqlite`, a `secret.key` e a pasta `exportacoes/`.

**Backup** = copiar essa pasta. **Atualizar o app** = trocar o `.exe`; os dados ficam.
Para apontar os dados para outro lugar (pen drive, pasta de rede), defina a variável
de ambiente `EXTRATOR_NF_DATA`.

## Como gerar o .exe (mantenedor)

### Caminho recomendado — GitHub Actions (sem precisar de Windows)

1. Configure o remoto e suba a branch:
   ```
   git push --set-upstream origin release/v0.1-piloto
   ```
2. Crie uma tag de versão e empurre:
   ```
   git tag v0.1.0-piloto
   git push origin v0.1.0-piloto
   ```
3. O workflow builda em `windows-latest` e **anexa `ExtratorNF.exe` ao release**.
   Baixe de lá (ou da aba *Actions → artefatos*) e envie ao colega.
   Sem tag, dá para rodar manualmente em *Actions → Build Windows → Run workflow*.

### Caminho manual (se tiver um Windows à mão)

```
uv sync --group empacotamento
uv run pyinstaller extrator-nf.spec
```
Saída em `dist\ExtratorNF.exe`.

## Como o colega usa (Windows, não-técnico)

1. Salvar o `ExtratorNF.exe` (ex.: na Área de Trabalho) e dar **duplo-clique**.
2. Na **primeira vez**, o Windows pode mostrar o aviso azul do *SmartScreen*
   (o programa não tem assinatura digital paga). Clicar em **“Mais informações” →
   “Executar assim mesmo”**. O antivírus corporativo pode pedir liberação — é
   esperado para `.exe` não assinado.
3. Abre uma janelinha preta (“Extrator NF está rodando — feche para encerrar”) e o
   **navegador abre sozinho** na tela do programa.
4. Usar normalmente: **Importar** as notas (XML) e **conferir** na tela.
5. Para fechar, **fechar a janelinha preta**.

## Limites desta versão (deixar claro ao colega)

- **Importar + conferir na tela** está pronto e é fiel à nota (Fase 1).
- **A exportação ainda é um CSV local de demonstração**, não a planilha/integração
  real — não usar o arquivo exportado como artefato de pagamento ainda.
- Os XMLs de exemplo que acompanham o app são **sintéticos** (valores fabricados).
- App **local de um usuário**, sem login; roda só na máquina dele, não na rede.
- Se a política do órgão bloquear `.exe` não assinado, o plano B é distribuir o
  código + um lançador e instalar o `uv` uma vez (mais fricção, mas passa).
