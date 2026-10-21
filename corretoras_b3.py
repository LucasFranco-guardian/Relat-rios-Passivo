# -*- coding: utf-8 -*-
"""
corretoras_b3.py
================
Busca a movimentação das corretoras (compra x venda) no banco `corretoras_peers`
e cola na planilha FORMATAR_COMPRAxVENDA (GARE11 / GAME11), substituindo a colagem
manual da tabela de corretoras e das abas mensais que alimentam a TABELA_MKM.

Fluxo típico (dentro dos notebooks Passivo_GARE / Passivo_GAME):

    from corretoras_b3 import buscar_corretoras_dia, buscar_corretoras_mes, conferir, colar_corretoras

    corretoras_dia = buscar_corretoras_dia("GARE11", dia)                  # tabela do dia
    corretoras_mes = buscar_corretoras_mes("GARE11", dia, pregoes=gare_precos["Data"])  # mês anterior
    conferir(corretoras_dia, corretoras_mes)                               # <-- confira aqui

    # ... dentro do bloco xlwings, antes do wb.save():
    colar_corretoras(wb, "GARE11", corretoras_dia, corretoras_mes)

As credenciais vêm do .env: USUARIO_GCP, SENHA_GCP, HOST_GCP, PORT_GCP, NEWDB_NAME_GCP.
"""

import os
from datetime import timedelta
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# ============================================================
# CONFIGURAÇÕES
# ============================================================
MERCADO = "Mercado Regular"

# Colunas na MESMA ordem da tabela da planilha (CORRETORA | Compra x5 | Venda x5 | Saldo)
COLUNAS_DIA = [
    "corretora_arquivo",
    "compra_neg", "compra_vtt", "compra_pct_vtt", "compra_qtt", "compra_med",
    "venda_neg", "venda_vtt", "venda_pct_vtt", "venda_qtt", "venda_med",
    "saldo_vtt",
]

# Onde cada fundo recebe os dados. As fórmulas auxiliares são escritas a partir da
# primeira linha e o Excel ajusta as referências relativas nas linhas seguintes.
LAYOUTS = {
    "GARE11": {
        "linha_ini": 14, "linha_fim": 53,          # TABELA_MKM busca até a linha 53
        "col_dados": ("K", "V"),
        "col_formulas": ("W", "AC"),
        "formulas": {
            "W":  '=RANK.EQ(M14,$M$14:$M$53,0)',
            "X":  '=RANK.EQ(R14,$R$14:$R$53,0)',
            "Y":  '=RANK.EQ(V14,$V$14:$V$53,1)',
            "Z":  '=IF(X14<8,"Normal","Others")',
            "AA": '=IF(U14>0,"maior","menor")',
            "AB": '=IF(W14<8,"Normal","Others")',
            "AC": '=IF(P14>0,"maior","menor")',
        },
        "aba_mes_compra": "MENSAL COMPRA - MKM",
        "aba_mes_venda": "HISTÓRICO VENDA - MKM",
        # Corretora | Neg | Vtt | %Vtt | Qtt
        "colunas_mes": ["corretora", "neg", "vtt", "pct", "qtt"],
    },
    "GAME11": {
        "linha_ini": 15, "linha_fim": 40,          # "MAIORES POSIÇÕES" começa na linha 41
        "col_dados": ("I", "T"),
        "col_formulas": ("U", "AA"),
        "formulas": {
            "U":  '=RANK.EQ(K15,$K$15:$K$40,0)',
            "V":  '=RANK.EQ(P15,$P$15:$P$40,0)',
            "W":  '=RANK.EQ(T15,$T$15:$T$40,1)',
            "X":  '=IF(V15>7,"Others","Normal")',
            "Y":  '=IF(S15>0,"maior","menor")',
            "Z":  '=IF(U15>7,"Others","Normal")',
            "AA": '=IF(N15>0,"maior","menor")',
        },
        "aba_mes_compra": "HISTÓRICO COMPRA - MKM",
        "aba_mes_venda": "HISTÓRICO VENDA - MKM",
        # Corretora | Volume | Participação | Quantidade
        "colunas_mes": ["corretora", "vtt", "pct", "qtt"],
    },
}

# Abas mensais: dados a partir da linha 3; a linha 62 do GARE tem um bloco auxiliar
LINHA_INI_MES, LINHA_FIM_MES = 3, 61

_engine = None


def _get_engine():
    """Engine do banco corretoras_peers (criada sob demanda)."""
    global _engine
    if _engine is None:
        usuario = os.getenv("USUARIO_GCP", "postgres")
        senha = os.getenv("SENHA_GCP")
        host = os.getenv("HOST_GCP")
        porta = os.getenv("PORT_GCP", "5432")
        banco = os.getenv("NEWDB_NAME_GCP")
        if not senha or not banco:
            raise RuntimeError("SENHA_GCP ou NEWDB_NAME_GCP não definido no .env.")
        _engine = create_engine(
            f"postgresql+psycopg2://{usuario}:{quote_plus(senha)}@{host}:{porta}/{banco}"
        )
    return _engine


def _como_data(valor):
    return pd.Timestamp(valor).date()


# ============================================================
# BUSCA NO BANCO
# ============================================================
def buscar_corretoras_dia(ticker, dia):
    """Tabela de corretoras do dia, na ordem do arquivo original (igual à colagem manual).

    Levanta erro se o banco ainda não tiver o dia (a carga roda ~11h do dia útil seguinte).
    """
    dia = _como_data(dia)
    sql = text(f"""
        SELECT {", ".join(COLUNAS_DIA)}
        FROM raw.negocios_corretora
        WHERE ticker = :ticker AND data_ref = :dia AND mercado = :mercado
        ORDER BY id
    """)
    with _get_engine().connect() as conn:
        df = pd.read_sql(sql, conn, params={"ticker": ticker, "dia": dia, "mercado": MERCADO})

    if df.empty:
        raise ValueError(
            f"Sem dados de corretoras do {ticker} para {dia:%d/%m/%Y} no banco "
            f"— a carga roda ~11h do dia útil seguinte."
        )
    if df["corretora_arquivo"].duplicated().any():
        repetidas = df.loc[df["corretora_arquivo"].duplicated(), "corretora_arquivo"].tolist()
        raise ValueError(f"Corretoras repetidas no banco para {ticker} em {dia:%d/%m/%Y}: {repetidas}")

    df = df.rename(columns={"corretora_arquivo": "corretora"})
    df[COLUNAS_DIA[1:]] = df[COLUNAS_DIA[1:]].astype(float)
    df.attrs.update(ticker=ticker, dia=dia)
    return df


def buscar_fechamento(ticker, dia):
    """Preço de fechamento do `ticker` no pregão `dia`, lido de raw.volume_preco.

    Reserva para quando o dia não está na planilha de preços (gare_precos / game_precos):
    serve para o histórico. Levanta erro se o banco não tiver o dia.
    """
    dia = _como_data(dia)
    sql = text("""
        SELECT preco_fechamento
        FROM raw.volume_preco
        WHERE ticker = :ticker AND data_ref = :dia
        ORDER BY data_carga DESC
        LIMIT 1
    """)
    with _get_engine().connect() as conn:
        linha = conn.execute(sql, {"ticker": ticker, "dia": dia}).fetchone()
    if linha is None or linha[0] is None:
        raise ValueError(f"Sem fechamento do {ticker} em {dia:%d/%m/%Y} em raw.volume_preco (banco corretoras_peers).")
    return float(linha[0])


def buscar_corretoras_mes(ticker, dia, pregoes=None):
    """Participação mensal de cada corretora no MÊS ANTERIOR ao `dia` (compra e venda).

    Participação = volume da corretora no mês / volume total do mês (fração: 0.4134 = 41,34%).
    `pregoes` (opcional): datas de pregão (ex.: gare_precos['Data']) para avisar dias faltando no banco.
    Retorna {'compra': df, 'venda': df, 'inicio', 'fim', 'dias_banco', 'dias_faltando'}.
    """
    dia = _como_data(dia)
    fim = dia.replace(day=1)                                  # exclusivo
    inicio = (fim - timedelta(days=1)).replace(day=1)

    sql = text("""
        SELECT data_ref, corretora_arquivo AS corretora,
               compra_neg, compra_vtt, compra_qtt,
               venda_neg, venda_vtt, venda_qtt
        FROM raw.negocios_corretora
        WHERE ticker = :ticker AND mercado = :mercado
          AND data_ref >= :inicio AND data_ref < :fim
    """)
    with _get_engine().connect() as conn:
        bruto = pd.read_sql(sql, conn, params={"ticker": ticker, "mercado": MERCADO,
                                               "inicio": inicio, "fim": fim})
    if bruto.empty:
        raise ValueError(f"Sem dados de corretoras do {ticker} em {inicio:%m/%Y} no banco.")

    dias_banco = sorted(pd.to_datetime(bruto["data_ref"]).dt.date.unique())
    dias_faltando = []
    if pregoes is not None:
        datas = pd.to_datetime(pd.Series(pregoes)).dt.date
        pregoes_mes = sorted(d for d in datas.unique() if inicio <= d < fim)
        dias_faltando = [d for d in pregoes_mes if d not in set(dias_banco)]

    soma = bruto.groupby("corretora")[
        ["compra_neg", "compra_vtt", "compra_qtt", "venda_neg", "venda_vtt", "venda_qtt"]
    ].sum().astype(float)

    lados = {}
    for lado in ("compra", "venda"):
        df = soma[[f"{lado}_neg", f"{lado}_vtt", f"{lado}_qtt"]].copy()
        df.columns = ["neg", "vtt", "qtt"]
        df = df[df["vtt"] > 0].sort_values("vtt", ascending=False)
        df["pct"] = df["vtt"] / df["vtt"].sum()
        lados[lado] = df.reset_index()[["corretora", "neg", "vtt", "pct", "qtt"]]

    return {**lados, "ticker": ticker, "inicio": inicio, "fim": fim,
            "dias_banco": dias_banco, "dias_faltando": dias_faltando}


# ============================================================
# CONFERÊNCIA
# ============================================================
def conferir(df_dia, mes=None, tolerancia=0.5):
    """Mostra a tabela do dia, a soma dos % e o resumo do mês anterior."""
    ticker, dia = df_dia.attrs.get("ticker", ""), df_dia.attrs.get("dia")
    print("=" * 60)
    print(f"CORRETORAS {ticker} — {dia:%d/%m/%Y} ({len(df_dia)} corretoras)")
    print("=" * 60)
    try:
        display(df_dia)  # noqa: F821 — disponível no Jupyter
    except NameError:
        print(df_dia.to_string())

    for lado in ("compra", "venda"):
        total = df_dia[f"{lado}_pct_vtt"].sum()
        marca = "✅" if abs(total - 100) <= tolerancia else "⚠️ "
        print(f"{marca} Soma % {lado}: {total:.2f}%")

    if mes is not None:
        print(f"\nPART/MÊS — {mes['inicio']:%m/%Y}: {len(mes['dias_banco'])} pregões no banco | "
              f"{len(mes['compra'])} corretoras compradoras, {len(mes['venda'])} vendedoras")
        if mes["dias_faltando"]:
            faltando = ", ".join(f"{d:%d/%m}" for d in mes["dias_faltando"])
            print(f"⚠️  ATENÇÃO: faltam no banco os pregões {faltando} — PART/MÊS calculado sem esses dias.")
        for lado in ("compra", "venda"):
            top = mes[lado].head(7)
            print(f"   Top 7 {lado}: " + " | ".join(f"{c} {p:.2%}" for c, p in zip(top["corretora"], top["pct"])))


# ============================================================
# COLAGEM NA PLANILHA (xlwings)
# ============================================================
def colar_corretoras(wb, ticker, df_dia, mes=None):
    """Cola a tabela do dia na BASE_TABELAS (limpando a área antes), reescreve as fórmulas
    auxiliares só nas linhas com dado e, se `mes` vier, reescreve as abas mensais."""
    lay = LAYOUTS[ticker]
    ini, fim = lay["linha_ini"], lay["linha_fim"]
    capacidade = fim - ini + 1
    n = len(df_dia)
    if n > capacidade:
        raise ValueError(f"{ticker}: {n} corretoras no dia, mas a tabela comporta {capacidade} "
                         f"(linhas {ini}–{fim}). Amplie o layout antes de colar.")

    ws = wb.sheets["BASE_TABELAS"]
    c_ini, c_fim = lay["col_dados"]
    f_ini, f_fim = lay["col_formulas"]
    ultima = ini + n - 1

    ws.range(f"{c_ini}{ini}:{c_fim}{fim}").clear_contents()
    ws.range(f"{f_ini}{ini}:{f_fim}{fim}").clear_contents()
    ws.range(f"{c_ini}{ini}").value = df_dia[["corretora"] + COLUNAS_DIA[1:]].values.tolist()
    for col, formula in lay["formulas"].items():
        ws.range(f"{col}{ini}:{col}{ultima}").formula = formula

    if mes is not None:
        for lado, aba in (("compra", lay["aba_mes_compra"]), ("venda", lay["aba_mes_venda"])):
            df = mes[lado][lay["colunas_mes"]]
            if len(df) > LINHA_FIM_MES - LINHA_INI_MES + 1:
                raise ValueError(f"{ticker}: {len(df)} corretoras no mês não cabem na aba '{aba}'.")
            sh = wb.sheets[aba]
            col_fim_mes = chr(ord("A") + len(lay["colunas_mes"]) - 1)
            sh.range(f"A{LINHA_INI_MES}:{col_fim_mes}{LINHA_FIM_MES}").clear_contents()
            sh.range(f"A{LINHA_INI_MES}").value = df.values.tolist()

    print(f"✅ {ticker}: {n} corretoras coladas em BASE_TABELAS!{c_ini}{ini}:{c_fim}{ultima}"
          + (f" | PART/MÊS de {mes['inicio']:%m/%Y}" if mes is not None else ""))
