# Contrato JSON do Relatório Passivo (build_passivo.py)

Um JSON por fundo e por dia. Percentuais são **frações** (0,0105 = 1,05 %), exceto os gráficos por faixa
(`participacao_pf_pj.*`, `cotas_faixa.pf_faixa/pj_faixa/cotistas`), que ficam em **pontos percentuais**
(4,96 = 4,96 %) como saem do notebook. Valores monetários em **R$ mil** onde indicado. O build formata tudo
em pt-BR com arredondamento igual ao do Excel (half away from zero).

| Campo | Tipo / unidade | Origem no notebook (`Passivo_<FUNDO>.ipynb`) | Origem na .xlsm (legado) |
|---|---|---|---|
| `fundo.ticker` | `"GARE11"` ou `"GAME11"` | constante | nome do arquivo |
| `data` | `"DD/MM/AAAA"` | `dia` | `BASE_TABELAS!C2` |
| `highlights.preco_fech` | R$ | `tab_precos['FEC']` | `BASE_TABELAS!C7` |
| `highlights.preco_max` / `preco_min` | R$ | `tab_precos['MAX']` / `['MIN']` | `F7` / `G7` |
| `highlights.fech_d1` | R$ | linha do pregão anterior em `gare_precos`/`game_precos` | `BASE_TABELAS!D7` |
| `highlights.preco_med` | R$ | `tab_precos['MED']` | `DADOS_BROADCAST!W10` (GARE) / `W9` (GAME) |
| `highlights.var_pmxpf` | fração | `(fech − med) / med` | `TABELA_HIGHLIGHT!T5` |
| `highlights.variacao` | fração (2 casas na página) | `(fech − fech_d1) / fech_d1` | `BASE_TABELAS!E7` |
| `highlights.var_ifix_seg` | fração | **só na .xlsm** → `passivo_relatorio.economatica_planilha()` (média dos peers do segmento; confere que a DATA salva na planilha é o dia do relatório) | `BASE_TABELAS!H7` |
| `highlights.var_ifix` | fração | banco `corretoras_peers` → `passivo_relatorio.var_ifix_banco(dia)` (`raw.volume_preco`, ticker `IFIX`, fechamento D-1 × pregão anterior) | `DADOS_BROADCAST!V10` |
| `highlights.vol_total_mm` | R$ MM (2 casas) | `corretoras_dia['compra_vtt'].sum() / 1e6` | `BASE_TABELAS!L11/1e6` |
| `highlights.vol_short_mm` | R$ MM (GARE11) | `tab_short['Volume Short'] / 1e6` | `C9/1e6` |
| `highlights.taxa_short` | fração (GARE11) | `tab_short['Taxa Short'] / 100` | `D9/100` |
| `highlights.volume_b3` / `daytrade` | fração | `tab_<FUNDO>_b3xDT['B3']` / `['DT']` | `J7` / `K7` |
| `market_maker.top_sold[]` | 7 + Others: `nome, volume (R$ mil), part_dia, part_mes, preco_medio` | `corretoras_dia` (venda_*), `corretoras_mes['venda']` | `TABELA_MKM` C8:G15 |
| `market_maker.top_bought[]` | idem (compra_*) | `corretoras_dia`, `corretoras_mes['compra']` | `TABELA_MKM` I8:M15 |
| `market_maker.saldo[]` | até 8 mais negativos: `nome, saldo (R$ mil)` | `corretoras_dia['saldo_vtt']` crescente | `TABELA_MKM` O8:P15 |
| `participacao_pf_pj` | `faixas[10]`, `venda_pf[10]`, `venda_pj[10]`, `compra_pf[10]`, `compra_pj[10]` (p.p.) | `graf1` → `participacao_pf_pj()` | — (PNG `VENDA/COMPRA_PF_E_PJ.png`) |
| `vendedores.lista[]` / `compradores.lista[]` | 10: `nome, cat_antiga, pf_pj, valor (R$ mil), cat_atual` (+ `gare15`, `galg15` no GARE11) | `TOP10_Venda` / `TOP10_Compra` → `top10()` | `TABELAS_C_V` |
| `vendedores.total` / `compradores.total` | R$ mil | soma | `G19` / `O19` |
| `cotas_faixa.pf_faixa[10]` / `pj_faixa[10]` | p.p. de cotas | `qtde_cotas['% TOTAL']` | — (PNG `COTAS_POR_CATEGORIA.png`) |
| `cotas_faixa.cotistas[10]` | p.p. de cotistas | `qtde_cotistas['% COTISTAS']` | — |
| `cotas_faixa.pf` / `pj` | fração | `tab_<FUNDO>_b3xDT['PF']` / `['PJ']` | `L7` / `M7` |
| `cotas_faixa.mov.entrada_dia` / `saida_dia` | int | `novos_cotistas` / `zeraram` | `DADOS_BROADCAST!W5` / `X5` |
| `cotas_faixa.mov.entrada_mes` / `saida_mes` | int (acumulado do mês, dia incluso) | `mov_cotistas_mes(passivo_relatorio.historico_var_cotistas(engine, ticker), dia, novos_cotistas, zeraram)` — Var_Cotistas é compartilhada GARE11/GAME11, filtrar por `fundo` | `W7` / `X7` |
| `cotas_faixa.mov.total` | int | `Tcotistas` | `V5` |
| `cotas_faixa.maiores[]` | 15: `nome, categoria, valor (R$ mil = cotas × fech / 1.000)` | `TOP15_Real_excel` | `TABELA_POSICOES` F8:H22 |

## Regras de negócio (todas em `passivo_json.py`)
- Market Maker: ordena por volume do lado; 7 primeiras + **Others** (soma do resto; PART/MÊS = 1 − soma das 7; preço médio = média das restantes com preço > 0). PART/MÊS é a participação no **mês anterior**; corretora sem mês = 0.
- SALDO: 8 saldos mais negativos; o build só imprime os que, em R$ mil inteiro, ficam < 0 (sem zeros).
- 10+: categoria antiga = `NC` quando `NOVOS_COTISTAS == 'NC'`; valores ÷ 1.000; TOTAL = soma. Faixas normalizadas (`0-1K` → `0-1k`).
- Gráfico PF/PJ: cada lado soma 100 % (venda ÷ total vendido; compra ÷ total comprado), 2 casas.
- Concentração por faixa: rótulo só a partir de 0,5 %; cotistas com 1 casa.
- 15 maiores: `COTAS × preço de fechamento / 1.000`.

## Formatação na página (build_passivo.py)
VARIAÇÃO 2 casas · VAR IFIX / VAR IFIX TIJOLO-PAPEL / VAR PMxPF / TAXA SHORT 1 casa · VOL TOTAL e VOL SHORT 2 casas ·
VOLUME B3 / DAYTRADE inteiros · volumes e valores em R$ mil inteiros · nomes longos com reticências pela largura da coluna.
Ajuste vertical automático (fator k ≤ 1,6) até o conteúdo chegar ao pé da A4, sempre 1 página.

## Regressão 14/10/2026 (rodada em 2026-10-20, células finais dos notebooks)
- GARE11: `verify` 130/130, 1 página. GAME11: `verify` 112/112, 1 página. Highlights, Market Maker, 10+, 15 maiores,
  PF/PJ no volume e cotistas por faixa idênticos aos JSONs de `exemplos/`.
- **Única diferença conhecida e aceita**: `cotas_faixa.pj_faixa` nas faixas com valor **abaixo de 0,5 %** (GARE11: 1k-5k a
  500k-1M; GAME11: 5k-20k a 50k-100k e 1M-3M). Os exemplos trazem zeros (ou 0,25/0,20) onde o notebook calcula 0,01–0,48 %.
  O notebook está certo (são PJs reais nessas faixas, ex.: GAME11 tem 0,48 % das cotas com PJs de 1M-3M); os exemplos foram
  montados sem esses valores porque o gráfico só rotula a partir de 0,5 %. Nada muda no PDF: barras abaixo de 0,5 % não têm
  rótulo e medem menos de um pixel.
- Histórico do GAME11 em `Var_Cotistas` foi carregado em 2026-10-20 a partir da aba DADOS_BROADCAST_COTISTAS (I:M) da planilha
  MACRO (321 dias, 01/07/2025 a 13/10/2026, `total` NULL). Sem ele o acumulado do mês saía só com o dia.
