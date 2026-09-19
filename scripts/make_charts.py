#!/usr/bin/env python3
"""Generate the README charts as SVG.

Three charts:
  1. complex-memory capacity  — how many complex memories fit in the 2,200-char budget
  2. detail-recall            — the complexity benchmark result (11/30 vs 30/30)
  3. resident-token-cost      — memory-block tokens vs number of memories held

SVG so GitHub renders them inline with no dependencies. A light/dark-safe palette:
explicit fills on every element, no reliance on theme defaults.
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = "/home/ubuntu/hermes-dynamic-memory/docs/charts"
os.makedirs(OUT, exist_ok=True)

# Palette — mid-contrast, readable on both GitHub light and dark themes.
NATIVE = "#c2703d"      # warm orange
DYNAMIC = "#2f7d8e"     # teal
GRID = "#8a8a8a"
TEXT = "#3d3d3d"
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "text.color": TEXT,
    "axes.labelcolor": TEXT,
    "xtick.color": TEXT,
    "ytick.color": TEXT,
    "axes.edgecolor": GRID,
})

data = json.load(open("docs/charts/chart_data.json"))


def finish(fig, path):
    fig.savefig(path, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    print("wrote", path)


# ---------------------------------------------------------------- chart 1
# Complex-memory capacity in one 2,200-char budget
fig, ax = plt.subplots(figsize=(7.5, 3.4))
labels = ["Native memory\n(block = the memory)", "Dynamic memory\n(12 keywords/entry, detail on disk)"]
vals = [data["capacity_native"], data["capacity_12kw"]]
colors = [NATIVE, DYNAMIC]
bars = ax.barh(labels, vals, color=colors, height=0.55)
for b, v in zip(bars, vals):
    ax.text(v + 0.35, b.get_y() + b.get_height() / 2, f"{v:.1f}",
            va="center", ha="left", fontsize=15, fontweight="bold",
            color=b.get_facecolor())
ax.set_xlim(0, max(vals) * 1.22)
ax.set_xlabel("complex memories holdable within the 2,200-character limit")
ax.set_title("Complex-memory capacity at equal resident budget",
             fontsize=13, fontweight="bold", pad=14)
ax.text(0.99, -0.42, "6.2x more", transform=ax.transAxes, ha="right",
        fontsize=12, fontweight="bold", color=DYNAMIC)
ax.grid(axis="x", color=GRID, alpha=0.22, linewidth=0.8)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
finish(fig, f"{OUT}/capacity.svg")

# ---------------------------------------------------------------- chart 2
# Detail recall on complex memories
fig, ax = plt.subplots(figsize=(7.5, 3.4))
cats = ["Native\n(all 6 facts offered)", "Dynamic\n(all 6 facts offered)"]
recalled = [11, 30]
total = 30
colors = [NATIVE, DYNAMIC]
bars = ax.bar(cats, recalled, color=colors, width=0.45)
ax.axhline(total, color=GRID, linestyle="--", linewidth=1, alpha=0.7)
ax.text(1.42, total + 0.6, "30 probes", ha="right", va="bottom",
        fontsize=9, color=GRID)
for b, v in zip(bars, recalled):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.8, f"{v}/30",
            ha="center", va="bottom", fontsize=15, fontweight="bold",
            color=b.get_facecolor())
ax.set_ylim(0, 34)
ax.set_ylabel("detail probes answered correctly")
ax.set_title("Complex-memory detail recall", fontsize=13, fontweight="bold", pad=14)
ax.grid(axis="y", color=GRID, alpha=0.22, linewidth=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(0.5, -0.06,
         "Native recalled 11/11 details on the 2 facts it could store, and 0/19 on the 4 it could not.",
         ha="center", fontsize=9.5, color=TEXT)
finish(fig, f"{OUT}/detail-recall.svg")

# ---------------------------------------------------------------- chart 3
# Resident memory-block cost vs. memories held
curve = data["block_curve_12kw"]
n = [c[0] for c in curve]
nat = [c[1] for c in curve]
dyn = [c[2] for c in curve]

fig, ax = plt.subplots(figsize=(7.8, 4.2))
ax.plot(n, nat, color=NATIVE, linewidth=2.6, marker="o", markersize=5,
        label="Native memory block")
ax.plot(n, dyn, color=DYNAMIC, linewidth=2.6, marker="s", markersize=5,
        label="Dynamic memory block (12 keywords/entry)")
ax.axhline(2200, color=GRID, linestyle="--", linewidth=1, alpha=0.8)
ax.text(33.2, 2090, "2,200-character\nresident limit", fontsize=9, color=GRID,
        ha="right", va="top")

# Native annotation: point at the flat-capped segment (x=6, on the line).
ax.annotate("native hits the hard cap\nat ~3 complex facts",
            xy=(6.0, 2200), xytext=(6.6, 2680), fontsize=9.5, color=NATIVE,
            ha="center",
            arrowprops=dict(arrowstyle="->", color=NATIVE, linewidth=1.3,
                            connectionstyle="arc3,rad=-0.2"))
# Dynamic annotation: point at x=16 where it approaches the limit.
ax.annotate("dynamic still inside the budget\nat 16 facts",
            xy=(16, 2080), xytext=(19.5, 1150), fontsize=9.5, color=DYNAMIC,
            arrowprops=dict(arrowstyle="->", color=DYNAMIC, linewidth=1.3,
                            connectionstyle="arc3,rad=0.2"))

ax.set_xlabel("complex memories held")
ax.set_ylabel("resident memory-block characters")
ax.set_title("Resident cost of holding complex memories",
             fontsize=13, fontweight="bold", pad=14)
ax.set_ylim(0, 5200)
ax.set_xlim(0, 34)
ax.legend(frameon=False, loc="upper left", fontsize=10)
ax.grid(color=GRID, alpha=0.2, linewidth=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
finish(fig, f"{OUT}/resident-cost.svg")

print("\nall charts written to docs/charts/")
