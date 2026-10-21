# -*- coding: utf-8 -*-
"""
historico_passivo_game.py
=========================
Povoa o banco Postgres com o histórico do GAME11 rodando o Passivo_GAME.ipynb uma vez por pregão,
em MODO_HISTORICO (só grava no banco: pula gráficos, Excel, PPT e PDF).

Como funciona
-------------
1. Lista os arquivos DD.MM.xlsx das pastas FORMATADOS\\GAME entre a data inicial e a final.
2. Para cada data, o papermill abre o notebook, injeta `data` e `MODO_HISTORICO = True` na célula
   marcada com a tag "parameters", roda tudo e salva a cópia executada em
   historico_game\\notebooks\\Passivo_GAME_AAAA-MM-DD.ipynb (para conferir depois).
3. Se um dia falhar, anota o erro em historico_game\\historico_game.log e segue para o próximo.
4. No fim, confere no banco quantas linhas o GAME11 tem em cada tabela por dia e lista os dias que faltam.

Repetir um dia é seguro: o envio apaga e regrava só aquele (data, fundo).

Uso (na pasta do repositório, com o .venv ativo)
------------------------------------------------
    python historico_passivo_game.py                        # 05/01/2026 até o último arquivo disponível
    python historico_passivo_game.py 2026-01-05 2026-03-31  # intervalo
    python historico_passivo_game.py 2026-02-02             # um dia só
    python historico_passivo_game.py --conferir             # só a conferência no banco, sem rodar nada
    python historico_passivo_game.py --fundo GARE11 2026-06-15   # mesmo fluxo para o GARE (Passivo_GARE.ipynb, pasta GARE)
"""
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import pandas as pd
import papermill as pm
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

REPO = os.path.dirname(os.path.abspath(__file__))
RAIZ_B3 = (r"G:\.shortcut-targets-by-id\1YZLLTFOuLniE6hO7WNHXl2c3MSa4TOv6\X. GAME11\GUARDIAN Institucional"
           r"\5. Planejamento & Processos\2. 2023\4. Research\2025\5. Inteligência Passivos Guardian"
           r"\1. ARQUIVOS B3\FORMATADOS")
MESES = {1: '1. JAN', 2: '2. FEV', 3: '3. MAR', 4: '4. ABR', 5: '5. MAI', 6: '6. JUN',
         7: '7. JUL', 8: '8. AGO', 9: '9. SET', 10: '10. OUT', 11: '11. NOV', 12: '12. DEZ'}

# Cada fundo tem seu notebook, sua pasta de arquivos da B3 e o nome da variável de data na célula de PARÂMETROS.
# Escolha com --fundo GARE11 (padrão: GAME11). O GARE é ~28x maior (≈565 mil linhas/dia na tabela_b3): conte 1-2 min por dia.
FUNDOS = {
    "GAME11": {"notebook": "Passivo_GAME.ipynb", "pasta_b3": "GAME", "param_data": "data", "saida": "historico_game"},
    "GARE11": {"notebook": "Passivo_GARE.ipynb", "pasta_b3": "GARE", "param_data": "dia",  "saida": "historico_gare"},
}
FUNDO = "GAME11"
NOTEBOOK = PASTA_SAIDA = PASTA_NOTEBOOKS = LOG = RAIZ_FORMATADOS = PARAM_DATA = None


def configurar_fundo(fundo):
    """Define os caminhos globais do fundo escolhido."""
    global FUNDO, NOTEBOOK, PASTA_SAIDA, PASTA_NOTEBOOKS, LOG, RAIZ_FORMATADOS, PARAM_DATA
    if fundo not in FUNDOS:
        raise SystemExit(f"Fundo desconhecido: {fundo}. Use um de {list(FUNDOS)}.")
    cfg = FUNDOS[fundo]
    FUNDO = fundo
    NOTEBOOK = os.path.join(REPO, cfg["notebook"])
    PASTA_SAIDA = os.path.join(REPO, cfg["saida"])
    PASTA_NOTEBOOKS = os.path.join(PASTA_SAIDA, "notebooks")
    LOG = os.path.join(PASTA_SAIDA, f"{cfg['saida']}.log")
    RAIZ_FORMATADOS = os.path.join(RAIZ_B3, cfg["pasta_b3"])
    PARAM_DATA = cfg["param_data"]


configurar_fundo(FUNDO)

DATA_INICIAL_PADRAO = datetime(2026, 1, 5)
TABELAS = ["tabela_b3", "Var_Cotistas", "Tabela_broadcast", "Short"]


# ============================================================
# ARQUIVOS DA B3 (mesma regra do bloco 2 do notebook)
# ============================================================
def pasta_mes(d):
    raiz_ano = os.path.join(RAIZ_FORMATADOS, str(d.year))
    raiz = raiz_ano if os.path.isdir(raiz_ano) else RAIZ_FORMATADOS
    return os.path.join(raiz, MESES[d.month])


def arquivos_b3(d):
    pasta, saida = pasta_mes(d), {}
    for nome in (os.listdir(pasta) if os.path.isdir(pasta) else []):
        partes = nome.lower().removesuffix('.xlsx').split('.')
        if nome.lower().endswith('.xlsx') and len(partes) == 2 and all(p.isdigit() for p in partes):
            dd, mm = map(int, partes)
            if mm == d.month:
                saida[datetime(d.year, mm, dd)] = os.path.join(pasta, nome)
    return saida


def datas_disponiveis(inicio, fim):
    """Datas com arquivo DD.MM.xlsx entre inicio e fim (inclusive), em ordem."""
    datas, cursor = set(), inicio.replace(day=1)
    while cursor <= fim:
        datas |= set(arquivos_b3(cursor))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return sorted(d for d in datas if inicio <= d <= fim)


# ============================================================
# BANCO (mesma conexão da célula 2 do notebook)
# ============================================================
def engine_passivo():
    url = os.getenv("DATABASE_URL")
    if not url:
        senha = os.getenv("SENHA_GCP")
        if not senha:
            raise RuntimeError("SENHA_GCP não definida no .env")
        url = (f"postgresql+psycopg2://{os.getenv('USUARIO_GCP', 'postgres')}:{quote_plus(senha)}"
               f"@{os.getenv('HOST_GCP')}:{os.getenv('PORT_GCP', '5432')}/{os.getenv('DB_NAME_GCP', 'passivo')}")
    elif "postgresql://" in url and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(url)


def conferir_banco(datas, log):
    """Linhas do GAME11 por dia em cada tabela; aponta os dias da lista que ficaram sem registro."""
    inicio, fim = min(datas).date(), max(datas).date()
    resumo = pd.DataFrame(index=pd.Index([d.date() for d in datas], name="data"))
    with engine_passivo().connect() as conn:
        for tabela in TABELAS:
            linhas = conn.execute(text(f'''
                SELECT data, COUNT(*) FROM "{tabela}"
                WHERE fundo = :fundo AND data BETWEEN :ini AND :fim
                GROUP BY data
            '''), {"fundo": FUNDO, "ini": inicio, "fim": fim}).fetchall()
            contagem = {d: n for d, n in linhas}
            resumo[tabela] = [contagem.get(d, 0) for d in resumo.index]

    faltam = resumo.index[resumo["tabela_b3"] == 0].tolist()
    log.info("CONFERÊNCIA NO BANCO — %s, %d dias entre %s e %s", FUNDO, len(datas), inicio, fim)
    log.info("\n%s", resumo.to_string())
    if faltam:
        log.warning("Dias SEM registro na tabela_b3: %s", ", ".join(d.strftime("%d/%m/%Y") for d in faltam))
    else:
        log.info("Todos os %d dias têm registro na tabela_b3.", len(datas))
    return resumo


# ============================================================
# EXECUÇÃO
# ============================================================
def rodar_dia(d, log):
    saida = os.path.join(PASTA_NOTEBOOKS, f"Passivo_GAME_{d:%Y-%m-%d}.ipynb")
    inicio = time.perf_counter()
    try:
        pm.execute_notebook(
            NOTEBOOK, saida,
            parameters={PARAM_DATA: d.strftime("%Y-%m-%d"), "MODO_HISTORICO": True},
            cwd=REPO, kernel_name="python3", progress_bar=False, log_output=False,
        )
        log.info("OK    %s  (%.0f s)", d.strftime("%d/%m/%Y"), time.perf_counter() - inicio)
        return True
    except pm.PapermillExecutionError as e:
        log.error("ERRO  %s  (%.0f s)  célula %s: %s: %s", d.strftime("%d/%m/%Y"), time.perf_counter() - inicio,
                  e.cell_index, e.ename, str(e.evalue).splitlines()[0][:300])
    except Exception as e:  # kernel caiu, Drive fora do ar etc.
        log.error("ERRO  %s  (%.0f s)  %s: %s", d.strftime("%d/%m/%Y"), time.perf_counter() - inicio,
                  type(e).__name__, str(e).splitlines()[0][:300])
    return False


def main(argv):
    argv = list(argv)
    if "--fundo" in argv:
        i = argv.index("--fundo")
        if i + 1 >= len(argv):
            raise SystemExit("Uso: --fundo GAME11 ou --fundo GARE11")
        configurar_fundo(argv[i + 1].upper())
        del argv[i:i + 2]
    os.makedirs(PASTA_NOTEBOOKS, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("historico")

    so_conferir = "--conferir" in argv
    args = [a for a in argv if not a.startswith("--")]
    inicio = datetime.strptime(args[0], "%Y-%m-%d") if len(args) >= 1 else DATA_INICIAL_PADRAO
    fim = datetime.strptime(args[1], "%Y-%m-%d") if len(args) >= 2 else (inicio if len(args) == 1 else datetime.today())

    datas = datas_disponiveis(inicio, fim)
    if not datas:
        log.error("Nenhum arquivo DD.MM.xlsx entre %s e %s em %s", inicio.date(), fim.date(), RAIZ_FORMATADOS)
        return 1

    if so_conferir:
        conferir_banco(datas, log)
        return 0

    log.info("=" * 70)
    log.info("HISTÓRICO %s — %d pregões de %s a %s", FUNDO, len(datas), datas[0].strftime("%d/%m/%Y"), datas[-1].strftime("%d/%m/%Y"))
    log.info("=" * 70)
    t0 = time.perf_counter()
    ok = [d for d in datas if rodar_dia(d, log)]
    falhas = [d for d in datas if d not in ok]
    log.info("-" * 70)
    log.info("FIM: %d ok, %d com erro, %.1f min", len(ok), len(falhas), (time.perf_counter() - t0) / 60)
    if falhas:
        log.warning("Dias com erro (rode de novo passando a data): %s", ", ".join(d.strftime("%Y-%m-%d") for d in falhas))
    conferir_banco(datas, log)
    return 0 if not falhas else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
