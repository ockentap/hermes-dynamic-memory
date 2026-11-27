#!/usr/bin/env python3
"""README chart for the XERJ routing comparison (2026-11-27).

Data: docs/xerj-vs-dynmem-2026-11.json (aggregate only; no personal memory text).
Output: docs/charts/xerj-routing-2026-11.svg and .png (1600x900).

The PNG is rendered from the SVG with headless Chromium when available; otherwise
open the SVG at 1600x900 and screenshot it.
"""
import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "charts")
DATA = json.load(open(os.path.join(ROOT, "docs", "xerj-vs-dynmem-2026-11.json")))

TEAL = "#3ec8d9"
TEAL_DIM = "#2f7d8e"
ORANGE = "#f08a4b"
ORANGE_DIM = "#c2703d"
WHITE = "#f2f7fb"
GREY = "#8fa3ba"
DARK = "#060a13"
PANEL = "#0d1524"

d = DATA["summary"]
dyn = d["dynmem_llm_route"]
lex = d["xerj_lexical_cli"]
sem = d["xerj_semantic"]
hyb = d["xerj_hybrid_rrf"]

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <radialGradient id="glowTeal" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{TEAL}" stop-opacity="0.30"/>
      <stop offset="100%" stop-color="{TEAL}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="glowOrange" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{ORANGE}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{ORANGE}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="headline" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{WHITE}"/>
      <stop offset="100%" stop-color="#9fc4cf"/>
    </linearGradient>
    <linearGradient id="gold" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffe08a"/>
      <stop offset="100%" stop-color="#b7791f"/>
    </linearGradient>
    <linearGradient id="panelL" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#10222b"/>
      <stop offset="100%" stop-color="{PANEL}"/>
    </linearGradient>
    <linearGradient id="panelR" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#241a14"/>
      <stop offset="100%" stop-color="{PANEL}"/>
    </linearGradient>
    <filter id="softGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="14" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <rect width="1600" height="900" fill="{DARK}"/>
  <ellipse cx="430" cy="500" rx="520" ry="420" fill="url(#glowTeal)"/>
  <ellipse cx="1190" cy="500" rx="480" ry="380" fill="url(#glowOrange)"/>

  <g stroke="#122033" stroke-width="2" opacity="0.55">
    <line x1="-100" y1="760" x2="900" y2="-40"/>
    <line x1="-20" y1="820" x2="980" y2="20"/>
    <line x1="620" y1="940" x2="1700" y2="140"/>
    <line x1="720" y1="980" x2="1800" y2="180"/>
  </g>

  <g opacity="0.9">
    <rect x="90" y="62" width="14" height="14" fill="{TEAL}"/>
    <text x="118" y="76" font-family="DejaVu Sans Mono, monospace" font-size="19"
          letter-spacing="5" fill="{GREY}">BENCHMARK // MEMORY ROUTING</text>
    <text x="1510" y="76" text-anchor="end" font-family="DejaVu Sans Mono, monospace"
          font-size="19" letter-spacing="5" fill="{GREY}">NOV 2026</text>
  </g>

  <text x="88" y="178" font-family="DejaVu Sans, Arial, sans-serif" font-size="78"
        font-weight="bold" letter-spacing="-1" fill="url(#headline)"><tspan fill="{TEAL}">DYNMEM</tspan> WINS.</text>
  <text x="92" y="222" font-family="DejaVu Sans, Arial, sans-serif" font-size="24"
        fill="{GREY}">40 prompts · 252 files · 488 chunks · top-1 topic-file routing</text>

  <line x1="90" y1="252" x2="1510" y2="252" stroke="#1b2a3e" stroke-width="2"/>

  <!-- dynmem panel -->
  <rect x="90" y="292" width="650" height="400" rx="18" fill="url(#panelL)" stroke="{TEAL_DIM}" stroke-width="2"/>
  <text x="128" y="350" font-family="DejaVu Sans, Arial, sans-serif" font-size="34"
        font-weight="bold" letter-spacing="9" fill="{TEAL}">DYNMEM</text>
  <text x="130" y="382" font-family="DejaVu Sans, Arial, sans-serif" font-size="17"
        letter-spacing="3" fill="{GREY}">KEYWORD INDEX</text>

  <g filter="url(#softGlow)">
    <text x="140" y="556" font-family="DejaVu Sans, Arial, sans-serif" font-size="170"
          font-weight="bold" fill="#eafcff" stroke="{TEAL}" stroke-width="2">40/40</text>
  </g>
  <text x="140" y="628" font-family="DejaVu Sans, Arial, sans-serif" font-size="27"
        font-weight="bold" letter-spacing="2" fill="{TEAL}">100% FIRST-HIT</text>
  <text x="140" y="662" font-family="DejaVu Sans, Arial, sans-serif" font-size="19"
        fill="#c3dfe6">20/20 keyword · 20/20 paraphrase</text>

  <!-- crown -->
  <g transform="translate(596 300)">
    <path d="M8 34 L8 12 L26 24 L40 4 L54 24 L72 12 L72 34 Z" fill="url(#gold)"/>
    <rect x="8" y="38" width="64" height="8" rx="2" fill="url(#gold)"/>
  </g>

  <!-- XERJ panel -->
  <rect x="860" y="292" width="650" height="400" rx="18" fill="url(#panelR)" stroke="{ORANGE_DIM}" stroke-width="2"/>
  <text x="898" y="350" font-family="DejaVu Sans, Arial, sans-serif" font-size="34"
        font-weight="bold" letter-spacing="9" fill="{ORANGE}">XERJ</text>
  <text x="900" y="382" font-family="DejaVu Sans, Arial, sans-serif" font-size="17"
        letter-spacing="3" fill="{GREY}">v1.0.0-rc.105 · LEXICAL</text>

  <text x="910" y="556" font-family="DejaVu Sans, Arial, sans-serif" font-size="170"
        font-weight="bold" fill="#fff3ea">37/40</text>
  <text x="910" y="628" font-family="DejaVu Sans, Arial, sans-serif" font-size="27"
        font-weight="bold" letter-spacing="2" fill="{ORANGE}">92.5% FIRST-HIT</text>
  <text x="910" y="662" font-family="DejaVu Sans, Arial, sans-serif" font-size="19"
        fill="#ecd8cc">19/20 keyword · 18/20 paraphrase</text>
  <text x="910" y="676" font-family="DejaVu Sans, Arial, sans-serif" font-size="16"
        fill="{GREY}">semantic {sem["top1"]}/{sem["n"]} · hybrid {hyb["top1"]}/{hyb["n"]}</text>

  <!-- VS bolt -->
  <text x="802" y="438" text-anchor="middle" font-family="DejaVu Sans, Arial, sans-serif"
        font-size="26" font-weight="bold" letter-spacing="4" fill="{GREY}">VS</text>
  <g transform="translate(790 500)">
    <path d="M14 -42 L-8 8 L6 8 L-6 50 L24 -2 L10 -2 Z" fill="url(#gold)" opacity="0.95"/>
  </g>

  <!-- stat strip -->
  <g font-family="DejaVu Sans, Arial, sans-serif">
    <rect x="90" y="726" width="456" height="86" rx="10" fill="#0c1422" stroke="#1d2f45"/>
    <text x="112" y="760" font-size="15" letter-spacing="3" fill="{GREY}">QUERY TIME</text>
    <text x="112" y="793" font-size="27" font-weight="bold" fill="{WHITE}">3.9 ms</text>
    <text x="238" y="793" font-size="17" fill="{GREY}">server-side, lexical</text>

    <rect x="572" y="726" width="456" height="86" rx="10" fill="#0c1422" stroke="#1d2f45"/>
    <text x="594" y="760" font-size="15" letter-spacing="3" fill="{GREY}">FOOTPRINT</text>
    <text x="594" y="793" font-size="27" font-weight="bold" fill="{WHITE}">2.1 MB</text>
    <text x="700" y="793" font-size="17" fill="{GREY}">index · 147 MB binary</text>

    <rect x="1054" y="726" width="456" height="86" rx="10" fill="#0c1422" stroke="#1d2f45"/>
    <text x="1076" y="760" font-size="15" letter-spacing="3" fill="{GREY}">NEURAL MODE</text>
    <text x="1076" y="793" font-size="27" font-weight="bold" fill="{ORANGE}">30/40</text>
    <text x="1176" y="793" font-size="17" fill="{GREY}">177 s ingest — vectors lose</text>
  </g>

  <text x="90" y="862" font-family="DejaVu Sans, Arial, sans-serif" font-size="15"
        fill="#5f7188">Hub-level retrieval, 40 hand-authored prompts, one run, 2026-11-27. Semantic = all-MiniLM-L6-v2; hybrid = RRF.
  </text>
</svg>
'''

os.makedirs(OUT, exist_ok=True)
svg_path = os.path.join(OUT, "xerj-routing-2026-11.svg")
open(svg_path, "w", encoding="utf-8").write(svg)
print("wrote", svg_path)

png_path = os.path.join(OUT, "xerj-routing-2026-11.png")
chrome = None
for base in (os.path.expanduser("~/.cache/ms-playwright"),):
    for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        cand = os.path.join(base, d, "chrome-linux64", "chrome")
        if os.path.exists(cand):
            chrome = cand
if chrome:
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=1600,900",
                    f"--screenshot={png_path}", "file://" + svg_path],
                   check=True, capture_output=True, timeout=120)
    print("wrote", png_path)
else:
    print("chromium not found; SVG only")
