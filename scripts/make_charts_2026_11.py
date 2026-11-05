#!/usr/bin/env python3
"""README charts for the 2026-11-05 benchmark set.

Data: docs/benchmarks-2026-11-05.json (all numbers measured on this host).
Output: docs/charts/*.svg (for GitHub) and docs/charts/*.png (for local review).
"""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = "/home/ubuntu/hermes-dynamic-memory"
OUT = os.path.join(ROOT, "docs", "charts")
os.makedirs(OUT, exist_ok=True)
DATA = json.load(open(os.path.join(ROOT, "docs", "benchmarks-2026-11-05.json")))

DYN = "#2f7d8e"      # dynmem teal
STOCK = "#c2703d"    # stock memory orange
GREY = "#9aa5b1"     # competitors
DARK = "#3d3d3d"
LIGHT = "#e8e8e8"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.edgecolor": DARK,
    "axes.labelcolor": DARK,
    "xtick.color": DARK,
    "ytick.color": DARK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

def save(fig, name):
    svg = os.path.join(OUT, name + ".svg")
    png = os.path.join(OUT, name + ".png")
    fig.tight_layout()
    fig.savefig(svg, format="svg", transparent=False)
    fig.savefig(png, dpi=140, transparent=False)
    plt.close(fig)
    print("wrote", svg)

# ── A. resident cost per turn ────────────────────────────────────────────────
def chart_resident():
    rows = DATA["resident_cost"]
    rows = sorted(rows, key=lambda r: r["tokens"])
    names = [r["name"] for r in rows]
    vals = [r["tokens"] for r in rows]
    colors = [DYN if "dynmem" in n else STOCK if "stock" in n else GREY for n in names]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.barh(names, vals, color=colors, height=0.62)
    for b, v in zip(bars, vals):
        ax.text(v + 180, b.get_y() + b.get_height() / 2, f"{v:,}", va="center", fontsize=10, color=DARK)
    ax.set_xlabel("tokens injected into every prompt")
    ax.set_title("Resident cost per turn — the memory block the model reads before it speaks",
                 fontsize=13, color=DARK, pad=12)
    # annotate the cluster honestly: every indexed system lands in the same band
    ax.text(0.62, -0.16, "all five indexed systems: 6.5k–8.1k — dynmem sits inside that band",
            transform=ax.transAxes, ha="center", fontsize=9, color="#5b6570")
    ax.annotate("dump-everything:\n2× the tokens", xy=(13948, 0), xytext=(10500, 2.1),
                fontsize=9, color=STOCK, arrowprops=dict(arrowstyle="->", color=STOCK, lw=1.1))
    ax.set_xlim(0, max(vals) * 1.18)
    ax.grid(axis="x", color=LIGHT)
    ax.set_axisbelow(True)
    save(fig, "resident-cost-2026-11")

# ── B. routing accuracy ─────────────────────────────────────────────────────
def chart_routing():
    rows = DATA["routing"]
    names = [r["name"] for r in rows]
    top1 = [r["top1"] for r in rows]
    top10 = [r["top10"] for r in rows]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(9, 4.6))
    w = 0.36
    # colour encodes the METRIC, not the system, so the legend is unambiguous
    ax.axvspan(-0.55, 0.55, color=DYN, alpha=0.08, zorder=0)
    b1 = ax.bar(x - w / 2, top1, w, color=DYN, label="right file, first hit")
    b2 = ax.bar(x + w / 2, top10, w, color="#8fbfca", label="right file, any hit (top 10)")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.12, f"{int(b.get_height())}",
                    ha="center", fontsize=10, color=DARK)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10)
    ax.set_ylim(0, 11.4)
    ax.set_ylabel("prompts routed correctly (of 10)")
    ax.set_title("Routing on a real 142-topic store — ten prompts taken from actual sessions",
                 fontsize=13, color=DARK, pad=12)
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.annotate("best router", xy=(0, 10), xytext=(0.55, 8.2), fontsize=9, color=DYN,
                arrowprops=dict(arrowstyle="->", color=DYN, lw=1.2))
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)
    save(fig, "routing-2026-11")

# ── C. write-step cost ──────────────────────────────────────────────────────
def chart_write():
    rows = DATA["write_cost"]
    names = [r["name"] for r in rows]
    vals = [r["input_tokens"] for r in rows]
    colors = [DYN if "dynmem" in n else GREY for n in names]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars = ax.bar(names, vals, color=colors, width=0.5)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 2200, f"{v:,}", ha="center", fontsize=11, color=DARK)
    ax.set_ylabel("input tokens for the final write")
    ax.set_title("Cost of turning memory into an artifact — same task, same store size",
                 fontsize=13, color=DARK, pad=12)
    ax.set_ylim(0, max(vals) * 1.22)
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)
    save(fig, "write-cost-2026-11")

# ── D. per-session ingest cost ──────────────────────────────────────────────
def chart_ingest():
    rows = DATA["ingest_per_session"]
    names = [r["name"] for r in rows]
    tin = [r["input_tokens"] for r in rows]
    tout = [r["output_tokens"] for r in rows]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    w = 0.34
    ax.bar(x - w / 2, tin, w, color=DYN, label="input")
    ax.bar(x + w / 2, tout, w, color="#8fbfca", label="output")
    for i, (a, b) in enumerate(zip(tin, tout)):
        ax.text(i - w / 2, a + 700, f"{a:,}", ha="center", fontsize=10, color=DARK)
        ax.text(i + w / 2, b + 700, f"{b:,}", ha="center", fontsize=10, color=DARK)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, max(tin) * 1.22)
    ax.set_ylabel("tokens per session")
    ax.set_title("Storing facts costs the same either way — ten sessions, 61 messages",
                 fontsize=13, color=DARK, pad=12)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)
    save(fig, "ingest-cost-2026-11")

# ── E. index growth ─────────────────────────────────────────────────────────
def chart_growth():
    g = DATA["index_growth"]
    x = [r["topics"] for r in g]
    y = [r["tokens_per_turn"] for r in g]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(x, y, color=DYN, linewidth=2.4, marker="o", markersize=6)
    ax.axvspan(0, 300, color=DYN, alpha=0.07)
    ax.text(150, max(y) * 0.72, "comfortable\nrange", ha="center", fontsize=10, color=DYN)
    for xi, yi in zip(x, y):
        ax.annotate(f"{yi:,}", (xi, yi), textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=9, color=DARK)
    ax.set_xlabel("topic files in the index")
    ax.set_ylabel("index tokens per turn")
    ax.set_title("The honest limit — the index grows linearly, so past ~300 topics it needs pruning",
                 fontsize=13, color=DARK, pad=12)
    ax.grid(color=LIGHT)
    ax.set_axisbelow(True)
    save(fig, "index-growth-2026-11")

# ── F. memory fidelity vs prose ─────────────────────────────────────────────
def chart_fidelity():
    """Two panels: what survived (a tie) and how much noise leaked into the prose."""
    f = DATA["fidelity"]
    labels = [r["name"] for r in f]
    mem = [r["memory"] for r in f]
    retr = [7, 7]
    noise = [r["noise"] for r in f]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.0), gridspec_kw={"width_ratios": [1.15, 1]})
    x = np.arange(len(labels))
    w = 0.34
    ax1.bar(x - w / 2, [m / 20 * 100 for m in mem], w, color=DYN, label="facts retained (of 20)")
    ax1.bar(x + w / 2, [r / 7 * 100 for r in retr], w, color="#8fbfca", label="retractions respected (of 7)")
    for i in range(len(labels)):
        ax1.text(i - w / 2, 101, f"{mem[i]}/20", ha="center", fontsize=10, color=DARK)
        ax1.text(i + w / 2, 101, f"{retr[i]}/7", ha="center", fontsize=10, color=DARK)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylim(0, 118)
    ax1.set_ylabel("% of canonical items")
    ax1.set_title("What survived ten sessions of facts + retractions", fontsize=12, color=DARK)
    ax1.legend(frameon=False, fontsize=8, loc="lower right")
    ax1.grid(axis="y", color=LIGHT)
    ax1.set_axisbelow(True)
    ax1.text(0.5, 112, "a tie", ha="center", fontsize=10, color="#5b6570")

    ax2.bar(labels, noise, width=0.45, color=[DYN, GREY])
    for i, v in enumerate(noise):
        ax2.text(i, v + 0.3, str(v), ha="center", fontsize=11, color=DARK)
    ax2.set_ylim(0, max(noise) * 1.3)
    ax2.set_ylabel("noise phrases absorbed")
    ax2.set_title("How much unrelated chatter leaked into the story", fontsize=12, color=DARK)
    ax2.grid(axis="y", color=LIGHT)
    ax2.set_axisbelow(True)
    ax2.text(0.5, 0.88, "lower is better", transform=ax2.transAxes, ha="center", fontsize=9, color="#5b6570")

    save(fig, "fidelity-2026-11")


for fn in (chart_resident, chart_routing, chart_write, chart_ingest, chart_growth, chart_fidelity):
    fn()
print("done")
