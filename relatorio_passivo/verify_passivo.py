#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_passivo.py — confere cada valor do JSON contra o texto do PDF gerado (formatado em pt-BR como o build faz).
Uso: python3 verify_passivo.py <dados.json> <relatorio.pdf> [--md checklist.md]
Sai com código 1 se houver ❌. Regras de formatação replicadas de build_passivo.py (n, pct, intbr, trunc).
"""
import sys, json, argparse, re
import pymupdf
from build_passivo import n, pct, intbr, FUND

def texto_pdf(pdf):
    doc = pymupdf.open(pdf)
    t = " ".join(pg.get_text() for pg in doc)
    return len(doc), re.sub(r"\s+", " ", t)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("json"); ap.add_argument("pdf"); ap.add_argument("--md")
    a = ap.parse_args()
    d = json.load(open(a.json, encoding="utf-8")); tk = d["fundo"]["ticker"]
    pages, txt = texto_pdf(a.pdf)
    checks = []  # (seção, rótulo, esperado, ok)
    def ck(sec, lab, s):
        checks.append((sec, lab, s, s in txt))
    ck("header", "ticker", tk); ck("header", "data", d["data"])
    h = d["highlights"]
    ck("01", "PREÇO FECHAMENTO", n(h["preco_fech"], 2)); ck("01", "PREÇO MÁXIMO", n(h["preco_max"], 2))
    ck("01", "PREÇO MÍNIMO", n(h["preco_min"], 2)); ck("01", "FECHAMENTO D-1", n(h["fech_d1"], 2))
    ck("01", "PREÇO MÉDIO", n(h["preco_med"], 2)); ck("01", "VAR PMxPF", pct(h["var_pmxpf"], 1))
    ck("01", f"VARIAÇÃO {tk}", pct(h["variacao"], 2)); ck("01", "VAR IFIX SEG", pct(h["var_ifix_seg"], 1))
    ck("01", "VAR IFIX", pct(h["var_ifix"], 1)); ck("01", "VOL TOTAL (MM)", n(h["vol_total_mm"], 2))
    ck("01", "VOLUME B3", pct(h["volume_b3"], 0)); ck("01", "DAYTRADE", pct(h["daytrade"], 0))
    if tk == "GARE11":
        ck("01", "TAXA SHORT", pct(h["taxa_short"], 1)); ck("01", "VOL SHORT (MM)", n(h["vol_short_mm"], 2))
    mm = d["market_maker"]
    for lado in ("top_sold", "top_bought"):
        for r in mm[lado]:
            ck("02", f"{lado} {r['nome']}", f"{r['nome']} {intbr(r['volume'])} {pct(r['part_dia'], 0)} {pct(r['part_mes'], 0)} R$ {n(r['preco_medio'], 2)}")
    for r in [r for r in mm["saldo"] if round(r["saldo"]) < 0][:8]:
        ck("02", f"saldo {r['nome']}", f"{r['nome']} {intbr(r['saldo'])}")
    p = d["participacao_pf_pj"]
    for k in ("venda_pf", "venda_pj", "compra_pf", "compra_pj"):
        for i, v in enumerate(p[k]):
            if v > 0: ck("03", f"{k} {p['faixas'][i]}", pct(v / 100, 2))
    for sec, key in (("04", "vendedores"), ("04", "compradores")):
        for r in d[key]["lista"]:
            ck(sec, f"{key} {r['nome'][:20]}", f"{r['pf_pj']} {intbr(r['valor'])} {r['cat_atual']}")
        ck(sec, f"{key} TOTAL", f"TOTAL – – {intbr(d[key]['total'])}")
    c = d["cotas_faixa"]
    for i, v in enumerate(c["pf_faixa"]):
        if v >= 0.5: ck("05", f"pf {c and p['faixas'][i]}", pct(v / 100, 2))
    for i, v in enumerate(c["cotistas"]): ck("05", f"cotistas {p['faixas'][i]}", pct(v / 100, 1))
    ck("05", "PF %", pct(c["pf"], 0)); ck("05", "PJ %", pct(c["pj"], 0))
    for lab, k in (("ENTRADA - DIA", "entrada_dia"), ("SAÍDA - DIA", "saida_dia"), ("ENTRADA - MÊS", "entrada_mes"), ("SAÍDA - MÊS", "saida_mes"), ("TOTAL", "total")):
        ck("05", lab, intbr(c["mov"][k]))
    for r in c["maiores"]:
        ck("05", f"maiores {r['nome'][:18]}", f"{r['categoria']} {intbr(r['valor'])}")
    ok = sum(1 for x in checks if x[3]); tot = len(checks)
    lines = [f"# Checklist {tk} {d['data']} — {ok}/{tot} OK — páginas: {pages}", ""]
    for sec, lab, s, good in checks:
        lines.append(f"- {'✅' if good else '❌'} [{sec}] {lab}: `{s}`")
    if pages != 1: lines.insert(1, "❌ O PDF tem mais de 1 página."); ok -= 1
    out = "\n".join(lines)
    if a.md: open(a.md, "w", encoding="utf-8").write(out)
    print(f"{tk} {d['data']}: {ok}/{tot} OK, páginas={pages}")
    for sec, lab, s, good in checks:
        if not good: print(f"  ❌ [{sec}] {lab}: {s}")
    sys.exit(0 if ok == tot and pages == 1 else 1)

if __name__ == "__main__":
    main()
