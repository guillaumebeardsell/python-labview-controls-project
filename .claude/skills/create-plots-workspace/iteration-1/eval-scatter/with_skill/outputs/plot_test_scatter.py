import sys
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from plot_style import setup_matplotlib, style_ax, save_fig, PALETTE

import pandas as pd
import numpy as np

setup_matplotlib()

# Color mapping for H2_frac
H2_COLOR_MAP = {
    0.0: PALETTE[0],    # blue
    0.3: PALETTE[1],    # red
    0.5: PALETTE[2],    # green
}
COLOR_OTHER = PALETTE[3]  # purple for 0.7 or other

CATALOGUE_PATH = "output/run_catalogue.xlsx"
STATUS_SHEETS = ["2026-01-06 and after", "2026-01-05 and before"]

frames = []
for sheet in STATUS_SHEETS:
    df = pd.read_excel(CATALOGUE_PATH, sheet_name=sheet)
    frames.append(df)

data = pd.concat(frames, ignore_index=True)

# Keep only rows that have both columns
mask = data["Spark timing"].notna() & data["CA50_Fired2_mean [deg]"].notna()
data = data[mask].copy()

print(f"Rows with both values: {len(data)}")

def h2_color(val):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return COLOR_OTHER
    for key, color in H2_COLOR_MAP.items():
        if abs(v - key) < 1e-6:
            return color
    return COLOR_OTHER

colors = data["H2_frac"].apply(h2_color)

# Build legend entries
legend_entries = {}
unique_h2 = sorted(data["H2_frac"].dropna().unique())
for val in unique_h2:
    color = h2_color(val)
    label = f"H2 = {val:.1f}"
    if label not in legend_entries:
        legend_entries[label] = color

fig, ax = plt.subplots(figsize=(7.5, 4.5))
fig.patch.set_facecolor("#f9f9f9")

# Plot each group separately for legend
for label, color in legend_entries.items():
    val = float(label.split("=")[1].strip())
    mask_group = data["H2_frac"].apply(lambda x: abs(float(x) - val) < 1e-6 if pd.notna(x) else False)
    ax.scatter(
        data.loc[mask_group, "Spark timing"],
        data.loc[mask_group, "CA50_Fired2_mean [deg]"],
        color=color,
        s=30,
        alpha=0.8,
        edgecolors="none",
        label=label,
        zorder=3,
    )

style_ax(ax)

ax.set_xlabel("Spark timing [CAD]")
ax.set_ylabel("CA50_Fired2_mean [deg]")
ax.set_title("CA50 (Fired 2) vs Spark Timing\ncoloured by H₂ fraction", fontsize=10, fontweight="bold", pad=8)

ax.legend(title="H₂ fraction", loc="best", framealpha=0.9, edgecolor="#cccccc")

save_fig(fig, "output/plots/test_scatter.png")
