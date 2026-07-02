import sys
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from plot_style import setup_matplotlib, style_ax, save_fig, PALETTE

setup_matplotlib()

# --- Load data ---
xl = pd.ExcelFile("output/run_catalogue.xlsx")
dfs = []
for sheet in ["2026-01-06 and after", "2026-01-05 and before"]:
    df = xl.parse(sheet)
    dfs.append(df[["H2_frac", "Spark timing", "CA50_Fired2_mean [deg]"]].copy())

data = pd.concat(dfs, ignore_index=True)
data = data.dropna(subset=["Spark timing", "CA50_Fired2_mean [deg]"])

# --- Color mapping by H2_frac ---
color_map = {
    0.0: PALETTE[0],   # blue
    0.3: PALETTE[1],   # red
    0.5: PALETTE[2],   # green
}
default_color = PALETTE[3]  # purple for 0.7 / other

label_map = {
    0.0: r"$H_2$ = 0",
    0.3: r"$H_2$ = 0.3",
    0.5: r"$H_2$ = 0.5",
    "other": r"$H_2$ = 0.7+",
}

# --- Plot ---
fig, ax = plt.subplots(figsize=(7.5, 4.5))
fig.patch.set_facecolor("#f9f9f9")
style_ax(ax)

plotted_labels = {}
for _, row in data.iterrows():
    h2 = row["H2_frac"]
    x = row["Spark timing"]
    y = row["CA50_Fired2_mean [deg]"]

    if h2 in color_map:
        color = color_map[h2]
        label = label_map[h2]
    else:
        color = default_color
        label = label_map["other"]

    if label not in plotted_labels:
        ax.scatter(x, y, color=color, s=30, alpha=0.8, label=label, zorder=3)
        plotted_labels[label] = True
    else:
        ax.scatter(x, y, color=color, s=30, alpha=0.8, zorder=3)

# --- Axis limits (range > 40 → snap to multiples of 10) ---
x_min_snap = int(np.floor(data["Spark timing"].min() / 10) * 10)
x_max_snap = int(np.ceil(data["Spark timing"].max() / 10) * 10)
y_min_snap = int(np.floor(data["CA50_Fired2_mean [deg]"].min() / 10) * 10)
y_max_snap = int(np.ceil(data["CA50_Fired2_mean [deg]"].max() / 10) * 10)

ax.set_xlim(x_min_snap, x_max_snap)
ax.set_ylim(y_min_snap, y_max_snap)

# --- Labels and title ---
ax.set_xlabel("Spark Timing [deg]")
ax.set_ylabel(r"CA50 Fired2 Mean [deg]")
ax.set_title("CA50 Fired2 Mean vs Spark Timing", fontsize=10, fontweight="bold", pad=8)

# --- Legend ---
ax.legend(loc="best", framealpha=0.9, edgecolor="#cccccc")

# --- Save ---
save_fig(fig, "output/plots/test_scatter2.png")
