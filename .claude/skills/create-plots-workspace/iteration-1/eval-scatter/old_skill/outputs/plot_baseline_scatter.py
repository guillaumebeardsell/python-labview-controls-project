"""Scatter plot: CA50_Fired2_mean vs Spark timing, colored by H2_frac."""

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Load data ────────────────────────────────────────────────────────────────
CATALOGUE = "output/run_catalogue.xlsx"
SHEETS = ["2026-01-06 and after", "2026-01-05 and before", "2026-02-09 Pegging Runs"]

frames = []
for sheet in SHEETS:
    try:
        df = pd.read_excel(CATALOGUE, sheet_name=sheet, header=0)
        frames.append(df)
    except Exception:
        pass

data = pd.concat(frames, ignore_index=True)

# Keep rows that have both values
data = data.dropna(subset=["CA50_Fired2_mean [deg]", "Spark timing"])

# ── Color mapping ─────────────────────────────────────────────────────────────
COLOR_MAP = {
    0.0: "blue",
    0.3: "red",
    0.5: "green",
}
DEFAULT_COLOR = "purple"

def h2_color(val):
    try:
        v = float(val)
        return COLOR_MAP.get(round(v, 2), DEFAULT_COLOR)
    except (TypeError, ValueError):
        return DEFAULT_COLOR

colors = data["H2_frac"].map(h2_color)

# ── Figure setup ─────────────────────────────────────────────────────────────
# Letter page width ~6.5 inches usable; single-column figure
FIG_W = 5.0   # inches
FIG_H = 3.8   # inches
FONT = "Open Sans"
FONTSIZE = 10

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [FONT, "DejaVu Sans"],
    "font.size": FONTSIZE,
    "axes.labelsize": FONTSIZE,
    "xtick.labelsize": FONTSIZE,
    "ytick.labelsize": FONTSIZE,
    "legend.fontsize": FONTSIZE,
})

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))

ax.scatter(
    data["Spark timing"],
    data["CA50_Fired2_mean [deg]"],
    c=colors,
    s=18,
    alpha=0.75,
    linewidths=0,
)

# ── Axis labels & limits ──────────────────────────────────────────────────────
ax.set_xlabel("Spark timing [deg]")
ax.set_ylabel("CA50 Fired2 mean [deg]")

# Trim limits to integers (range > 5 for both axes)
x = data["Spark timing"]
y = data["CA50_Fired2_mean [deg]"]

ax.set_xlim(int(np.floor(x.min())), int(np.ceil(x.max())))
ax.set_ylim(int(np.floor(y.min())), int(np.ceil(y.max())))

# ── Legend ────────────────────────────────────────────────────────────────────
legend_entries = [
    mpatches.Patch(color="blue",   label="H₂ frac = 0"),
    mpatches.Patch(color="red",    label="H₂ frac = 0.3"),
    mpatches.Patch(color="green",  label="H₂ frac = 0.5"),
    mpatches.Patch(color="purple", label="H₂ frac = 0.7 / other"),
]
ax.legend(handles=legend_entries, loc="upper left", framealpha=0.85)

ax.set_title("CA50 Fired2 vs Spark Timing by H₂ Fraction", fontsize=FONTSIZE)

# ── Save ──────────────────────────────────────────────────────────────────────
out_dir = "output/plots"
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "baseline_scatter.png")
fig.tight_layout()
fig.savefig(out_path, dpi=150)
print(f"Saved: {out_path}")
