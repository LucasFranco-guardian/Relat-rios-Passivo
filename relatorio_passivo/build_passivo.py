#!/usr/bin/env python3
"""Gera o Relatório Passivo (GARE11 ou GAME11) em PDF A4 de 1 página, no Design System Guardian Gestora,
a partir de um JSON (contrato em README_contrato_json.md).
Uso: python3 build_passivo.py <dados.json> <saida.pdf> [--html saida.html] [--sections header,01,02,03,04,05]
"""
import sys, json, html, math, os, re, argparse, base64
from weasyprint import HTML

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = __import__("pathlib").Path(HERE, "assets").as_uri()   # file:///C:/... (file://C:\... nao funciona no Windows)
ICONS = f"{HERE}/assets/icons"

# ------------------------------------------------------------------ tokens (DS Guardian) — iguais ao relatorio-ativo
T = dict(
    slate="#374856", slate900="#262e38", slate800="#2e3a46", slate500="#4d5f74", slate400="#657791",
    slate300="#868d96", slate200="#a1a1a1", slate100="#d8d8d8", slate50="#f4f4f6",
    blood="#5a98b5", blue300="#9ac0d3", blue100="#e9f1f7", white="#ffffff",
    pos="#1f8f55", neg="#c8392b", border=".14", border2=".28",
)
FUND = {
    "GARE11": dict(color="#39537a", soft="#e6ebf3", light="#9ac0d3", light2="#5a98b5", icon="fund-gare11-icon-white.png",
                   nome="FII GUARDIAN REAL ESTATE", segmento="TIJOLO", txt="#ffffff"),
    "GAME11": dict(color="#31b0cb", soft="#e3f4f8", light="#76d5f9", light2="#9fd9e6", icon="fund-game11-icon.png",
                   nome="FII GUARDIAN MULTIESTRATÉGIA", segmento="PAPEL", txt="#12232e"),
}

# ------------------------------------------------------------------ formatação pt-BR (arredondamento do Excel)
def _br(x, dec):
    from decimal import Decimal, ROUND_HALF_UP
    q = Decimal(1).scaleb(-dec)
    v = Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP)
    s = f"{v:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")

def n(x, dec=2, dash="–"):
    if x is None or (isinstance(x, float) and math.isnan(x)): return dash
    if abs(x) < 0.5 * 10 ** (-dec): x = 0.0
    return _br(x, dec)

def pct(x, dec=2):
    """x em fração (0,0105 → 1,05%)."""
    if x is None: return "–"
    v = x * 100
    if abs(v) < 0.5 * 10 ** (-dec): v = 0.0
    return _br(v, dec) + "%"

def intbr(x):
    if x is None: return "–"
    return _br(round(x), 0)

def esc(s): return html.escape(str(s)) if s is not None else ""

def cls_var(x):
    if x is None: return ""
    return "pos" if x > 0 else "neg" if x < 0 else "zero"

def arrow(x):
    if x is None or x == 0: return ''
    return '<span class="arw pos">▲</span>' if x > 0 else '<span class="arw neg">▼</span>'

def icon(name, size="4mm", color=None):
    """Ícone Phosphor (regular) como <img> data-URI (inline <svg> quebra a pintura no WeasyPrint 70)."""
    svg = open(f"{ICONS}/{name}.svg").read().replace('fill="currentColor"', f'fill="{color or T["blood"]}"')
    b64 = base64.b64encode(svg.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{b64}" style="width:{size};height:{size};display:block" alt="">'

def trunc(s, lim=38):
    s = str(s).strip()
    return s if len(s) <= lim else s[:lim - 1].rstrip() + "…"

# ------------------------------------------------------------------ CSS
CSS = r"""
@font-face{font-family:'Avenir';src:url('__ASSETS__/fonts/Avenir Next LT Pro Regular.otf');font-weight:400;}
@font-face{font-family:'Geo';src:url('__ASSETS__/fonts/Geometos Rounded.ttf');font-weight:400;}
@page{size:A4;margin:0;}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:210mm;height:297mm;}
body{font-family:'Avenir';color:__SLATE__;background:#fff;font-size:7pt;line-height:1.25;-weasy-hyphens:none;}
.geo{font-family:'Geo';letter-spacing:-.01em;}
.b{text-shadow:.32px 0 currentColor,-.32px 0 currentColor;}
.ey{font-size:5.6pt;letter-spacing:.2em;text-transform:uppercase;color:__SLATE400__;}
.page{width:210mm;height:297mm;overflow:hidden;display:flex;flex-direction:column;background:#fff;}
.pos{color:__POS__;} .neg{color:__NEG__;} .zero{color:__SLATE300__;}
.arw{font-family:'Avenir';font-size:.62em;vertical-align:.12em;margin-right:.25em;}

/* ===== HEADER ===== */
.header{position:relative;background:__SLATE__;color:#fff;height:19mm;padding:0 9mm;flex:none;}
.gridtex{position:absolute;inset:0;
  background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
  background-size:7mm 7mm;}
.hrow{position:relative;display:flex;align-items:center;height:100%;}
.hlogo{height:8.2mm;display:block;}
.vsep{width:1px;height:10mm;background:rgba(255,255,255,.24);margin:0 5mm;}
.htitle .ey{color:__FUNDLIGHT__;font-size:6pt;}
.htitle .h1{font-size:15pt;line-height:1;letter-spacing:.02em;text-transform:uppercase;color:#fff;margin-top:1.2mm;}
.hspace{flex:1;}
.hdate{text-align:right;margin-right:6mm;}
.hdate .ey{color:rgba(255,255,255,.62);}
.hdate .d{font-size:11.5pt;color:#fff;margin-top:1mm;}
.hfund{display:flex;align-items:center;gap:2.6mm;padding-left:5mm;border-left:1px solid rgba(255,255,255,.24);height:10mm;}
.hfund img{height:8.2mm;display:block;}
.hfund .fn{font-size:6pt;line-height:1.3;letter-spacing:.06em;text-transform:uppercase;color:#fff;white-space:nowrap;}
.hfund .fn b{display:block;font-size:8.5pt;letter-spacing:.04em;text-shadow:.3px 0 #fff;}

/* ===== BODY ===== */
.body{flex:1;padding:3.4mm 9mm 3mm 9mm;display:flex;flex-direction:column;}
.sec{margin-top:__SECGAP__mm;}
.sec:first-child{margin-top:0;}
.sh{display:flex;align-items:center;margin-bottom:1.7mm;}
.sh .num{font-family:'Geo';font-size:5.6pt;color:#fff;background:__FUND__;width:5mm;height:5mm;display:flex;align-items:center;justify-content:center;margin-right:2.2mm;flex:none;}
.sh .t{font-size:7.4pt;letter-spacing:.16em;text-transform:uppercase;color:__SLATE__;white-space:nowrap;}
.sh .t b{text-shadow:.3px 0 currentColor;}
.sh .t .sep{color:__SLATE200__;margin:0 1.4mm;}
.sh .t .sub{letter-spacing:.1em;color:__SLATE400__;}
.sh .rule{flex:1;height:1px;background:rgba(55,72,86,__BORDER__);margin-left:3mm;}

/* ===== 01 HIGHLIGHTS — painel escuro (identidade do Passivo) ===== */
.pan{display:flex;background:__SLATE__;color:#fff;border-left:2.5mm solid __FUND__;}
.hero{width:44mm;flex:none;padding:2.2mm 3mm 2mm 3.2mm;border-right:1px solid rgba(255,255,255,.16);display:flex;flex-direction:column;justify-content:center;}
.hero .lab{font-size:5.2pt;letter-spacing:.16em;text-transform:uppercase;color:__FUNDLIGHT__;display:flex;align-items:center;gap:1.4mm;}
.hero .val{font-family:'Geo';font-size:21pt;line-height:1;margin-top:1.6mm;color:#fff;white-space:nowrap;}
.hero .val .rs{font-family:'Avenir';font-size:7pt;letter-spacing:.04em;color:rgba(255,255,255,.62);margin-right:1.2mm;vertical-align:.45em;}
.hero .var{margin-top:1.8mm;display:flex;align-items:center;gap:1.6mm;}
.hero .var .lab{color:rgba(255,255,255,.62);}
.hero .var .chip{font-family:'Geo';font-size:8pt;line-height:1;padding:.9mm 1.6mm .7mm;border-radius:.6mm;white-space:nowrap;}
.chip.pos{background:rgba(95,211,154,.16);color:#7fe0b0;} .chip.neg{background:rgba(255,155,141,.16);color:#ffa89a;} .chip.zero{background:rgba(255,255,255,.1);color:#fff;}
.pgrid{flex:1;display:flex;flex-direction:column;min-width:0;}
.prow{display:flex;flex:1;}
.prow+.prow{border-top:1px solid rgba(255,255,255,.16);}
.pk{flex:1;min-width:0;padding:1.5mm 2mm 1.3mm;border-left:1px solid rgba(255,255,255,.16);}
.pk:first-child{border-left:none;}
.pk .lab{font-size:4.8pt;letter-spacing:.1em;text-transform:uppercase;color:rgba(255,255,255,.62);line-height:1.1;display:flex;align-items:center;gap:1.1mm;white-space:nowrap;}
.pk .val{font-family:'Geo';font-size:11pt;line-height:1;margin-top:1.2mm;color:#fff;white-space:nowrap;}  /* 9pt -> 11pt (pedido do Lucas, 2026-10-20) */
.pk .val .rs{font-family:'Avenir';font-size:4.6pt;letter-spacing:.04em;color:rgba(255,255,255,.55);margin-right:.6mm;vertical-align:.3em;}
.pk .val .arw{font-size:5pt;}
.pk .val .pos{color:#7fe0b0;} .pk .val .neg{color:#ffa89a;} .pk .val .zero{color:#fff;}
.pk.vol{background:rgba(255,255,255,.07);}
.pk.vol .lab{color:__FUNDLIGHT__;}
.pk.vol+.pk.vol{border-left-color:rgba(255,255,255,.1);}
.sb{font-size:.72em;letter-spacing:.02em;text-transform:none;vertical-align:-.05em;}



.tb td.nc{color:__FUND__;text-shadow:.25px 0 currentColor;}
.tb td.aus{color:__SLATE300__;}
.tb td.num{font-variant-numeric:tabular-nums;}

.s04 table.tb{font-size:5.3pt;}
.s04 .tb td{padding:.42mm .7mm;}


/* ===== 05 cotas por faixa ===== */
.s05 .cards{align-items:stretch;}
.card.dark{background:__SLATE__;color:#fff;border:none;border-left:2.5mm solid __FUND__;padding:1.6mm 2mm 1.4mm 2.2mm;display:flex;flex-direction:column;}
.card.dark .dt{font-size:5.2pt;letter-spacing:.16em;text-transform:uppercase;color:__FUNDLIGHT__;white-space:nowrap;}
.split{display:flex;height:2.2mm;margin:1.4mm 0 1.2mm;border-radius:.4mm;overflow:hidden;}
.split .pf{background:__FUND__;} .split .pj{background:rgba(255,255,255,.35);}
.pfpj{display:flex;justify-content:space-between;}
.pfpj div{display:flex;flex-direction:column;}
.pfpj .l{font-size:4.8pt;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.62);}
.pfpj .v{font-family:'Geo';font-size:9.5pt;line-height:1;margin-top:.8mm;color:#fff;}
.pfpj div+div{align-items:flex-end;}
.pfpj .sw{display:inline-block;width:1.6mm;height:1.6mm;margin-right:1mm;vertical-align:-.1em;}
.mov{margin-top:auto;border-top:1px solid rgba(255,255,255,.16);padding-top:1.3mm;}
.mov .mr{display:flex;justify-content:space-between;align-items:baseline;padding:.55mm 0;border-bottom:1px solid rgba(255,255,255,.08);}
.mov .mr .l{font-size:4.8pt;letter-spacing:.1em;text-transform:uppercase;color:rgba(255,255,255,.62);white-space:nowrap;}
.mov .mr .v{font-family:'Geo';font-size:7.4pt;color:#fff;}
.mov .mr.tot{border-bottom:none;margin-top:.6mm;padding-top:1mm;border-top:1px solid rgba(255,255,255,.16);}
.mov .mr.tot .l{color:__FUNDLIGHT__;} .mov .mr.tot .v{font-size:8.6pt;color:__FUNDLIGHT__;}
.s05 .card.chart svg{height:100%;}

/* ===== 03 gráfico divergente ===== */
.card.chart{padding:1.6mm 2mm 1.2mm;}
.card.chart svg{display:block;width:100%;height:auto;}

/* ===== cards e tabelas (identidade Passivo: cabeçalho sem preenchimento, filete na cor do fundo) ===== */
.cards{display:flex;gap:3mm;}
.card{border:1px solid rgba(55,72,86,__BORDER__);background:#fff;padding:1.4mm 2mm 1.2mm;min-width:0;}
.card.venda{border-top:2px solid __SLATE500__;} .card.compra{border-top:2px solid __FUND__;} .card.neutro{border-top:2px solid __SLATE300__;}
.card .ct{display:flex;align-items:baseline;gap:1.6mm;margin-bottom:1.2mm;}
.card .ct .t{font-size:6.2pt;letter-spacing:.16em;text-transform:uppercase;color:__SLATE__;text-shadow:.3px 0 currentColor;white-space:nowrap;}
.card .ct .u{font-size:4.8pt;letter-spacing:.06em;text-transform:uppercase;color:__SLATE400__;white-space:nowrap;margin-left:auto;}
table.tb{width:100%;border-collapse:collapse;table-layout:fixed;font-size:5.6pt;}
.tb th{font-size:4.7pt;letter-spacing:.07em;text-transform:uppercase;color:__FUND__;text-align:right;padding:0 .8mm .7mm;border-bottom:1px solid __FUND__;white-space:normal;line-height:1.1;vertical-align:bottom;}
.tb th:first-child{text-align:left;padding-left:.6mm;}
.tb td{padding:.38mm .8mm;line-height:1.1;text-align:right;border-bottom:1px solid rgba(55,72,86,.08);white-space:nowrap;font-variant-numeric:tabular-nums;color:__SLATE__;overflow:hidden;text-overflow:ellipsis;}
.tb td:first-child{text-align:left;padding-left:.6mm;}
.tb tr:nth-child(even) td{background:__SLATE50__;}
.tb tr.others td{color:__SLATE400__;border-top:1px solid rgba(55,72,86,__BORDER2__);}
.tb tr.total td{color:__SLATE__;text-shadow:.3px 0 currentColor;border-top:1px solid rgba(55,72,86,__BORDER2__);background:#fff;}
.tb td .rs{font-size:.8em;color:__SLATE400__;margin-right:.4mm;}
.tb td.bar{position:relative;}
.tb td.bar .fill{position:absolute;right:0;top:.5mm;bottom:.5mm;background:rgba(200,57,43,.14);}
.tb td.bar span.v{position:relative;color:__NEG__;}
.tb td.pf{color:__SLATE400__;} .tb td.tag{color:__SLATE400__;letter-spacing:.02em;}
"""

def css_for(tk, k=1.0):
    f = FUND[tk]
    return (CSS.replace("__SECGAP__", f"{1.8 * k:.2f}").replace("__ASSETS__", ASSETS).replace("__SLATE__", T["slate"]).replace("__SLATE400__", T["slate400"])
            .replace("__SLATE500__", T["slate500"]).replace("__SLATE300__", T["slate300"]).replace("__SLATE200__", T["slate200"])
            .replace("__SLATE50__", T["slate50"]).replace("__SLATE100__", T["slate100"]).replace("__BLUE100__", T["blue100"])
            .replace("__BLOOD__", T["blood"]).replace("__POS__", T["pos"]).replace("__NEG__", T["neg"])
            .replace("__FUNDLIGHT__", f["light"]).replace("__FUNDSOFT__", f["soft"]).replace("__FUNDTXT__", f["txt"])
            .replace("__FUND__", f["color"]).replace("__BORDER2__", T["border2"]).replace("__BORDER__", T["border"]))

# ------------------------------------------------------------------ seções
def sec_head(num, title_html, sub=None):
    t = f'<span class="t">{title_html}'
    if sub: t += f'<span class="sep">|</span><span class="sub">{sub}</span>'
    t += '</span>'
    return f'<div class="sh"><span class="num">{num}</span>{t}<span class="rule"></span></div>'

def header(d):
    tk = d["fundo"]["ticker"]; f = FUND[tk]
    lines = f["nome"].replace("FII ", "").split(" ", 1)
    return f"""
    <header class="header"><div class="gridtex"></div>
      <div class="hrow">
        <img class="hlogo" src="{ASSETS}/logos/logo_guardian_negativo.png" alt="Guardian Gestora">
        <div class="vsep"></div>
        <div class="htitle"><div class="ey">Cenário diário · {tk}</div><div class="h1">Relatório Passivo</div></div>
        <div class="hspace"></div>
        <div class="hdate"><div class="ey">Data de referência</div><div class="d geo">{esc(d["data"])}</div></div>
        <div class="hfund"><img src="{ASSETS}/logos/{f['icon']}" alt="{tk}">
          <div class="fn"><b>{tk}</b>FII {esc(lines[0])}<br>{esc(lines[1] if len(lines) > 1 else "")}</div></div>
      </div>
    </header>"""

def var_html(x, dec):
    return f'{arrow(x)}<span class="{cls_var(x)}">{esc(pct(x, dec))}</span>'

def rs(v):  # R$ + número
    return f'<span class="rs">R$</span>{esc(n(v, 2))}'

def sec01(d):
    tk = d["fundo"]["ticker"]; h = d["highlights"]; seg = FUND[tk]["segmento"]
    ic = lambda name: icon(name, "2.6mm", T["blood"])
    def pk(name, lab, val, vol=False):
        return f'<div class="pk{" vol" if vol else ""}"><div class="lab">{ic(name)}<span>{lab}</span></div><div class="val">{val}</div></div>'
    var = h["variacao"]
    hero = (f'<div class="hero"><div class="lab">{ic("clock")}<span>Preço fechamento</span></div>'
            f'<div class="val">{rs(h["preco_fech"])}</div>'
            f'<div class="var"><span class="lab">Variação {tk}</span><span class="chip {cls_var(var)}">{arrow(var)}{esc(pct(var, 2))}</span></div></div>')
    row1 = [pk("currency-dollar-simple", "Preço máximo", rs(h["preco_max"])),
            pk("currency-dollar-simple", "Preço mínimo", rs(h["preco_min"])),
            pk("clock-counter-clockwise", "Fechamento D-1", rs(h["fech_d1"])),
            pk("money", "Preço médio", rs(h["preco_med"])),
            pk("chart-line-up", "Var PMxPF", var_html(h["var_pmxpf"], 1))]
    if tk == "GARE11":
        row1.append(pk("percent", "Taxa short", esc(pct(h["taxa_short"], 1))))
    row2 = [pk("buildings" if seg == "TIJOLO" else "file-text", f"Var IFIX {seg.lower()}", var_html(h["var_ifix_seg"], 1)),
            pk("chart-bar", "Var IFIX", var_html(h["var_ifix"], 1)),
            pk("coins", 'Vol total <span class="sb">(MM)</span>', esc(n(h["vol_total_mm"], 2)), vol=True)]
    if tk == "GARE11":
        row2.append(pk("vault", 'Vol short <span class="sb">(MM)</span>', esc(n(h["vol_short_mm"], 2)), vol=True))
    row2 += [pk("chart-pie-slice", "Volume B3", esc(pct(h["volume_b3"], 0)), vol=True),
             pk("timer", "Daytrade", esc(pct(h["daytrade"], 0)), vol=True)]
    grid = f'<div class="pgrid"><div class="prow">{"".join(row1)}</div><div class="prow">{"".join(row2)}</div></div>'
    return sec_head("01", f"Highlights <b>{tk}</b>") + f'<div class="pan">{hero}{grid}</div>'


def table(cols, rows, widths=None):
    """cols: lista de (label_html, cls); rows: lista de (cls, [cell_html...])."""
    cg = "".join(f'<col style="width:{w}">' for w in widths) if widths else ""
    th = "".join(f'<th class="{c}">{l}</th>' for l, c in cols)
    tr = "".join(f'<tr class="{rc}">' + "".join(f'<td class="{cc}">{v}</td>' for v, cc in cells) + "</tr>" for rc, cells in rows)
    return f'<table class="tb"><colgroup>{cg}</colgroup><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'

def card(kind, title, unit, inner, style=""):
    u = f'<span class="u">{unit}</span>' if unit else ""
    return f'<div class="card {kind}" style="{style}"><div class="ct"><span class="t">{title}</span>{u}</div>{inner}</div>'

def sec02(d):
    tk = d["fundo"]["ticker"]; mm = d["market_maker"]
    cols = [("Nome", ""), ("Volume", ""), ("Part/dia", ""), ("Part/mês", ""), ("Preço médio", "")]
    w = ["26%", "17%", "17%", "17%", "23%"]
    def rows(lst):
        out = []
        for r in lst:
            rc = "others" if r["nome"].lower() == "others" else ""
            out.append((rc, [(esc(r["nome"]), ""), (esc(intbr(r["volume"])), ""), (esc(pct(r["part_dia"], 0)), ""),
                            (esc(pct(r["part_mes"], 0)), ""), (f'<span class="rs">R$</span>{esc(n(r["preco_medio"], 2))}', "")]))
        return out
    sold = card("venda", "Top sold", "Volume em R$ mil", table(cols, rows(mm["top_sold"]), w), "flex:38;")
    bought = card("compra", "Top bought", "Volume em R$ mil", table(cols, rows(mm["top_bought"]), w), "flex:38;")
    neg = [r for r in mm["saldo"] if round(r["saldo"]) < 0][:8]   # só o que aparece negativo na página (R$ mil inteiro)
    mx = max((abs(r["saldo"]) for r in neg), default=1)
    srows = [("", [(esc(r["nome"]), ""), (f'<div class="fill" style="width:{abs(r["saldo"]) / mx * 100:.1f}%"></div><span class="v">{esc(intbr(r["saldo"]))}</span>', "bar")]) for r in neg]
    saldo = card("neutro", "Saldo", "R$ mil", table([("Nome", ""), ("Saldo", "")], srows, ["58%", "42%"]), "flex:20;")
    return sec_head("02", "Relatório <b>Market Maker</b>") + f'<div class="cards">{sold}{bought}{saldo}</div>'


FAIXAS = ["0-1k", "1k-5k", "5k-20k", "20k-50k", "50k-100k", "100k-500k", "500k-1M", "1M-3M", "3M-15M", ">15M"]
VENDA_PF, VENDA_PJ = "#657791", "#c3c8cf"

def st(x, y, s, size=1.75, fill=None, anchor="start", family="Avenir", ls=0, weight=""):
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{family}" font-size="{size}" fill="{fill or T["slate"]}" '
            f'text-anchor="{anchor}" letter-spacing="{ls}"{weight}>{esc(s)}</text>')

def chart_pf_pj(p, tk, w=188.0, row_h=3.7, bar_h=1.4, top=6.0):
    """Barras divergentes: venda à esquerda (PF/PJ em cinzas), compra à direita (PF na cor do fundo, PJ no tom claro)."""
    f = FUND[tk]
    cols = {"venda_pf": VENDA_PF, "venda_pj": VENDA_PJ, "compra_pf": f["color"], "compra_pj": f["light2"]}
    lab_w = 13.0; label_room = 9.0
    cx = lab_w + (w - lab_w) / 2
    half = (w - lab_w) / 2 - label_room
    mx = max(max(p[k]) for k in cols) or 1
    scale = half / mx
    h = top + row_h * len(FAIXAS) + 1.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h:.2f}" width="{w}mm" height="{h:.2f}mm">']
    # legenda (topo direito) e direções
    lx = w - 2
    for key, text in reversed([("venda_pf", "Venda PF"), ("venda_pj", "Venda PJ"), ("compra_pf", "Compra PF"), ("compra_pj", "Compra PJ")]):
        tw = len(text) * 1.1 + 1.0
        lx -= tw
        out.append(st(lx, 2.6, text.upper(), 1.5, T["slate400"], "start", ls=0.12))
        lx -= 2.6
        out.append(f'<rect x="{lx:.2f}" y="1.15" width="1.9" height="1.9" fill="{cols[key]}"/>')
        lx -= 3.2
    out.append(st(cx - 2.2, 2.6, "◀ VENDA", 1.5, T["slate400"], "end", ls=0.12))
    out.append(st(cx + 2.2, 2.6, "COMPRA ▶", 1.5, T["slate400"], "start", ls=0.12))
    y0 = top
    for i, fx in enumerate(FAIXAS):
        y = y0 + i * row_h
        if i > 0:
            out.append(f'<line x1="{lab_w:.2f}" y1="{y:.2f}" x2="{w:.2f}" y2="{y:.2f}" stroke="{T["slate"]}" stroke-opacity=".22" stroke-width=".18" stroke-dasharray="1 .8"/>')
        out.append(st(lab_w - 1.6, y + row_h / 2 + 0.6, fx, 1.8, T["slate500"], "end"))
        for j, (sk, ck) in enumerate([("venda_pf", "compra_pf"), ("venda_pj", "compra_pj")]):
            by = y + 0.45 + j * (bar_h + 0.35)
            v = p[sk][i]
            if v > 0:
                bw = v * scale
                out.append(f'<rect x="{cx - bw:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bar_h}" fill="{cols[sk]}"/>')
                out.append(st(cx - bw - 0.8, by + bar_h - 0.25, pct(v / 100, 2), 1.55, T["slate500"], "end", family="Geo"))
            v = p[ck][i]
            if v > 0:
                bw = v * scale
                out.append(f'<rect x="{cx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bar_h}" fill="{cols[ck]}"/>')
                out.append(st(cx + bw + 0.8, by + bar_h - 0.25, pct(v / 100, 2), 1.55, T["slate500"], "start", family="Geo"))
    out.append(f'<line x1="{cx:.2f}" y1="{y0 - 1:.2f}" x2="{cx:.2f}" y2="{h - 0.6:.2f}" stroke="{T["slate"]}" stroke-width=".3"/>')
    out.append("</svg>")
    return "".join(out)

def sec03(d, k=1.0):
    tk = d["fundo"]["ticker"]
    svg = chart_pf_pj(d["participacao_pf_pj"], tk, row_h=3.7 * k)
    return sec_head("03", "Participação de <b>PF</b> e <b>PJ</b> no volume geral") + f'<div class="card chart neutro">{svg}</div>'


def sec04(d):
    tk = d["fundo"]["ticker"]; gare = tk == "GARE11"
    cols = [("Nome", ""), ("Categoria antiga", ""), ("PF_PJ", ""), ("Valor (R$)", ""), ("Categoria atual", "")]
    w = ["34%", "14.5%", "6%", "9%", "14.5%", "11%", "11%"] if gare else ["50%", "14%", "9%", "13%", "14%"]
    lim = 28 if gare else 36
    if gare: cols += [("GARE15", ""), ("GALG15", "")]
    def rows(lst, total):
        out = []
        for r in lst:
            cells = [(esc(trunc(r["nome"], lim)), ""),
                     (esc(r["cat_antiga"]), "nc" if r["cat_antiga"] == "NC" else "tag"),
                     (esc(r["pf_pj"]), "pf"), (esc(intbr(r["valor"])), "num"), (esc(r["cat_atual"]), "tag")]
            if gare:
                for k in ("gare15", "galg15"):
                    v = r.get(k, "AUSENTE")
                    cells.append(("–", "aus") if v == "AUSENTE" else (esc(v), "nc"))
            out.append(("", cells))
        tot = [("TOTAL", ""), ("–", "tag"), ("–", "tag"), (esc(intbr(total)), "num"), ("–", "tag")] + ([("–", "tag"), ("–", "tag")] if gare else [])
        out.append(("total", tot))
        return out
    v = d["vendedores"]; c = d["compradores"]
    cv = card("venda", "10+ Vendedores", "Valor em R$ mil", table(cols, rows(v["lista"], v["total"]), w), "flex:1;")
    cc = card("compra", "10+ Compradores", "Valor em R$ mil", table(cols, rows(c["lista"], c["total"]), w), "flex:1;")
    return sec_head("04", "<b>10+ Vendedores</b> e <b>10+ Compradores</b>") + f'<div class="cards">{cv}{cc}</div>'


def chart_faixas(c, tk, w=92.0, row_h=4.7, top=5.0, split=0.68):
    """Pane esquerda: CONCENTRAÇÃO POR FAIXA (% de cotas, PF/PJ). Pane direita: COTISTAS POR FAIXA (% de cotistas), eixo compartilhado."""
    f = FUND[tk]; cpf, cpj, cgray = f["color"], f["light2"], T["slate300"]
    lab_w = 13.0; gap = 4.0
    wl = (w - lab_w) * split - gap; xl = lab_w
    xr = lab_w + wl + gap; wr = w - xr
    h = top + row_h * len(FAIXAS) + 0.8
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h:.2f}" width="{w}mm" height="{h:.2f}mm" preserveAspectRatio="xMinYMin meet">']
    out.append(st(xl, 2.2, "CONCENTRAÇÃO POR FAIXA", 1.75, T["slate"], ls=0.16))
    out.append(st(xr, 2.2, "COTISTAS POR FAIXA", 1.75, T["slate"], ls=0.16))
    # legenda PF/PJ
    lx = xl + wl
    for text, col in [("PJ", cpj), ("PF", cpf)]:
        out.append(st(lx, 2.2, text, 1.45, T["slate400"], "end", ls=0.1)); lx -= 3.2
        out.append(f'<rect x="{lx - 0.6:.2f}" y=".85" width="1.7" height="1.7" fill="{col}"/>'); lx -= 3.4
    mx1 = max(max(c["pf_faixa"]), max(c["pj_faixa"])) or 1; s1 = (wl - 8.5) / mx1
    mx2 = max(c["cotistas"]) or 1; s2 = (wr - 8.0) / mx2
    bh = 1.3
    for i, fx in enumerate(FAIXAS):
        y = top + i * row_h
        if i > 0:
            out.append(f'<line x1="{lab_w:.2f}" y1="{y:.2f}" x2="{w:.2f}" y2="{y:.2f}" stroke="{T["slate"]}" stroke-opacity=".22" stroke-width=".18" stroke-dasharray="1 .8"/>')
        out.append(st(lab_w - 1.6, y + row_h / 2 + 0.6, fx, 1.75, T["slate500"], "end"))
        for j, (k, col) in enumerate([("pf_faixa", cpf), ("pj_faixa", cpj)]):
            v = c[k][i]; by = y + 0.65 + j * (bh + 0.25)
            if v > 0:
                bw = max(v * s1, 0.25)
                out.append(f'<rect x="{xl:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh}" fill="{col}"/>')
                if v >= 0.5:
                    out.append(st(xl + bw + 0.7, by + bh - 0.15, pct(v / 100, 2), 1.45, T["slate500"], family="Geo"))
        v = c["cotistas"][i]; bh2 = 2.0; by = y + (row_h - bh2) / 2
        bw = max(v * s2, 0.25) if v > 0 else 0
        if bw: out.append(f'<rect x="{xr:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh2}" fill="{cgray}"/>')
        out.append(st(xr + bw + 0.7, by + bh2 / 2 + 0.55, pct(v / 100, 1), 1.45, T["slate500"], family="Geo"))
    out.append(f'<line x1="{xl:.2f}" y1="{top - 0.6:.2f}" x2="{xl:.2f}" y2="{h - 0.4:.2f}" stroke="{T["slate"]}" stroke-width=".25"/>')
    out.append(f'<line x1="{xr:.2f}" y1="{top - 0.6:.2f}" x2="{xr:.2f}" y2="{h - 0.4:.2f}" stroke="{T["slate"]}" stroke-width=".25"/>')
    out.append("</svg>")
    return "".join(out)

def sec05(d):
    tk = d["fundo"]["ticker"]; c = d["cotas_faixa"]; f = FUND[tk]
    chart = f'<div class="card chart neutro" style="flex:50;">{chart_faixas(c, tk)}</div>'
    pf, pj = c["pf"], c["pj"]; m = c["mov"]
    dark = (f'<div class="card dark" style="flex:15;"><div class="dt">Concentração</div>'
            f'<div class="split"><div class="pf" style="width:{pf * 100:.1f}%"></div><div class="pj" style="flex:1"></div></div>'
            f'<div class="pfpj"><div><span class="l"><span class="sw" style="background:{f["color"]}"></span>PF</span><span class="v">{esc(pct(pf, 0))}</span></div>'
            f'<div><span class="l"><span class="sw" style="background:rgba(255,255,255,.35)"></span>PJ</span><span class="v">{esc(pct(pj, 0))}</span></div></div>'
            f'<div class="mov"><div class="dt">Mov cotistas</div>'
            + "".join(f'<div class="mr"><span class="l">{l}</span><span class="v">{esc(intbr(m[k]))}</span></div>'
                      for l, k in [("Entrada - dia", "entrada_dia"), ("Saída - dia", "saida_dia"), ("Entrada - mês", "entrada_mes"), ("Saída - mês", "saida_mes")])
            + f'<div class="mr tot"><span class="l">Total</span><span class="v">{esc(intbr(m["total"]))}</span></div></div></div>')
    rows = [("", [(esc(trunc(r["nome"], 30)), ""), (esc(r["categoria"]), "tag"), (esc(intbr(r["valor"])), "num")]) for r in c["maiores"]]
    tbl = card("neutro", "15 Maiores posições", "R$ mil", table([("Nome", ""), ("Categorias", ""), ("R$ mil", "")], rows, ["58%", "22%", "20%"]), "flex:35;")
    return sec_head("05", "<b>Cotas</b> por faixa de <b>investimento</b>") + f'<div class="cards">{chart}{dark}{tbl}</div>'

SECTIONS = {"01": sec01, "02": sec02, "03": sec03, "04": sec04, "05": sec05}

def build_html(d, sections=None, k=1.0):
    tk = d["fundo"]["ticker"]
    parts = [header(d)] if (sections is None or "header" in sections) else []
    body = []
    for key in ["01", "02", "03", "04", "05"]:
        if (sections is None or key in sections) and key in SECTIONS:
            fn = SECTIONS[key]
            body.append(f'<section class="sec s{key}">{fn(d, k) if key == "03" else fn(d)}</section>')
    parts.append(f'<div class="body">{"".join(body)}</div>')
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{css_for(tk, k)}</style></head><body><div class="page">{"".join(parts)}</div></body></html>'

def content_bottom_mm(pdf_bytes):
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) > 1: return 999.0
    pg = doc[0]
    ys = [b[3] for b in pg.get_text("blocks")]
    for dr in pg.get_drawings():
        if dr["rect"].height < 700:  # ignora o fundo branco da página
            ys.append(dr["rect"].y1)
    return max(ys) / 72 * 25.4

def fit_k(d, sections=None, target=291.0, kmax=1.6):
    """Fator k (respiro entre seções + altura do gráfico 03) para o conteúdo terminar perto do rodapé da A4.
    A altura é linear em k: duas medições, interpolação e uma conferência (nunca mais de 1 página)."""
    def bottom(k):
        return content_bottom_mm(HTML(string=build_html(d, sections, k), base_url=HERE).write_pdf())
    b1, b2 = bottom(1.0), bottom(1.2)
    if b1 >= target or b2 <= b1: return 1.0
    k = min(kmax, round(1.0 + (target - b1) / (b2 - b1) * 0.2, 2))
    while k > 1.0 and bottom(k) > target + 0.5:
        k = round(k - 0.05, 2)
    return max(k, 1.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json"); ap.add_argument("pdf")
    ap.add_argument("--html"); ap.add_argument("--sections", help="header,01,02,03,04,05"); ap.add_argument("--no-fit", action="store_true")
    a = ap.parse_args()
    d = json.load(open(a.json, encoding="utf-8"))
    secs = a.sections.split(",") if a.sections else None
    k = fit_k(d, secs) if (secs is None and not a.no_fit) else 1.0
    doc_html = build_html(d, secs, k)
    print(f"k={k}")
    if a.html: open(a.html, "w", encoding="utf-8").write(doc_html)
    HTML(string=doc_html, base_url=HERE).write_pdf(a.pdf)
    print("ok", a.pdf)

if __name__ == "__main__":
    main()
