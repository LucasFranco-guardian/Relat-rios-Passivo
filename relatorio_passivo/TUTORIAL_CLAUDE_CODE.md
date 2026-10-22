# Tutorial para o Claude Code — Relatório Passivo 100 % em Python

> Para quem lê isto (Claude Code): este arquivo é a especificação da tarefa. Leia-o inteiro antes de
> tocar em qualquer código. O layout do PDF já está aprovado pelo Lucas e **não é objeto desta tarefa**;
> a tarefa é ligar a lógica dos notebooks ao renderizador, eliminando Excel, macro VBA e PowerPoint.

## 1. Onde estamos e aonde vamos

**Hoje** (notebooks `Passivo_GARE.ipynb` e `Passivo_GAME.ipynb` nesta pasta):
1. seções `# 1.` a `# 37.` (números dos títulos markdown) calculam tudo a partir das posições da B3 (D‑1 × D‑2), preços, short, grupos e listas de oferta;
2. seção `# 40.` gera três PNGs (matplotlib) e cola no `_base.pptx` via python‑pptx;
3. seção `# 41.` busca corretoras no Postgres (`corretoras_b3.py`) e cola tabelas na `.xlsm` via xlwings;
4. fora do Python: abre‑se a `.xlsm`, roda‑se a macro `CopiarImagensDePlanilhasParaPowerPoint*`, salva‑se o
   `.pptx` do dia e exporta‑se o PDF.

**Amanhã**: as mesmas células 1–37 + `corretoras_b3.py` alimentam `passivo_json.montar_json(...)`, que devolve um
dicionário no contrato de `README_contrato_json.md`; `gerar_passivo.gerar(dados, pasta)` escreve
`Passivo_<TICKER>_DD.MM.AAAA.pdf`, confere cada número contra o PDF (`verify_passivo.py`) e salva um PNG de preview.
Zero Excel, zero PowerPoint, zero macro.

Os arquivos do novo pipeline estão em `relatorio_passivo/` (ao lado dos notebooks):

| Arquivo | Papel |
|---|---|
| `build_passivo.py` | JSON → HTML → PDF A4 (WeasyPrint). Layout aprovado. **Não altere sem pedir ao Lucas.** |
| `passivo_json.py` | DataFrames do notebook → JSON. Todas as regras de negócio da planilha, função a função. |
| `gerar_passivo.py` | `gerar(dados, pasta)`: build + verify + preview em uma chamada. |
| `verify_passivo.py` | Checklist: cada valor do JSON precisa aparecer no texto do PDF, formatado em pt‑BR. |
| `extract_passivo.py` | Legado: lê a `.xlsm _MACRO` e gera o JSON (sem os gráficos). Serve de referência cruzada. |
| `README_contrato_json.md` | O contrato: campo → unidade → variável do notebook → célula da planilha. |
| `assets/` | Fontes (Avenir Next LT Pro, Geometos Rounded), logos e ícones Phosphor. Já embutidos — nada a instalar. |
| `exemplos/` | JSONs, PDFs e checklists de 14/10/2026 aprovados — são o **teste de regressão**. |

## 2. Setup

```bash
pip install weasyprint pymupdf openpyxl pandas
```
WeasyPrint no Windows precisa do runtime GTK3 (Pango/Cairo): instale o
[GTK3 runtime for Windows](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)
ou rode o pipeline no WSL. Teste de fumaça (deve imprimir `k=…`, `ok …` e `130/130 OK`):

```bash
cd relatorio_passivo
python build_passivo.py exemplos/dados_Passivo_GARE11_14.10.2026.json /tmp/teste.pdf
python verify_passivo.py exemplos/dados_Passivo_GARE11_14.10.2026.json /tmp/teste.pdf
```

## 3. O que fazer — passo a passo

### Passo 1 — Transformar o notebook em função (sem mudar a lógica)
Crie `passivo_pipeline.py` com uma função por fundo, `calcular_gare11(dia)` e `calcular_game11(dia)`, movendo o
código das seções `# 2.` a `# 37.` do GARE (e das seções equivalentes do GAME, que seguem a mesma ordem) **sem alterar cálculo nenhum**. A função devolve um dicionário com os
objetos que o JSON precisa:

```python
return dict(
    dia=dia,
    precos=gare_precos,              # DataFrame Data|FEC|MAX|MIN|MED|QTT (game_precos no GAME11)
    tab_short=tab_short,             # Series do dia (Volume Short, Saldo Short, Taxa Short); None no GAME11
    b3xdt=tab_GARE11_b3xDT,          # B3 | DT | PF | PJ
    corretoras_dia=corretoras_dia,   # corretoras_b3.buscar_corretoras_dia(ticker, dia)
    corretoras_mes=corretoras_mes,   # corretoras_b3.buscar_corretoras_mes(ticker, dia, pregoes=...)
    top10_venda=TOP10_Venda, top10_compra=TOP10_Compra,
    graf=graf1,                      # CATEGORIAS(int) | OPERACAO | PF_PJ | VAR_PRECO
    qtde_cotas=qtde_cotas,           # CATEGORIAS | PF_PJ | TOTAL_NOVO | % TOTAL
    qtde_cotistas=qtde_cotistas,     # CATEGORIAS | DOCUMENTO | % COTISTAS
    top15=TOP15_Real_excel,          # índice NOME | PF_PJ | CATEGORIAS | COTAS
    novos_cotistas=novos_cotistas, zeraram=zeraram, total_cotistas=Tcotistas,
)
```
Regras ao extrair:
- `dia` vira parâmetro (hoje é `datetime(2026, 10, 13)` fixo na seção `# 3.`) e os caminhos `13.10.xlsx` / `09.10.xlsx`
  passam a ser derivados do `dia` (D‑1 = `dia`, D‑2 = pregão anterior em `gare_precos['Data']`). A pasta do mês segue
  o padrão já usado: `1. ARQUIVOS B3/FORMATADOS/<GARE|GAME>/<N. MÊS>/DD.MM.xlsx`.
- `graf1` é a base dos dois lados (seção `# 25.`). Não use `graf_compra`/`graf_venda` (seções `# 28.`/`# 30.`) — eles dividem os dois
  lados pelo total de venda; `passivo_json.participacao_pf_pj` divide cada lado pelo próprio total, que é a regra aprovada.
- Não copie as seções de gráfico (`# 27.`, `# 29.`, `# 31.`), do pptx (`# 40.`) nem da colagem xlwings (`# 41.`) para a função.
- Mantenha os `print` de conferência (NOVO × ANTIGO, compra × venda, duplicados) — viram `assert`s com mensagem.

### Passo 2 — Fontes que ainda não vêm do notebook
Três campos vinham do Economatica dentro da `.xlsm` e um do histórico mensal:

| Campo | Solução imediata | Solução definitiva (sugestão) |
|---|---|---|
| `var_ifix` (IFIX D‑1 × D‑2) | `passivo_json.economatica_da_xlsm(caminho_xlsm)` lê o último valor salvo | série do IFIX via Economatica/API ou a tabela de índices do Postgres, se existir |
| `var_ifix_seg` (média da variação dos peers Tijolo/Papel) | idem | lista de peers (`DADOS_BROADCAST_COTISTAS!O5:P56`) + preços no banco → média simples das variações |
| `preco_med` | já vem de `tab_precos['MED']` | — |
| `mov.entrada_mes` / `saida_mes` | `passivo_json.mov_cotistas_mes(historico, dia, novos_cotistas, zeraram)` sobre a tabela **Var_Cotistas** do Postgres (`DATA, Entraram, Sairam`) | idem (já é definitiva) |

Enquanto a solução imediata do IFIX depender da `.xlsm`, a seção `# 41.` (xlwings) continua existindo **só** para o
Excel recalcular os links Economatica; o resto da planilha deixa de ter função. Documente isso no topo do script.

### Passo 3 — Montar o JSON e gerar o PDF
```python
from relatorio_passivo.passivo_json import montar_json, mov_cotistas_mes, economatica_da_xlsm
from relatorio_passivo.gerar_passivo import gerar

r = calcular_gare11(dia)
dados = montar_json(
    ticker="GARE11", dia=r["dia"], precos=r["precos"], tab_short=r["tab_short"], b3xdt=r["b3xdt"],
    corretoras_dia=r["corretoras_dia"], corretoras_mes=r["corretoras_mes"],
    top10_venda=r["top10_venda"], top10_compra=r["top10_compra"], graf=r["graf"],
    qtde_cotas=r["qtde_cotas"], qtde_cotistas=r["qtde_cotistas"], top15=r["top15"],
    novos_cotistas=r["novos_cotistas"], zeraram=r["zeraram"], total_cotistas=r["total_cotistas"],
    mov_mes=mov_cotistas_mes(historico_var_cotistas, r["dia"], r["novos_cotistas"], r["zeraram"]),
    economatica=economatica_da_xlsm(CAMINHO_XLSM_MACRO_GARE),
)
pdf = gerar(dados, pasta_saida)      # Passivo_GARE11_DD.MM.AAAA.pdf + Checklist + PNG
```
Saída: `Passivo_GARE11_DD.MM.AAAA.pdf` em `2. RELATÓRIOS/1. DIARIOS/GARE/PDF/<N. MÊS>/` e
`Passivo_GAME11_DD.MM.AAAA.pdf` em `2. RELATÓRIOS/1. DIARIOS/GAME/PDFs/<ano>/<N. MÊS>/` (padrão atual das pastas;
`<N. MÊS>` = número sem zero à esquerda, ponto, espaço, mês em três letras: `10. OUT`). Crie a pasta do mês se não existir.
Grave também o `dados_Passivo_<TICKER>_DD.MM.AAAA.json` ao lado do PDF — é o insumo da rodada 2 (resumos WhatsApp/e‑mail).

### Passo 4 — Linha de comando
`python rodar_passivo.py --fundo GARE11 --dia 2026-10-14` e `--fundo GAME11`; sem `--dia`, usa o último pregão com
arquivo da B3 na pasta do mês. Um `--ambos` roda os dois. Erros de insumo (arquivo da B3 ausente, banco sem o dia —
`corretoras_b3` já levanta `ValueError` com a mensagem certa) devem parar a execução com a causa na tela, nunca gerar
PDF com dado faltando.

### Passo 5 — Teste de regressão (obrigatório antes de dar por pronto)
Rode com `dia = 2026‑10‑14` e compare o JSON gerado com `exemplos/dados_Passivo_GARE11_14.10.2026.json` e
`exemplos/dados_Passivo_GAME11_14.10.2026.json` (tolerância 0,2 % nos floats; strings idênticas). Diferenças aceitas e
conhecidas: nenhuma — esses JSONs foram validados número a número contra os PDFs oficiais de 14/10. Depois rode o
`verify_passivo.py` sobre o PDF gerado: a saída tem de ser `NNN/NNN OK, páginas=1`.
Os insumos de 14/10 (`13.10.xlsx`, `09.10.xlsx` do GARE e do GAME; `gare_precos.xlsx`, `gare_short.xlsx`,
`game_precos.xlsx`) estão nas pastas que os notebooks já apontam.

### Passo 6 — Aposentar o legado
Só depois do Passo 5 verde: remova das rotinas a seção `# 40.` (pptx) e os PNGs; mantenha `corretoras_b3.py` (continua
sendo a fonte das corretoras); mantenha a seção `# 41.` apenas enquanto o IFIX vier da `.xlsm` (Passo 2). A macro VBA e os
`_base.pptx` / `_graficos.pptx` deixam de ser usados — não os apague, arquive.

## 4. Regras que não se negociam
- **Layout é decisão do Lucas.** `build_passivo.py` reproduz um layout aprovado seção a seção (cabeçalho, 01–05). Se um
  dado novo não couber, mostre o problema; não reduza fonte, não corte seção, não "melhore" o visual por conta própria.
- **Cabeçalhos e rótulos** do PDF são os da planilha (só a grafia foi corrigida: CONCENTRAÇÃO, PREÇO MÍNIMO). Unidades:
  R$ mil nas tabelas, R$ MM só em VOL TOTAL/VOL SHORT.
- **Nunca grave a `.xlsm` com openpyxl** (destrói macros, cache e calcChain). Leitura sempre `data_only=True`.
- **Números**: o JSON carrega o valor cru; quem arredonda é o build (regra do Excel). Não pré‑arredonde no pipeline.
- **1 página, sempre.** O build ajusta o respiro (k ≤ 1,6) e nunca passa de uma página; se o `verify` acusar 2 páginas,
  é bug de dado (ex.: 30 linhas no SALDO), não de layout.
- **Fale dos dados como primeira análise**: o PDF não tem versão, não tem "corrigido"; cada dia é regenerado do zero.

## 5. Critério de pronto
1. `python rodar_passivo.py --ambos --dia 2026-10-14` gera os dois PDFs sem abrir Excel nem PowerPoint.
2. JSONs iguais aos de `exemplos/` (tolerância acima) e `verify` 100 % OK nos dois.
3. Um dia novo (o último disponível) roda de ponta a ponta com o mesmo comando.
4. `README_contrato_json.md` atualizado se algum campo mudou de origem (coluna "Origem no notebook").
