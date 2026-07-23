"""Render annotated snippets from the real CRF PDFs for the deep-dive doc
(docs/assets/sig_*.png). Each image shows the exact page region a fingerprint
signal reacts to, with the counted lines boxed, so the doc explains the signals
visually instead of by description."""
import os

import fitz
from PIL import Image, ImageDraw, ImageFont

from common import BRACKET_LINE, INT_ONLY, build_page_lines

CRF = r"..\..\data\crf_forms"
OUT = r"..\..\docs\assets"
os.makedirs(OUT, exist_ok=True)

GREEN = (15, 123, 77)
INK = (28, 36, 48)
GRAY = (150, 150, 150)

FONT = "C:/Windows/Fonts/arialbd.ttf"


def render(page, zoom):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def box(draw, line, zoom, color=GREEN, w=4):
    draw.rectangle([line.x0 * zoom - 5, line.y0 * zoom - 3,
                    line.x1 * zoom + 5, line.y1 * zoom + 3], outline=color, width=w)


def save(img, name):
    path = os.path.join(OUT, name)
    img.save(path)
    print(f"{name}: {img.width}x{img.height}")


# ---- 1. bracket-only lines: OID-annotated aCRF page ------------------------
doc = fitz.open(os.path.join(CRF, "384-201-00004_aCRF_16JAN2025.pdf"))
page = doc[3]  # page 4
lines = build_page_lines(page)
z = 2.0
img = render(page, z)
d = ImageDraw.Draw(img)
brackets = [L for L in lines if BRACKET_LINE.match(L.text)]
for L in brackets:
    box(d, L, z)
y_top = max(0, min(L.y0 for L in brackets[:8]) - 18)
img = img.crop((0, int(y_top * z), img.width, int(min(page.rect.height, y_top + 265) * z)))
save(img, "sig_brackets.png")
doc.close()

# ---- 2. integer-only lines: Unique CRF p133 field-number column ------------
doc = fitz.open(os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"))
page = doc[132]
lines = build_page_lines(page)
img = render(page, z)
d = ImageDraw.Draw(img)
for L in lines:
    if INT_ONLY.match(L.text):
        box(d, L, z)
img_int = img.crop((0, int(138 * z), img.width, int(340 * z)))
save(img_int, "sig_integers.png")

# ---- 5. x-histogram: p133 with 4 column bins + line-start markers ----------
img = render(page, z)
overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
od = ImageDraw.Draw(overlay)
W = img.width
fired = [True, False, False, True]  # 12-0-1-12 -> "1001"
for b in range(4):
    x0b, x1b = b * W / 4, (b + 1) * W / 4
    if fired[b]:
        od.rectangle([x0b, 0, x1b, img.height], fill=(15, 123, 77, 32))
    if b:
        od.line([x0b, 0, x0b, img.height], fill=(120, 120, 120, 170), width=2)
img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
d = ImageDraw.Draw(img)
for L in lines:  # mark where every line STARTS - this is what the histogram counts
    cx, cy = L.x0 * z, (L.y0 + L.y1) / 2 * z
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=(176, 104, 14), outline=(255, 255, 255), width=2)
f42 = ImageFont.truetype(FONT, 46)
f26 = ImageFont.truetype(FONT, 30)
for b, (bit, cnt) in enumerate(zip("1001", [12, 0, 1, 12])):
    cx = (b + 0.5) * W / 4
    col = GREEN if bit == "1" else GRAY
    d.text((cx, 26), bit, font=f42, fill=col, anchor="mm")
    d.text((cx, 68), f"{cnt} line start" + ("s" if cnt != 1 else ""), font=f26, fill=col, anchor="mm")
save(img, "sig_xhist.png")
doc.close()

# ---- 3. colored lines: QSC eSource template chrome -------------------------
doc = fitz.open(os.path.join(CRF, "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf"))
page = doc[9]  # page 10
lines = build_page_lines(page)
img = render(page, z)
d = ImageDraw.Draw(img)
colored = [L for L in lines if L.non_black]
for L in colored:
    box(d, L, z, w=4)
y_top = max(0, min(L.y0 for L in colored) - 14)
img = img.crop((0, int(y_top * z), img.width, int((y_top + 205) * z)))
save(img, "sig_colored.png")
doc.close()

# ---- 4. density strip: four page families at a glance ----------------------
CASES = [
    (os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"), 1, "title page", "8 lines", "s"),
    (os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"), 133, "entry form", "25 lines", "m"),
    (os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"), 116, "data dictionary", "65 lines", "l"),
    (os.path.join(CRF, "384-201-00004_aCRF_16JAN2025.pdf"), 4, "aCRF definition", "152 lines", "xl"),
]
TH, GAP, LABEL_H = 470, 22, 78
thumbs = []
for path, p1, *_ in CASES:
    doc = fitz.open(path)
    page = doc[p1 - 1]
    zz = TH / page.rect.height
    thumbs.append(render(page, zz))
    doc.close()
total_w = sum(t.width for t in thumbs) + GAP * (len(thumbs) + 1)
strip = Image.new("RGB", (total_w, TH + LABEL_H + GAP * 2), (255, 255, 255))
d = ImageDraw.Draw(strip)
f28 = ImageFont.truetype(FONT, 27)
f22 = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
x = GAP
for t, (path, p1, name, nl, bucket) in zip(thumbs, CASES):
    strip.paste(t, (x, GAP))
    d.rectangle([x, GAP, x + t.width - 1, GAP + t.height - 1], outline=(200, 196, 184), width=2)
    cx = x + t.width // 2
    d.text((cx, GAP + TH + 22), f"{name}", font=f28, fill=INK, anchor="mm")
    d.text((cx, GAP + TH + 54), f'{nl}  \u2192  "{bucket}"', font=f22, fill=GREEN, anchor="mm")
    x += t.width + GAP
save(strip, "sig_density.png")
