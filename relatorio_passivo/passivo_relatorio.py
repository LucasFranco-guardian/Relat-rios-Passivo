# -*- coding: utf-8 -*-
"""
passivo_relatorio.py
====================
Cola entre os notebooks Passivo_GARE / Passivo_GAME e o pipeline de PDF (passivo_json + gerar_passivo).
NÃO contém regra de negócio do relatório (isso fica em passivo_json.py) nem layout (build_passivo.py).
Aqui ficam só as fontes auxiliares e a gravação no padrão de pastas/nomes que a rotina já usa:

    from passivo_relatorio import var_ifix_banco, historico_var_cotistas, economatica_planilha, gerar_relatorio

    economatica = economatica_planilha(caminho_destino, dia)        # peers do segmento (planilha MACRO, com checagem da data)
    economatica["var_ifix"] = var_ifix_banco(dia)                   # IFIX direto do banco corretoras_peers
    mov_mes = mov_cotistas_mes(historico_var_cotistas(get_engine(), "GARE11"), dia, novos_cotistas, zeraram)
    dados = montar_json(...)
    pdf = gerar_relatorio(dados, PASTA_DIARIOS, "Passivos_GARE11_13.10.2026.pdf")

O PDF é gravado na RAIZ da pasta do fundo com o nome que o Enviar_email_PASSIVO já lê.
JSON, checklist e preview PNG ficam na subpasta PYTHON_JSON/ da mesma pasta.
"""
from __future__ import annotations
import os, sys, json, math, shutil
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# O WeasyPrint precisa das DLLs do GTK (Pango/Cairo). O kernel do Jupyter pode ter nascido antes da
# instalação e ainda não enxergar o PATH novo; garantimos aqui para o build (subprocesso) herdar.
GTK_BIN = r"C:\Program Files\GTK3-Runtime Win64\bin"
if os.path.isdir(GTK_BIN) and GTK_BIN.lower() not in os.environ.get("PATH", "").lower():
    os.environ["PATH"] = GTK_BIN + os.pathsep + os.environ.get("PATH", "")

SUBPASTA_AUX = "PYTHON_JSON"


def _data(d):
    if isinstance(d, datetime): return d.date()
    if isinstance(d, date): return d
    return pd.to_datetime(d).date()


# ----------------------------------------------------------------------------- IFIX (banco corretoras_peers)
def var_ifix_banco(dia, ticker_indice="IFIX"):
    """Variação do IFIX entre o pregão `dia` e o pregão anterior, lida de raw.volume_preco do banco
    corretoras_peers (mesma conexão do corretoras_b3). Substitui o link Economatica 'VAR IFIX'.
    Levanta erro se o banco não tiver o dia ou o pregão anterior."""
    from corretoras_b3 import _get_engine
    dia = _data(dia)
    sql = text("""
        SELECT data_ref, preco_fechamento
        FROM raw.volume_preco
        WHERE ticker = :t AND data_ref <= :d
        ORDER BY data_ref DESC
        LIMIT 2
    """)
    with _get_engine().connect() as conn:
        df = pd.read_sql(sql, conn, params={"t": ticker_indice, "d": dia})
    if df.empty or pd.Timestamp(df["data_ref"].iloc[0]).date() != dia:
        raise ValueError(f"{ticker_indice}: sem fechamento para {dia:%d/%m/%Y} em raw.volume_preco (a carga roda ~11h do dia útil seguinte).")
    if len(df) < 2:
        raise ValueError(f"{ticker_indice}: sem pregão anterior a {dia:%d/%m/%Y} em raw.volume_preco.")
    hoje, ant = float(df["preco_fechamento"].iloc[0]), float(df["preco_fechamento"].iloc[1])
    return hoje / ant - 1.0


# ----------------------------------------------------------------------------- Var_Cotistas (banco passivo)
def historico_var_cotistas(engine, fundo, tabela="Var_Cotistas"):
    """Histórico diário de entradas/saídas de cotistas do fundo (tabela compartilhada GARE11/GAME11,
    por isso o filtro em `fundo`). Colunas no nome que mov_cotistas_mes espera: DATA, Entraram, Sairam."""
    sql = text(f'SELECT data AS "DATA", entraram AS "Entraram", sairam AS "Sairam" FROM "{tabela}" WHERE fundo = :f ORDER BY data')
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"f": fundo})


# ----------------------------------------------------------------------------- Economatica (planilha MACRO)
def economatica_planilha(caminhos, dia, exigir_data=True):
    """Lê VAR IFIX TIJOLO/PAPEL (média dos peers do segmento) do último valor SALVO em uma planilha
    FORMATAR (MACRO ou BASE), via passivo_json.economatica_da_xlsm, e confere que a data D-1 salva em
    BASE_TABELAS é o `dia` do relatório e que o valor é numérico.
    `caminhos` pode ser um caminho ou uma lista: a primeira planilha válida vence (ordem sugerida:
    MACRO, depois BASE). Motivo: a seção 41 (xlwings) regrava a MACRO sem o suplemento Economatica e as
    células _xll.BCH viram '#NAME?'; a BASE, que é aberta no Excel de verdade, costuma estar íntegra.
    Sem essas checagens um zero ou um valor velho entraria no PDF sem ninguém notar."""
    if isinstance(caminhos, (list, tuple)):
        erros = []
        for c in caminhos:
            try:
                eco = economatica_planilha(c, dia, exigir_data)
                eco["planilha"] = c
                return eco
            except Exception as e:  # tenta a próxima
                erros.append(f"- {os.path.basename(c)}: {e}")
        raise RuntimeError("Nenhuma planilha FORMATAR serve para o VAR IFIX do segmento:\n" + "\n".join(erros))
    caminho_xlsm = caminhos
    import openpyxl
    from passivo_json import economatica_da_xlsm
    dia = _data(dia)
    eco = economatica_da_xlsm(caminho_xlsm)
    wb = openpyxl.load_workbook(caminho_xlsm, data_only=True, read_only=True)
    ws = wb["BASE_TABELAS"]
    data_salva, bruto_seg = None, None
    for row in ws.iter_rows(min_row=1, max_row=12):
        for c in row:
            if isinstance(c.value, str) and c.value.strip().upper() == "DATA" and data_salva is None:
                v = ws.cell(row=c.row, column=c.column + 1).value
                if v is not None:
                    data_salva = _data(v)
            if isinstance(c.value, str) and c.value.strip().upper() in ("VAR_IFIX_TIJOLO", "VAR_IFIX_PAPEL"):
                bruto_seg = ws.cell(row=c.row + 1, column=c.column).value
    wb.close()   # read_only mantém o .xlsm aberto até aqui; sem isto o kernel segura o arquivo e o Excel não consegue salvar
    eco["data_planilha"] = data_salva
    # O xlwings (seção 41) regrava a MACRO sem o suplemento Economatica: as células _xll.BCH viram '#NAME?' e
    # economatica_da_xlsm() as leria como 0,0 sem reclamar. Só aceitamos número de verdade.
    if not isinstance(bruto_seg, (int, float)) or isinstance(bruto_seg, bool):
        raise RuntimeError(
            f"VAR IFIX do segmento na planilha está '{bruto_seg}' (o Economatica não recalculou; se for a MACRO, ela foi "
            f"regravada pelo xlwings). Abra a planilha no Excel, confira a data {dia:%d/%m/%Y} em BASE_TABELAS!C2, "
            f"espere o Economatica preencher, salve e rode esta célula de novo:\n  {caminho_xlsm}"
        )
    if exigir_data and data_salva != dia:
        salva = f"{data_salva:%d/%m/%Y}" if data_salva else "vazia"
        raise RuntimeError(
            f"Planilha salva com DATA {salva}, mas o relatório é de {dia:%d/%m/%Y}. "
            f"Abra a planilha no Excel, digite {dia:%d/%m/%Y} em BASE_TABELAS!C2 (o Economatica recalcula os peers), "
            f"salve e rode esta célula de novo:\n  {caminho_xlsm}"
        )
    return eco


# ----------------------------------------------------------------------------- geração
def _conferir_render(pdf):
    """Garante que o PDF saiu com as fontes do layout e com as imagens (logo + ícone do fundo).
    Se o GTK/fontes/assets falharem, o WeasyPrint cai em fontes genéricas e texto alternativo sem erro;
    o verify_passivo (só números) não pega isso."""
    import pymupdf
    doc = pymupdf.open(pdf)
    pg = doc[0]
    # nomes embutidos saem como 'XXXXXX+Avenir' / 'XXXXXX+Geo' (families do CSS do build); com GTK/assets
    # quebrados o WeasyPrint cai em Verdana/Arial e o PDF fica sem imagens.
    fontes = {f[3].split("+")[-1].lower() for f in pg.get_fonts()}
    n_img = len(pg.get_images())
    problemas = []
    if not any(f.startswith("avenir") for f in fontes): problemas.append(f"fonte Avenir não embutida (fontes: {sorted(fontes)})")
    if not any(f.startswith("geo") for f in fontes): problemas.append("fonte Geometos (Geo) não embutida")
    if n_img < 2: problemas.append(f"só {n_img} imagem(ns) no PDF (esperado logo + ícone do fundo + ícones)")
    if len(doc) != 1: problemas.append(f"{len(doc)} páginas")
    if problemas:
        raise RuntimeError("PDF renderizado com problema: " + "; ".join(problemas) + f" -> {pdf}")


def _longpath(p):
    """Prefixo \\\\?\\ do Windows: libera caminhos acima de 260 caracteres sem mexer no registro.
    Os caminhos do Drive (G:\\.shortcut-targets-by-id\\...\\5. Inteligência Passivos Guardian\\2. RELATÓRIOS\\...)
    passam de 260 com o nome do checklist, e o open() falha com WinError 206."""
    p = os.path.abspath(p)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        p = "\\\\?\\" + p
    return p


def _copiar_com_retentativa(origem, destino, tentativas=6, espera=2.0):
    """Cópia para o Google Drive (G:) com retentativas: o Drive File Stream às vezes segura o arquivo por
    alguns segundos logo depois de uma gravação e devolve PermissionError/OSError."""
    import time
    ultimo = None
    for i in range(tentativas):
        try:
            shutil.copyfile(_longpath(origem), _longpath(destino))
            return destino
        except OSError as e:
            ultimo = e
            time.sleep(espera * (i + 1))
    raise RuntimeError(f"Não consegui gravar {destino} depois de {tentativas} tentativas: {ultimo}")


def gerar_relatorio(dados, pasta_fundo, nome_pdf, pasta_aux=None, preview=True):
    """gerar_passivo.gerar + checagem de render + gravação com o nome/pasta da rotina.
    O build, o verify e o preview rodam numa pasta temporária LOCAL (rápido e sem a latência do Google
    Drive, que já fez o verify falhar ao ler um PDF recém-gravado em G:). Só no fim os arquivos são
    copiados para o destino:
    - PDF final: <pasta_fundo>/<nome_pdf>  (ex.: .../1. DIARIOS/GARE/Passivos_GARE11_13.10.2026.pdf)
    - dados_*.json, Checklist_*.md e *.png: <pasta_fundo>/PYTHON_JSON/ (ou `pasta_aux`)
    Retorna o caminho do PDF final."""
    import tempfile
    from gerar_passivo import gerar
    pasta_aux = pasta_aux or os.path.join(pasta_fundo, SUBPASTA_AUX)
    tmp = tempfile.mkdtemp(prefix="passivo_pdf_")
    try:
        pdf_tmp = gerar(dados, tmp, preview=preview)      # imprime "TK DD/MM/AAAA: N/N OK, páginas=1"
        _conferir_render(pdf_tmp)
        os.makedirs(_longpath(pasta_aux), exist_ok=True)
        os.makedirs(_longpath(pasta_fundo), exist_ok=True)
        destino = os.path.join(pasta_fundo, nome_pdf)
        _copiar_com_retentativa(pdf_tmp, destino)
        for f in sorted(os.listdir(tmp)):
            if f != os.path.basename(pdf_tmp):
                _copiar_com_retentativa(os.path.join(tmp, f), os.path.join(pasta_aux, f))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"✅ PDF: {destino}")
    print(f"   JSON/checklist/preview: {pasta_aux}")
    return destino


# ----------------------------------------------------------------------------- regressão
def comparar_json(dados, exemplo, tol=0.002):
    """Compara o JSON gerado com um JSON de referência (ex.: exemplos/dados_Passivo_GARE11_14.10.2026.json).
    Floats: tolerância relativa `tol` (0,2 %) ou absoluta 1e-9; strings/ints: iguais. Retorna lista de diferenças."""
    ref = json.load(open(exemplo, encoding="utf-8")) if isinstance(exemplo, (str, os.PathLike)) else exemplo
    difs = []

    def cmp(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a: difs.append(f"{path}.{k}: falta no gerado"); continue
                if k not in b: difs.append(f"{path}.{k}: não existe no exemplo"); continue
                cmp(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b): difs.append(f"{path}: {len(a)} itens no gerado x {len(b)} no exemplo")
            for i, (x, y) in enumerate(zip(a, b)): cmp(x, y, f"{path}[{i}]")
        elif isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
            if a != b: difs.append(f"{path}: gerado={a!r} exemplo={b!r}")
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if math.isnan(float(a)) and math.isnan(float(b)): return
            if abs(float(a) - float(b)) > max(abs(float(b)) * tol, 1e-9):
                difs.append(f"{path}: gerado={a} exemplo={b}")
        elif a != b:
            difs.append(f"{path}: gerado={a!r} exemplo={b!r}")

    cmp(dados, ref, "$")
    if difs:
        print(f"❌ {len(difs)} diferença(s) em relação a {exemplo}:")
        for d in difs: print("   ", d)
    else:
        print(f"✅ JSON idêntico ao exemplo (tolerância {tol:.1%} nos floats): {exemplo}")
    return difs
