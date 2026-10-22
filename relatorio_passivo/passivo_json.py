# -*- coding: utf-8 -*-
"""
passivo_json.py
===============
Monta o JSON do Relatório Passivo (contrato em README_contrato_json.md) a partir dos
DataFrames que os notebooks Passivo_GARE.ipynb / Passivo_GAME.ipynb já produzem.
É a ponte entre o notebook e o build_passivo.py — substitui o trio xlwings → macro VBA → PowerPoint.

Uso típico (última célula do notebook, depois do TOP15_Real_excel):

    from passivo_json import montar_json, mov_cotistas_mes, economatica_da_xlsm
    dados = montar_json(
        ticker="GARE11", dia=dia,
        precos=gare_precos, tab_short=tab_short,               # GAME11: precos=game_precos, tab_short=None
        b3xdt=tab_GARE11_b3xDT,
        corretoras_dia=corretoras_dia, corretoras_mes=corretoras_mes,
        top10_venda=TOP10_Venda, top10_compra=TOP10_Compra,
        graf=graf1, qtde_cotas=qtde_cotas, qtde_cotistas=qtde_cotistas,
        top15=TOP15_Real_excel,
        novos_cotistas=novos_cotistas, zeraram=zeraram, total_cotistas=Tcotistas,
        mov_mes=mov_cotistas_mes(historico, dia),               # ou {"entrada_mes": ..., "saida_mes": ...}
        economatica=economatica_da_xlsm(caminho_destino),      # {"var_ifix": ..., "var_ifix_seg": ...}
    )
    json.dump(dados, open(f"dados_passivo_{ticker}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

Todas as regras de negócio da planilha (ranks, Others, Saldo, NC, ÷1.000, faixas) estão aqui, documentadas
função a função. Percentuais no JSON são FRAÇÕES (0,0105 = 1,05 %), exceto os três gráficos por faixa,
que ficam em pontos percentuais (4,96 = 4,96 %), como saem do notebook.
"""
from __future__ import annotations
import math
from datetime import date, datetime

import pandas as pd

FAIXAS = ["0-1k", "1k-5k", "5k-20k", "20k-50k", "50k-100k", "100k-500k", "500k-1M", "1M-3M", "3M-15M", ">15M"]
MAPEAR = {i + 1: f for i, f in enumerate(FAIXAS)}          # 1 → "0-1k" … 10 → ">15M"
N_TOP_MKM = 7           # TOP SOLD / TOP BOUGHT: 7 corretoras + Others  (planilha: RANK < 8)
N_SALDO = 8             # SALDO: até 8 corretoras mais negativas          (planilha: Q8:Q15)
N_TOP10 = 10            # 10+ VENDEDORES / COMPRADORES
N_TOP15 = 15            # 15 MAIORES POSIÇÕES


# ----------------------------------------------------------------------------- utilidades
def _f(x, default=0.0):
    try:
        v = float(x)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default

def _data(d):
    if isinstance(d, datetime): return d.date()
    if isinstance(d, date): return d
    return pd.to_datetime(d).date()

def _faixa(x):
    """Aceita 1..10, '1'..'10' ou o rótulo pronto ('0-1k'). Normaliza '0-1K' → '0-1k'."""
    if x is None or (isinstance(x, float) and math.isnan(x)): return "0-1k"
    s = str(x).strip()
    if s.isdigit(): return MAPEAR.get(int(s), s)
    s = s.replace("K", "k")
    return s if s != "NC" else "NC"


# ----------------------------------------------------------------------------- 01 HIGHLIGHTS
def highlights(ticker, dia, precos, tab_short, b3xdt, economatica, corretoras_dia):
    """precos: DataFrame gare_precos/game_precos (Data, FEC, MAX, MIN, MED, QTT), uma linha por pregão.
    tab_short: linha de gare_short do dia (Volume Short, Saldo Short, Taxa Short) — None para o GAME11.
    b3xdt: tab_<FUNDO>_b3xDT (B3, DT, PF, PJ) em fração.
    economatica: {"var_ifix": fração, "var_ifix_seg": fração} (IFIX e média dos peers do segmento, dia D-1 × D-2).
    corretoras_dia: tabela do dia — VOL TOTAL (MM) = soma de compra_vtt / 1e6 (BASE_TABELAS!L11)."""
    dia = _data(dia)
    p = precos.copy(); p["Data"] = pd.to_datetime(p["Data"]).dt.date
    p = p.sort_values("Data")
    hoje = p[p["Data"] == dia]
    if hoje.empty: raise ValueError(f"{ticker}: sem linha de preços para {dia:%d/%m/%Y}")
    hoje = hoje.iloc[0]
    ant = p[p["Data"] < dia]
    if ant.empty: raise ValueError(f"{ticker}: sem pregão anterior a {dia:%d/%m/%Y} na base de preços")
    ant = ant.iloc[-1]
    fech, fech_d1, med = _f(hoje["FEC"]), _f(ant["FEC"]), _f(hoje["MED"])
    h = {
        "preco_fech": fech, "preco_max": _f(hoje["MAX"]), "preco_min": _f(hoje["MIN"]),
        "fech_d1": fech_d1, "preco_med": med,
        "var_pmxpf": (fech - med) / med if med else 0.0,                 # TABELA_HIGHLIGHT!T5
        "variacao": (fech - fech_d1) / fech_d1 if fech_d1 else 0.0,       # BASE_TABELAS!E7
        "var_ifix_seg": _f(economatica.get("var_ifix_seg")),            # BASE_TABELAS!H7 (média dos peers)
        "var_ifix": _f(economatica.get("var_ifix")),                    # DADOS_BROADCAST_COTISTAS!V10
        "vol_total_mm": _f(corretoras_dia["compra_vtt"].sum()) / 1e6,   # BASE_TABELAS!L11 / 1e6
        "volume_b3": _f(b3xdt["B3"].iloc[0]), "daytrade": _f(b3xdt["DT"].iloc[0]),
    }
    if ticker == "GARE11":
        if tab_short is None: raise ValueError("GARE11 exige tab_short (Volume Short, Taxa Short)")
        h["taxa_short"] = _f(tab_short["Taxa Short"]) / 100.0           # TABELA_HIGHLIGHT!P5 = D9/100
        h["vol_short_mm"] = _f(tab_short["Volume Short"]) / 1e6         # TABELA_HIGHLIGHT!P8 = C9/1e6
    return h


# ----------------------------------------------------------------------------- 02 MARKET MAKER
def market_maker(corretoras_dia, corretoras_mes):
    """Reproduz TABELA_MKM. corretoras_dia: saída de buscar_corretoras_dia (corretora, compra_*, venda_*, saldo_vtt),
    com *_pct_vtt em pontos percentuais. corretoras_mes: saída de buscar_corretoras_mes ({'compra': df, 'venda': df}
    com pct em fração) — PART/MÊS = participação no mês ANTERIOR; corretora ausente no mês → 0."""
    df = corretoras_dia.copy()
    mes_c = dict(zip(corretoras_mes["compra"]["corretora"], corretoras_mes["compra"]["pct"])) if corretoras_mes else {}
    mes_v = dict(zip(corretoras_mes["venda"]["corretora"], corretoras_mes["venda"]["pct"])) if corretoras_mes else {}

    def lado(prefixo, mes):
        d = df.sort_values(f"{prefixo}_vtt", ascending=False).reset_index(drop=True)
        top, resto = d.iloc[:N_TOP_MKM], d.iloc[N_TOP_MKM:]
        rows = [{"nome": r["corretora"], "volume": _f(r[f"{prefixo}_vtt"]) / 1000.0,
                 "part_dia": _f(r[f"{prefixo}_pct_vtt"]) / 100.0, "part_mes": _f(mes.get(r["corretora"], 0.0)),
                 "preco_medio": _f(r[f"{prefixo}_med"])} for _, r in top.iterrows()]
        com_preco = resto[resto[f"{prefixo}_med"] > 0]                 # AVERAGEIFS(... "maior")
        rows.append({"nome": "Others", "volume": _f(resto[f"{prefixo}_vtt"].sum()) / 1000.0,
                     "part_dia": _f(resto[f"{prefixo}_pct_vtt"].sum()) / 100.0,
                     "part_mes": max(0.0, 1.0 - sum(r["part_mes"] for r in rows)),          # =1-SUM(top 7)
                     "preco_medio": _f(com_preco[f"{prefixo}_med"].mean()) if len(com_preco) else 0.0})
        return rows

    saldo = df.sort_values("saldo_vtt", ascending=True).iloc[:N_SALDO]      # RANK crescente = mais negativo primeiro
    return {"top_sold": lado("venda", mes_v), "top_bought": lado("compra", mes_c),
            "saldo": [{"nome": r["corretora"], "saldo": _f(r["saldo_vtt"]) / 1000.0} for _, r in saldo.iterrows()]}


# ----------------------------------------------------------------------------- 03 PARTICIPAÇÃO PF/PJ
def participacao_pf_pj(graf):
    """graf: graf1 do notebook (CATEGORIAS int 1..10, OPERACAO Compra/Venda, PF_PJ, VAR_PRECO positivo).
    Cada lado soma 100 %: venda ÷ total vendido, compra ÷ total comprado (pontos percentuais, 2 casas)."""
    g = graf[graf["OPERACAO"].isin(["Compra", "Venda"])].copy()
    g["VAR_PRECO"] = g["VAR_PRECO"].abs().astype(float)
    g["fx"] = g["CATEGORIAS"].map(lambda x: _faixa(x))
    tot = {op: _f(g[g["OPERACAO"] == op]["VAR_PRECO"].sum()) or 1.0 for op in ("Venda", "Compra")}
    out = {"faixas": FAIXAS}
    for op, tipo, key in [("Venda", "PF", "venda_pf"), ("Venda", "PJ", "venda_pj"),
                          ("Compra", "PF", "compra_pf"), ("Compra", "PJ", "compra_pj")]:
        sub = g[(g["OPERACAO"] == op) & (g["PF_PJ"] == tipo)].groupby("fx")["VAR_PRECO"].sum()
        out[key] = [round(_f(sub.get(fx, 0.0)) / tot[op] * 100.0, 2) for fx in FAIXAS]
    return out


# ----------------------------------------------------------------------------- 04 10+ VENDEDORES / COMPRADORES
def top10(df, ticker):
    """df: TOP10_Venda ou TOP10_Compra do notebook (índice NOME; CATEGORIAS já mapeada, PF_PJ, VAR_PRECO,
    CATEGORIAS ATUAIS, NOVOS_COTISTAS, ENTRADA_GARE15/ENTRADA_GALG15 só no GARE11).
    Regras da planilha: categoria antiga = 'NC' quando novo cotista (TABELAS_C_V!M9); valor ÷ 1.000; TOTAL = soma."""
    d = df.reset_index() if df.index.name == "NOME" or "NOME" not in df.columns else df
    lista = []
    for _, r in d.head(N_TOP10).iterrows():
        nc = str(r.get("NOVOS_COTISTAS", "ANTIGO")).strip() == "NC"
        item = {"nome": str(r["NOME"]).strip(), "cat_antiga": "NC" if nc else _faixa(r["CATEGORIAS"]),
                "pf_pj": str(r["PF_PJ"]).strip(), "valor": _f(r["VAR_PRECO"]) / 1000.0,
                "cat_atual": _faixa(r.get("CATEGORIAS ATUAIS"))}
        if ticker == "GARE11":
            item["gare15"] = str(r.get("ENTRADA_GARE15", "AUSENTE")).strip() or "AUSENTE"
            item["galg15"] = str(r.get("ENTRADA_GALG15", "AUSENTE")).strip() or "AUSENTE"
        lista.append(item)
    return {"lista": lista, "total": sum(i["valor"] for i in lista)}


# ----------------------------------------------------------------------------- 05 COTAS POR FAIXA
def cotas_faixa(qtde_cotas, qtde_cotistas, b3xdt, top15, preco_fech, novos_cotistas, zeraram, total_cotistas, mov_mes):
    """qtde_cotas: (CATEGORIAS, PF_PJ, TOTAL_NOVO, % TOTAL) — % de cotas por faixa e tipo (pontos percentuais).
    qtde_cotistas: (CATEGORIAS, DOCUMENTO, % COTISTAS). b3xdt: PF/PJ em fração (TABELA_POSICOES!C27/C29).
    top15: TOP15_Real_excel (índice NOME; PF_PJ, CATEGORIAS, COTAS) — R$ mil = COTAS × fechamento / 1.000.
    mov_mes: {"entrada_mes", "saida_mes"} (acumulado do mês até o dia, inclusive — DADOS_BROADCAST!W7/X7)."""
    qc = qtde_cotas.copy(); qc["fx"] = qc["CATEGORIAS"].map(_faixa)
    pf = qc[qc["PF_PJ"] == "PF"].groupby("fx")["% TOTAL"].sum()
    pj = qc[qc["PF_PJ"] == "PJ"].groupby("fx")["% TOTAL"].sum()
    qt = qtde_cotistas.copy(); qt["fx"] = qt["CATEGORIAS"].map(_faixa)
    ct = qt.groupby("fx")["% COTISTAS"].sum()
    t15 = top15.reset_index() if "NOME" not in top15.columns else top15
    maiores = [{"nome": str(r["NOME"]).strip(), "categoria": _faixa(r["CATEGORIAS"]),
                "valor": _f(r["COTAS"]) * preco_fech / 1000.0} for _, r in t15.head(N_TOP15).iterrows()]
    return {"pf_faixa": [round(_f(pf.get(f, 0.0)), 2) for f in FAIXAS],
            "pj_faixa": [round(_f(pj.get(f, 0.0)), 2) for f in FAIXAS],
            "cotistas": [round(_f(ct.get(f, 0.0)), 1) for f in FAIXAS],
            "pf": _f(b3xdt["PF"].iloc[0]), "pj": _f(b3xdt["PJ"].iloc[0]),
            "mov": {"entrada_dia": int(novos_cotistas), "saida_dia": int(zeraram),
                    "entrada_mes": int(mov_mes["entrada_mes"]), "saida_mes": int(mov_mes["saida_mes"]),
                    "total": int(total_cotistas)},
            "maiores": maiores}


# ----------------------------------------------------------------------------- auxiliares de origem
def mov_cotistas_mes(historico, dia, entrada_dia=None, saida_dia=None,
                     col_data="DATA", col_entrada="Entraram", col_saida="Sairam"):
    """Acumulado do mês (até `dia`, inclusive) a partir de um histórico diário — por exemplo a tabela
    Var_Cotistas do Postgres (TOTAL, Entraram, Sairam, DATA) ou a aba DADOS_BROADCAST_COTISTAS (J:M).
    Se o próprio `dia` ainda não estiver no histórico, passe entrada_dia/saida_dia e eles são somados
    (é o que a planilha faz em DADOS_BROADCAST!W7 = W6 + W5)."""
    dia = _data(dia)
    h = historico.copy(); h[col_data] = pd.to_datetime(h[col_data]).dt.date
    m = h[(h[col_data] >= dia.replace(day=1)) & (h[col_data] <= dia)]
    ent = int(pd.to_numeric(m[col_entrada], errors="coerce").fillna(0).sum())
    sai = int(pd.to_numeric(m[col_saida], errors="coerce").fillna(0).sum())
    if entrada_dia is not None and dia not in set(m[col_data]):
        ent += int(entrada_dia); sai += int(saida_dia or 0)
    return {"entrada_mes": ent, "saida_mes": sai}


def economatica_da_xlsm(caminho_xlsm):
    """Os três únicos campos que hoje só existem na planilha (links Economatica, último valor SALVO):
    VAR IFIX (DADOS_BROADCAST_COTISTAS, bloco 'VAR IFIX' sob 'DATA RELATÓRIO'), VAR IFIX TIJOLO/PAPEL
    (BASE_TABELAS, coluna 'VAR_IFIX_TIJOLO'/'VAR_IFIX_PAPEL') e PREÇO MÉDIO (idem, 'PREÇO MÉDIO').
    Lê por cabeçalho (sobrevive a linhas inseridas). Nunca grave a .xlsm com openpyxl."""
    import openpyxl
    wb = openpyxl.load_workbook(caminho_xlsm, data_only=True, read_only=True)
    out = {}
    ws = wb["BASE_TABELAS"]
    for row in ws.iter_rows(min_row=1, max_row=12):
        for c in row:
            if isinstance(c.value, str) and c.value.strip().upper() in ("VAR_IFIX_TIJOLO", "VAR_IFIX_PAPEL"):
                out["var_ifix_seg"] = _f(ws.cell(row=c.row + 1, column=c.column).value)
    ws = wb["DADOS_BROADCAST_COTISTAS"]
    for row in ws.iter_rows(min_row=1, max_row=12):
        for c in row:
            if isinstance(c.value, str) and c.value.strip().upper() == "VAR IFIX":
                out["var_ifix"] = _f(ws.cell(row=c.row + 1, column=c.column).value)
            if isinstance(c.value, str) and c.value.strip().upper() == "PREÇO MÉDIO" and c.row > 5:
                out["preco_med"] = _f(ws.cell(row=c.row + 1, column=c.column).value)
    wb.close()   # read_only mantém o .xlsm aberto; sem fechar, o kernel segura o arquivo e o Excel não salva
    faltam = [k for k in ("var_ifix", "var_ifix_seg") if k not in out]
    if faltam: raise RuntimeError(f"economatica_da_xlsm: não achei {faltam} em {caminho_xlsm}")
    return out


# ----------------------------------------------------------------------------- montagem
def montar_json(ticker, dia, precos, tab_short, b3xdt, corretoras_dia, corretoras_mes,
                top10_venda, top10_compra, graf, qtde_cotas, qtde_cotistas, top15,
                novos_cotistas, zeraram, total_cotistas, mov_mes, economatica):
    dia = _data(dia)
    h = highlights(ticker, dia, precos, tab_short, b3xdt, economatica, corretoras_dia)
    return {
        "fundo": {"ticker": ticker},
        "data": dia.strftime("%d/%m/%Y"),
        "highlights": h,
        "market_maker": market_maker(corretoras_dia, corretoras_mes),
        "participacao_pf_pj": participacao_pf_pj(graf),
        "vendedores": top10(top10_venda, ticker),
        "compradores": top10(top10_compra, ticker),
        "cotas_faixa": cotas_faixa(qtde_cotas, qtde_cotistas, b3xdt, top15, h["preco_fech"],
                                   novos_cotistas, zeraram, total_cotistas, mov_mes),
    }
