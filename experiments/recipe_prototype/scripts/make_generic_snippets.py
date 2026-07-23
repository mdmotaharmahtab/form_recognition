"""Render the visuals for the generic-clustering section of the deep-dive doc
(docs/assets/gen_*.png), all computed from the real corpus:

  gen_chrome.png  QSC eSource page 10 with every line boxed by its token's
                  ubiquity weight: gray = chrome (weight ~0, printed on ~every
                  page, discovered per document), green = discriminative.
  gen_theta.png   theta stability selection on the QSC book: stacks vs theta,
                  adjacent-partition Rand index, the detected plateau, and the
                  chosen theta*.
"""
import os
from collections import Counter

import fitz
from PIL import Image, ImageDraw, ImageFont

from common import build_page_lines
from generic_profile import (X_BINS, _charclass, _size_rel, page_profile,
                             select_theta, token_weights)

CRF = r"..\..\data\crf_forms"
OUT = r"..\..\docs\assets"
os.makedirs(OUT, exist_ok=True)

GREEN = (15, 123, 77)
GRAY = (158, 158, 158)
FONT_B = "C:/Windows/Fonts/arialbd.ttf"
FONT_R = "C:/Windows/Fonts/arial.ttf"


def save(img, name):
    path = os.path.join(OUT, name)
    img.save(path)
    print(f"{name}: {img.width}x{img.height}")


# ---- chrome discovery on QSC page 10 ----------------------------------------
doc = fitz.open(os.path.join(CRF, "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf"))
page_lines = {i: build_page_lines(doc[i]) for i in range(doc.page_count)}
profiles = {i: page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height)
            for i in page_lines}
w = token_weights(profiles)

page = doc[9]
lines = page_lines[9]
sizes = Counter(round(L.size, 1) for L in lines)
modal = sizes.most_common(1)[0][0]

z = 2.0
pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
d = ImageDraw.Draw(img)
n_chrome = n_disc = 0
for L in lines:
    xb = min(X_BINS - 1, int(L.x0 / max(page.rect.width, 1) * X_BINS))
    tok = (xb, _size_rel(L.size, modal), "B" if L.bold else ".",
           "C" if L.non_black else ".", _charclass(L.text))
    weight = w.get(tok, 0.0)
    # DISPLAY cutoff only (the pipeline's damping is smooth, no threshold):
    # w<0.1 = tokens on >~96% of pages, the visually unmistakable chrome
    chrome = weight < 0.1
    n_chrome += chrome
    n_disc += not chrome
    d.rectangle([L.x0 * z - 4, L.y0 * z - 2, L.x1 * z + 4, L.y1 * z + 2],
                outline=GRAY if chrome else GREEN, width=3 if chrome else 4)

# crop to the region that shows both chrome (header block) and content
img = img.crop((0, 0, img.width, int(430 * z)))
# legend strip on top
LEG_H = 74
canvas = Image.new("RGB", (img.width, img.height + LEG_H), (255, 255, 255))
canvas.paste(img, (0, LEG_H))
d = ImageDraw.Draw(canvas)
f26 = ImageFont.truetype(FONT_B, 30)
f22 = ImageFont.truetype(FONT_R, 24)
d.rectangle([24, 20, 58, 52], outline=GRAY, width=4)
d.text((72, 36), "chrome - token on ~every page, weight ~0", font=f22, fill=(90, 90, 90), anchor="lm")
x2 = 24 + d.textlength("chrome - token on ~every page, weight ~0", font=f22) + 110
d.rectangle([x2, 20, x2 + 34, 52], outline=GREEN, width=4)
d.text((x2 + 48, 36), "discriminative - carries template identity", font=f22, fill=GREEN, anchor="lm")
save(canvas, "gen_chrome.png")
print(f"p10: {n_chrome} chrome-weighted lines, {n_disc} discriminative")

# ---- theta stability selection chart (matplotlib) ----------------------------
theta, diag = select_theta(profiles)
doc.close()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

grid = diag["grid"]
stacks = diag["n_stacks"]
adj = diag["adjacent_rand"]
runs = diag["runs"]

fig, ax = plt.subplots(figsize=(8.6, 3.9), dpi=150)
ax.plot(grid, stacks, "o-", color="#1d5fbf", lw=2, ms=6, zorder=3, label="stacks found")
for s, e in runs:
    # pair run s..e spans grid indices s..e+1
    ax.axvspan(grid[s], grid[e + 1], color="#0f7b4d", alpha=0.10, zorder=1)
# annotate adjacent Rand index between grid points
for i, ri in enumerate(adj):
    xm = (grid[i] + grid[i + 1]) / 2
    ok = ri >= 0.97
    ax.annotate(f"{ri:.2f}", (xm, max(stacks) * 0.97), ha="center", fontsize=8.5,
                color="#0f7b4d" if ok else "#b3382e",
                fontweight="bold" if ok else "normal")
ax.annotate("Rand index between adjacent partitions\n(green $\\geq$ 0.97 = unchanged)",
            (grid[0], max(stacks) * 0.80), fontsize=8.5, color="#5b6472")
ax.axvline(theta, color="#b0680e", lw=1.6, ls="--", zorder=2)
ax.annotate(f"chosen $\\theta^*$ = {theta:.2f}\n(middle of widest plateau)",
            (theta + 0.006, stacks[grid.index(theta)] + 2.2), fontsize=9.5,
            color="#b0680e", fontweight="bold")
ax.set_xlabel("similarity threshold $\\theta$")
ax.set_ylabel("number of stacks")
ax.set_title("QSC eSource book (609 pages): the partition itself picks $\\theta$", fontsize=11)
ax.set_xticks(grid)
ax.set_ylim(0, max(stacks) + 3.5)
ax.grid(axis="y", alpha=0.25)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "gen_theta.png"))
print(f"gen_theta.png: theta*={theta}, stacks={stacks}, runs={runs}")
