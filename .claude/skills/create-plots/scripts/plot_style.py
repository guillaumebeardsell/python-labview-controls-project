"""
Shared plotting style for this project.

Copy this file to the project root, then import at the top of every plot script:

    from plot_style import setup_matplotlib, style_ax, save_fig, nice_limits, PALETTE

Call setup_matplotlib() once at module level before creating any figures.
"""

import math
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Colorblind-friendly palette (blue, red, green, purple)
PALETTE = ["#2166ac", "#d6604d", "#4dac26", "#8073ac"]


def setup_matplotlib():
    """Configure matplotlib defaults: font (Helvetica), base size 9 pt.

    Call once at module level. If Helvetica is not installed, falls back to
    DejaVu Sans and prints a warning.
    """
    sys.stdout.reconfigure(encoding="utf-8")

    helvetica_available = any(
        "Helvetica" in f.name for f in fm.fontManager.ttflist
    )
    if helvetica_available:
        plt.rcParams["font.family"] = "Helvetica"
    else:
        print("WARNING: Helvetica not found; using DejaVu Sans.")
        plt.rcParams["font.family"] = "DejaVu Sans"

    plt.rcParams["font.size"] = 9


def style_ax(ax):
    """Apply the standard axis style to an Axes object.

    Sets grey background, major/minor grid, grey spines and ticks.
    Call on every axis after creating the figure.
    """
    ax.set_facecolor("white")
    ax.grid(which="major", color="#cccccc", linewidth=0.8, linestyle="-")
    ax.grid(which="minor", color="#e0e0e0", linewidth=0.4, linestyle=":")
    ax.minorticks_on()
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_edgecolor("#cccccc")
    ax.tick_params(labelsize=9, color="#888888")


def nice_limits(data_min, data_max):
    """Return axis limits that align with major tick positions.

    Selects a tick step using the 1/2/5/10 progression (same logic as
    matplotlib's auto-locator) so that limits land on multiples of that step.
    Data range ≤ 5 is returned unchanged (tight to the data).

    Examples:
      nice_limits(-2, 130)   → (-20, 140)  [step=20]
      nice_limits(3.1, 18.7) → (2, 20)     [step=2]
      nice_limits(0, 45)     → (0, 50)     [step=10]
    """
    span = data_max - data_min
    if span <= 5:
        return data_min, data_max
    # Pick a step that gives roughly 5–8 ticks using 1/2/5/10 progression
    rough = span / 6
    magnitude = 10 ** math.floor(math.log10(rough))
    step = magnitude
    for mult in [1, 2, 5, 10]:
        step = mult * magnitude
        if span / step <= 8:
            break
    return math.floor(data_min / step) * step, math.ceil(data_max / step) * step


def save_fig(fig, path, dpi=300):
    """Apply tight_layout, save the figure as PNG and SVG, close it, and print the paths.

    The PNG is saved at 300 dpi. The SVG is fully vectorized (text, lines,
    patches are all vector objects), making it easy to edit in Inkscape or
    Illustrator. The .svg file is written alongside the .png with the same
    base name.

    Creates the output directory if it does not exist.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.tight_layout()

    # Ensure path ends with .png
    base = path[:-4] if path.lower().endswith(".png") else path
    png_path = base + ".png"
    svg_path = base + ".svg"

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    print(f"Saved {png_path}")

    # SVG: vector output — no dpi needed; format="svg" keeps everything as
    # vector paths (text rendered as glyphs, not rasterised bitmaps).
    fig.savefig(svg_path, format="svg", bbox_inches="tight")
    print(f"Saved {svg_path}")

    plt.close(fig)
