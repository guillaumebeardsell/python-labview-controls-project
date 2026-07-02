import sys
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from plot_style import setup_matplotlib, style_ax, save_fig, PALETTE

setup_matplotlib()

# --- Synthetic data ---
np.random.seed(42)
ca = np.linspace(-180, 180, 721)
n_cycles = 50

# Gaussian bump centered at 10 CAD, amplitude ~40 bar, baseline 5 bar
bump = 40 * np.exp(-((ca - 10) ** 2) / (2 * 15**2))
baseline = 5.0
cycles = np.array([
    baseline + bump + np.random.normal(0, 1.5, size=len(ca))
    for _ in range(n_cycles)
])
mean_cycle = cycles.mean(axis=0)

# --- Plot ---
fig, ax = plt.subplots(figsize=(7.5, 4.5))
fig.patch.set_facecolor("#f9f9f9")

blue = PALETTE[0]  # "#2166ac"

# Individual cycles
for cycle in cycles:
    ax.plot(ca, cycle, color=blue, alpha=0.03, linewidth=0.7)

# Mean cycle
ax.plot(ca, mean_cycle, color=blue, linewidth=1.8, label="Mean")

# Spark vertical line
ax.axvline(x=-20, color="grey", linestyle="--", linewidth=1.0, label="spark")

# Labels and title
ax.set_xlabel("Crank Angle [CAD]")
ax.set_ylabel("Cylinder Pressure [bar]")
ax.set_title("Synthetic Pressure Traces", fontsize=10, fontweight="bold", pad=8)

# Axis limits — apply tiered rule
x_min, x_max = ca.min(), ca.max()
x_range = x_max - x_min  # 360, > 40 → snap to nearest multiple of 10
ax.set_xlim(
    np.floor(x_min / 10) * 10,
    np.ceil(x_max / 10) * 10,
)

y_min_data = cycles.min()
y_max_data = cycles.max()
y_range = y_max_data - y_min_data  # ~50 bar, > 40 → snap to nearest multiple of 10
ax.set_ylim(
    max(0, np.floor(y_min_data / 10) * 10),  # don't go below 0
    np.ceil(y_max_data / 10) * 10,
)

style_ax(ax)

ax.legend(loc="upper left", framealpha=0.9, edgecolor="#cccccc")

save_fig(fig, "output/plots/test_timeseries2.png")
