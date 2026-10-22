#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_passivo.py — um comando: JSON → Passivo_<TICKER>_DD.MM.AAAA.pdf (+ checklist e preview PNG).
Uso: python3 gerar_passivo.py <dados.json> <pasta_saida>
Pode ser importado: from gerar_passivo import gerar; gerar(dados_dict, pasta_saida)
"""
import sys, os, json, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))

def gerar(dados, pasta_saida, preview=True):
    if isinstance(dados, (str, os.PathLike)):
        caminho_json = str(dados); dados = json.load(open(caminho_json, encoding="utf-8"))
    else:
        caminho_json = None
    tk, data = dados["fundo"]["ticker"], dados["data"]          # "14/10/2026"
    os.makedirs(pasta_saida, exist_ok=True)
    base = f"Passivo_{tk}_{data.replace('/', '.')}"
    js = caminho_json or os.path.join(pasta_saida, f"dados_{base}.json")
    if not caminho_json:
        json.dump(dados, open(js, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    pdf = os.path.join(pasta_saida, base + ".pdf")
    subprocess.run([sys.executable, os.path.join(HERE, "build_passivo.py"), js, pdf], check=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, "verify_passivo.py"), js, pdf, "--md", os.path.join(pasta_saida, f"Checklist_{base}.md")],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        raise RuntimeError(f"Checklist com ❌ — veja Checklist_{base}.md\n{r.stdout}\n{r.stderr[-3000:]}")
    if preview:
        import pymupdf
        pymupdf.open(pdf)[0].get_pixmap(dpi=110).save(os.path.join(pasta_saida, base + ".png"))
    return pdf

if __name__ == "__main__":
    print(gerar(sys.argv[1], sys.argv[2]))
