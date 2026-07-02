import sys
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from plot_style import setup_matplotlib, style_ax, save_fig, PALETTE

import numpy as np

setup_matplotlib()

# --- Synthetic data ---
rng = np.random.default_rng(42)
ca = np.linspace(-180, 180, 721)

n_cycles = 50
# Gaussian bump centered at 10 CAD, amplitude ~40 bar, baseline 5 bar
sigma = 20.0
bump = 40.0 * np.exp(-0.5 * ((ca - 10.0) / sigma) ** 2)
baseline = 5.0
noise_std = 2.0

cycles = baseline + bump[np.newaxis, :] + rng.normal(0, noise_std, size=(n_cycles, len(ca)))
mean_cycle = cycles.mean(axis=0)

# --- Figure ---
fig, ax = plt.subplots(figsize=(7.5, 4.5))
fig.patch.set_facecolor("#f9f9f9")

color = PALETTE[0]  # #2166ac

# Individual cycles
for i in range(n_cycles):
    ax.plot(ca, cycles[i], color=color, alpha=0.03, linewidth=0.7)

# Mean cycle
ax.plot(ca, mean_cycle, color=color, linewidth=1.8, label="Mean")

# Spark timing marker
spark_ca = -20.0
ax.axvline(spark_ca, color="grey", linestyle="--", linewidth=1.0, label="spark")

style_ax(ax)

ax.set_xlabel("Crank Angle [CAD]")
ax.set_ylabel("Cylinder Pressure [bar]")
ax.set_title("Synthetic Pressure Traces", fontsize=10, fontweight="bold", pad=8)

# Trim axis limits to data
ax.set_xlim(-180, 180)
ax.set_ylim(0, max(mean_cycle.max(), cycles.max()) * 1.05)
ax.set_ylim(0, int(cycles.max()) + 1)

ax.legend(loc="upper right", framealpha=0.9, edgecolor="#cccccc")

save_fig(fig, "output/plots/test_timeseries.png")
