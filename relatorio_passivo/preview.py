#!/usr/bin/env python3
"""Renderiza os PDFs dos dois fundos só com as seções pedidas e monta um PNG de preview empilhado.
Uso: python3 preview.py <sections> <saida.png> [--crop y0,y1]   (frações da altura da página, ex.: 0.06,0.2)
"""
import sys, subprocess, argparse, pymupdf
from PIL import Image
HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("sections"); ap.add_argument("png"); ap.add_argument("--crop", default=None)
ap.add_argument("--dpi", type=int, default=220); ap.add_argument("--fundos", default="gare,game")
a = ap.parse_args()
imgs = []
for f in a.fundos.split(","):
    pdf = f"{HERE}/out/prev_{f}.pdf"
    subprocess.run([sys.executable, f"{HERE}/build_passivo.py", f"{HERE}/out/dados_{f}.json", pdf, "--sections", a.sections], check=True, capture_output=True)
    doc = pymupdf.open(pdf); pix = doc[0].get_pixmap(dpi=a.dpi); png = pdf.replace(".pdf", ".png"); pix.save(png)
    im = Image.open(png); w, h = im.size
    if a.crop:
        y0, y1 = [float(x) for x in a.crop.split(",")]
        im = im.crop((0, int(h * y0), w, int(h * y1)))
    imgs.append(im)
W = max(i.width for i in imgs); H = sum(i.height for i in imgs) + 24 * (len(imgs) - 1)
out = Image.new("RGB", (W, H), "#d8d8d8"); y = 0
for i in imgs: out.paste(i, (0, y)); y += i.height + 24
out.save(a.png); print(out.size, a.png)
