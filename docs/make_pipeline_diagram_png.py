"""Render docs/crf_pipeline_simple.png - one-glance graph of the codegen pipeline.

Layout is an S-flow: steps 1-3 left-to-right on the top row, step 4 drops down,
step 5 (stop rule) sits under the code agent so the loop-back arrow is a short
vertical hop. Numbers/labels follow the team's 5-step framing.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK = "#1c2430"
MUT = "#5b6472"
PY_BG, PY_ED, PY_TX = "#e9f5ef", "#0f7b4d", "#0d5137"
AI_BG, AI_ED, AI_TX = "#eaf1fc", "#1d5fbf", "#16498f"
LP_BG, LP_ED, LP_TX = "#fdf3e3", "#b0680e", "#8a5209"

fig, ax = plt.subplots(figsize=(15.5, 8.2), dpi=200)
ax.set_xlim(0, 100)
ax.set_ylim(0, 56)
ax.axis("off")
fig.patch.set_facecolor("white")


def box(x, y, w, h, bg, ed, num, title, tcol, lines, lh=1.55):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.55,rounding_size=1.1",
                                facecolor=bg, edgecolor=ed, linewidth=1.6))
    if num:
        ax.add_patch(plt.Circle((x + 1.9, y + h - 1.7), 1.35, facecolor=ed, edgecolor="none"))
        ax.text(x + 1.9, y + h - 1.75, num, ha="center", va="center",
                fontsize=10.5, fontweight="bold", color="white")
        tx = x + 3.9
    else:
        tx = x + 1.6
    ax.text(tx, y + h - 1.75, title, ha="left", va="center",
            fontsize=10.5, fontweight="bold", color=tcol)
    for i, ln in enumerate(lines):
        ax.text(x + 1.6, y + h - 4.1 - i * lh, ln, ha="left", va="center",
                fontsize=8.8, color=INK)


def arrow(p0, p1, color=MUT, style="-", lw=1.8, rad=0.0):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=16,
                                 linewidth=lw, color=color, linestyle=style,
                                 connectionstyle=f"arc3,rad={rad}", zorder=5))


ax.text(2, 54.4, "Unknown-format CRF digitizer - the agentic codegen loop",
        fontsize=15.5, fontweight="bold", color=INK)
ax.text(2, 52.1, "The LLM never reads the document. It writes a parser for it; "
                 "deterministic Python runs and grades that parser on every page.",
        fontsize=10, color=MUT)

TOP_Y, TOP_H = 36.5, 12.5
BOT_Y, BOT_H = 15.5, 12.5

# input chip
ax.add_patch(FancyBboxPatch((1.5, 40.2), 10.5, 5.6, boxstyle="round,pad=0.55,rounding_size=1.1",
                            facecolor="white", edgecolor="#b9b4a6", linewidth=1.4))
ax.text(6.75, 44.0, "CRF PDF", ha="center", va="center", fontsize=10.5, fontweight="bold", color=INK)
ax.text(6.75, 42.0, "any format\nup to ~1000 pages", ha="center", va="center", fontsize=8.2, color=MUT)

box(15, TOP_Y, 21, TOP_H, PY_BG, PY_ED, "1", "Page-layout clustering", PY_TX, [
    "each line \u2192 typography token; page =",
    "its token set (words ignored); doc's own",
    "boilerplate discounted; threshold self-",
    "picked per doc. e.g. 404 pages \u2192 5 clusters",
])
box(44, TOP_Y, 21, TOP_H, AI_BG, AI_ED, "2", "Code agent  (LLM)", AI_TX, [
    "sees 4-12 representative pages",
    "(1-2 per big cluster)",
    "writes a deterministic extractor:",
    "python code with structural rules",
])
box(73, TOP_Y, 21, TOP_H, PY_BG, PY_ED, "3", "Sandbox verifier", PY_TX, [
    "is the code safe to run? (no LLM)",
    "import allow-list, no I/O,",
    "no network, hard timeout,",
    "throwaway subprocess",
])
box(73, BOT_Y, 21, BOT_H, PY_BG, PY_ED, "4", "Deterministic reviewer", PY_TX, [
    "runs extractor on ALL pages (free)",
    "gates: empty? junk labels? crash?",
    "coverage map \u2192 which clusters",
    "produced nothing",
])
box(44, BOT_Y, 21, BOT_H, LP_BG, LP_ED, "5", "Continue or stop?", LP_TX, [
    "stop on diminishing return (no gain",
    "vs previous version) or max 5 versions;",
    "clean gates + zero audit issues = done.",
    "best version wins, not the last",
])
# output
ax.add_patch(FancyBboxPatch((15, BOT_Y), 21, BOT_H, boxstyle="round,pad=0.55,rounding_size=1.1",
                            facecolor=INK, edgecolor=INK, linewidth=1.6))
ax.text(16.6, BOT_Y + BOT_H - 1.75, "Output", ha="left", va="center",
        fontsize=11, fontweight="bold", color="white")
for i, ln in enumerate(["best extractor kept + audit trail",
                        "CSV: form_name \u00b7 field_name \u00b7 page",
                        "\u2192 name-to-OID mapping downstream",
                        "real run: 1,242 fields / 76 forms"]):
    ax.text(16.6, BOT_Y + BOT_H - 4.1 - i * 1.55, ln, ha="left", va="center",
            fontsize=8.8, color="#dbe2ea")

MID_T = TOP_Y + TOP_H / 2
MID_B = BOT_Y + BOT_H / 2
arrow((12.6, MID_T), (14.2, MID_T))
arrow((36.7, MID_T), (43.2, MID_T))
ax.text(40.0, MID_T + 1.6, "4-12 pages", ha="center", fontsize=8, color=MUT)
arrow((65.7, MID_T), (72.2, MID_T))
ax.text(69.0, MID_T + 1.6, "code", ha="center", fontsize=8, color=MUT)
arrow((83, TOP_Y - 0.7), (83, BOT_Y + BOT_H + 0.8))
ax.text(84.2, (TOP_Y + BOT_Y + BOT_H) / 2 + 0.1, "run on all pages", ha="left", fontsize=8, color=MUT)
arrow((72.2, MID_B), (65.7, MID_B))
ax.text(69.0, MID_B + 1.6, "verdict", ha="center", fontsize=8, color=MUT)
arrow((43.2, MID_B), (36.7, MID_B), color=PY_ED)
ax.text(40.0, MID_B + 1.6, "stop", ha="center", fontsize=8, color=PY_ED, fontweight="bold")

# loop-back: step 5 -> step 2 (the agent's own LLM self-review, hence blue)
arrow((54, BOT_Y + BOT_H + 0.8), (54, TOP_Y - 0.7), color=AI_ED, style="--", lw=2.0)
ax.text(55.2, (TOP_Y + BOT_Y + BOT_H) / 2 + 2.15, "loop (LLM self-audit): agent re-reads a few",
        ha="left", fontsize=8, color=AI_TX)
ax.text(55.2, (TOP_Y + BOT_Y + BOT_H) / 2 + 0.55, "real pages beside its own output, confirms",
        ha="left", fontsize=8, color=AI_TX)
ax.text(55.2, (TOP_Y + BOT_Y + BOT_H) / 2 - 1.05, "empty clusters, fixes missed / false fields",
        ha="left", fontsize=8, color=AI_TX)
ax.text(55.2, (TOP_Y + BOT_Y + BOT_H) / 2 - 2.65, "\u2192 writes revised / extended code",
        ha="left", fontsize=8, color=AI_TX)

# legend
lx = 2
for bg, ed, label, w in [(PY_BG, PY_ED, "deterministic Python - free, repeatable", 26),
                         (AI_BG, AI_ED, "LLM agent (Sonnet 4.5): writes + audits the parser (7-10 calls/doc)", 40),
                         (LP_BG, LP_ED, "bounded loop control", 16)]:
    ax.add_patch(FancyBboxPatch((lx, 3.2), 1.8, 1.8, boxstyle="round,pad=0.28,rounding_size=0.5",
                                facecolor=bg, edgecolor=ed, linewidth=1.3))
    ax.text(lx + 3.0, 4.1, label, fontsize=8.6, color=MUT, va="center")
    lx += w
ax.text(2, 0.9, "LLM cost scales with the number of layout clusters, never with page count - "
                "a 1000-page CRF costs the same handful of calls as a 100-page one.",
        fontsize=8.6, color=MUT, style="italic")

fig.savefig(r"D:\ubuntu\codes\ZS\otsuka\ECS\docs\crf_pipeline_simple.png",
            bbox_inches="tight", facecolor="white")
print("saved docs/crf_pipeline_simple.png")
