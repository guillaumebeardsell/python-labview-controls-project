---
name: create-plots
description: >
  Creates consistently high-quality, publication-ready matplotlib plots for
  optical engine data analysis. Use this skill for ANY data visualization
  task — whenever the user asks to plot, chart, graph, or visualize data,
  or requests figures for a report, paper, or presentation. Also use when
  asked to improve, clean up, or make an existing plot look better, including
  fixing axis labels, adding subscripts, correcting units, adjusting figure
  size, or improving text formatting in an existing plot script. Trigger
  even for casual requests like "show me X vs Y" or "can you plot the trend".
metadata:
  author: Guillaume Beardsell
  version: 0.3.0
---

# Create High-Quality Plots

## Setup

This project has a shared `plot_style.py` in the **project root**. Before
writing a new plot script, confirm the file exists there. If it does not,
copy it from `.claude/skills/create-plots/scripts/plot_style.py`.

Every plot script must start with:

```python
import sys
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from plot_style import setup_matplotlib, style_ax, save_fig, PALETTE

setup_matplotlib()
```

`setup_matplotlib()` sets the font to **TeX Gyre Heros** (Helvetica clone) at 8 pt (falls back to
DejaVu Sans with a warning if not installed).

---

## Figure sizes

**Never make a figure wider than 6.5 in unless the user explicitly asks for a
landscape / wide figure.** 6.5 in is the usable width of a letter-size page with
1-inch margins, so a figure embeds at full size without being shrunk. Width is
the hard constraint — grow a figure by adding *height*, not width.

| Layout | `figsize` |
|---|---|
| Single panel | `(6.5, 4.0)` |
| Single panel, wide/short | `(6.5, 3.0)` |
| Two panels, vertical (`sharex`) | `(6.5, 8.0)` |
| Three panels, vertical (`sharex`) | `(6.5, 11.0)` |

Need more than one panel? **Stack vertically** (keep width 6.5, increase height),
or emit each panel as its own ≤6.5 in figure — do not place panels side by side
into a wide (e.g. 13 in) figure. A legend may sit just outside the axes on the
right (`bbox_to_anchor`); the 6.5 in cap is about the plotting area / `figwidth`,
not that spillover.

Only exceed 6.5 in when the user specifically requests a landscape or wide
figure (e.g. a poster panel or a standalone dense grid). In that case widen as
needed (e.g. `(10, 14)`) — but treat it as the exception, not the default.

Add `layout="constrained"` to any figure that uses `fig.suptitle()` or has
a twin axis, so the layout engine allocates space for all elements
automatically. Do **not** specify `y=` on `suptitle` — let constrained layout
place it.

---

## Axis styling

Call `style_ax(ax)` on **every** axis. It applies:
- White background
- Major grid: solid, `#cccccc`, 0.8 pt
- Minor grid: dotted, `#e0e0e0`, 0.4 pt
- Grey spines (`#cccccc`) and tick marks (`#888888`)
- 8 pt tick labels

Do **not** set `fig.patch.set_facecolor()` — leave the figure background at
matplotlib's default white.

---

## Color palette

Use `PALETTE` from `plot_style` for sequential series:

```python
PALETTE = ["#2166ac", "#d6604d", "#4dac26", "#8073ac"]
#           blue       red        green      purple
```

These are colorblind-friendly and consistent across all project plots. Use
them in order; don't pick arbitrary colors unless the data has a specific
semantic meaning that maps to a color (e.g., blue = 10% CO₂, red = 15% CO₂).

---

## Axis limits

- Minimize empty space: trim limits so data fills the plot area.
- **Axis limits must land on major tick positions.** The tick step determines
  the grid; limits must be exact multiples of that step. For example, data
  from −2 to 130 with a step of 20 → limits −20 to 140 (not −10 to 130,
  because −10 and 130 are not multiples of 20).
- Use `nice_limits(data_min, data_max)` from `plot_style` — it selects the
  step automatically using the 1/2/5/10 progression (matching matplotlib's
  own locator logic) and snaps limits accordingly:
  ```python
  lo, hi = nice_limits(data.min(), data.max())
  ax.set_xlim(lo, hi)
  ```
- For physical quantities, don't let axes extend below zero unless negative
  values are meaningful.
- If a shared y-axis is needed across subplots, compute the global min/max
  from all data first, then apply `nice_limits` uniformly.

---

## Labels and titles

- Axis labels must include units in square brackets: `"Pressure [bar]"`,
  `"Temperature [°C]"`, `"Crank Angle [CAD]"`.
- Font size 8 pt for all text — this is the `rcParams` default set by
  `setup_matplotlib()`, so you usually don't need to specify it explicitly.
- Titles: `fontsize=8, fontweight="bold", pad=8`. Do **not** pass a
  `fontfamily` argument to `set_title()` — let it inherit from `rcParams`
  so the title uses the same typeface as all other text elements.
- For multi-line titles (e.g., main title + subtitle), use `\n`.

### Chemical formulas and subscripts

Use matplotlib math text for **all** subscripts — chemical formulas and physical variable names alike:

```python
# Chemical formulas — numeric subscripts
"$H_2$ in Fuel [%]"        # → H₂ in Fuel [%]
"$CO_2$ [%]"               # → CO₂ [%]
"$O_2$ [%]"                # → O₂ [%]

# Physical variable names — word subscripts use \mathrm{} for upright text
r"$P_{\mathrm{intake}}$ [bar]"    # → P_intake with proper subscript
r"$P_{\mathrm{GEX}}$ [bar]"      # → P_GEX with proper subscript
r"$P_{\mathrm{int}}$ [bar]"      # → P_int with proper subscript
r"$\lambda_{\mathrm{MC}}$"       # → λ_MC with proper subscript

# Bad — plain text, subscripts missing
"P_intake [bar]"           # → P_intake (underscore visible, no subscript)
"P_GEX [bar]"              # → P_GEX
"lambda_MC"                # → lambda_MC
```

Use `r""` (raw string) to avoid double-escaping backslashes. For differences
and negatives, use `$-$` or `$P_{\mathrm{A}} - P_{\mathrm{B}}$` — never the
unicode minus `\u2212` alongside math mode.

**f-strings with LaTeX:** When embedding a LaTeX label inside an f-string
(e.g. to include a variable value in a title), escape LaTeX curly braces by
doubling them: `{{` → `{` at runtime, `}}` → `}` at runtime:

```python
# Correct — LaTeX braces doubled, f-expression in single braces
f"$P_{{\\mathrm{{int}}}}$ = {p_bar:.2f} bar"

# Wrong — {\\mathrm{int}} is parsed as an f-string expression → SyntaxError
f"$P_{\\mathrm{int}}$ = {p_bar:.2f} bar"
```

This applies to axis labels, legend entries, annotations, and titles — anywhere a formula or variable name appears.

---

## Legends

- Check that the legend doesn't cover data. Start with `loc="best"`.
- If it overlaps data, try corners explicitly: `"upper right"`, `"upper left"`,
  `"lower right"`, `"lower left"`.
- If all corners overlap data, extend axis limits to create empty space rather
  than placing the legend on top of data.
- Standard options: `framealpha=0.9`, `edgecolor="#cccccc"`.

---

## Saving

Use `save_fig(fig, path)` from `plot_style`. It calls `tight_layout()`,
saves the figure in **two formats** (PNG at 300 dpi and fully-vectorized SVG),
closes the figure, and prints both paths. No need to call `plt.close()` or
`tight_layout()` separately.

**`bbox_inches` is not used.** The figure is saved at exactly `figsize × dpi`
pixels. This guarantees that 8 pt text in a 6.5-inch figure renders as
exactly 8 pt when placed at 6.5 inches in a document. Do not add
`bbox_inches="tight"` — it trims whitespace and changes the effective size,
making font sizes unpredictable.

The SVG is fully vectorized — text, lines, and patches are all vector objects,
not rasterised bitmaps — so users can open it in Inkscape or Illustrator for
further editing.

**Always pass a `.png` path** to `save_fig`; the `.svg` sibling is written
automatically with the same base name.

**Width suffix:** `save_fig` automatically appends `_width_X_Xin` to the
filename stem, derived from `fig.get_figwidth()`. For example, a figure
created with `figsize=(6.5, 4.0)` is saved as `…_width_6_5in.png` /
`…_width_6_5in.svg`. This makes the intended display size visible in the
filename without any extra argument at the call site.

**Output path convention:**
- Study figures: `output/studies/<topic>/<name>_width_6_5in.png`  (→ also `.svg`)
- Integrated scenario deliverables: `output/scenarios/<P>bar/<name>_width_6_5in.png`  (→ also `.svg`)

---

## Multi-cycle / ensemble data

When many cycles are plotted on the same axis (e.g., pressure traces):
- Individual cycles: `alpha=0.03`, `linewidth=0.7`
- Cycle mean: `linewidth=1.8`, full opacity, same color

---

## Reference lines

- Vertical markers (spark timing, TDC, etc.):
  `color="grey", linestyle="--", linewidth=1.0`
- Horizontal markers (MFB fractions, thresholds, etc.):
  `color="#888888"`, choose linestyle to distinguish levels
  (e.g., `":"` for 10%, `"-."` for 50%, `"--"` for 90%)
