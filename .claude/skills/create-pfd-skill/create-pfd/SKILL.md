---
name: create-pfd
description: >
  Builds consistent, publication-ready process flow diagrams (PFDs) from the
  NTS Visio stencil, as fully-vectorized SVG (plus PNG preview). Use this skill
  for ANY process-diagram task — whenever the user asks to draw, build, lay out,
  or update a PFD, flowsheet, block flow diagram, or equipment train, or to add
  equipment (exchangers, pumps, compressors, columns, vessels, membranes,
  valves) and wire streams between them. Also use when asked to improve, clean
  up, or re-route an existing PFD, fix component tags, recolor stream classes,
  or re-export a diagram to SVG/PDF. Trigger even for casual requests like
  "draw the GSU permeate train" or "lay out Embodiment 9".
metadata:
  author: Guillaume Beardsell
  version: 0.1.0
---

# Create Process Flow Diagrams

## Setup

This project has a shared `nts_pfd.py` and a symbol library under
`assets/symbols/`. Before writing a PFD script, confirm `nts_pfd.py` is
importable (it lives in `scripts/`). Every PFD script starts with:

```python
import sys
sys.path.insert(0, ".claude/skills/create-pfd/scripts")
from nts_pfd import PFD, STREAMS
```

`nts_pfd` loads the symbol library at import: each symbol is a **real Visio
stencil master**, extracted to a tight-viewBox SVG with named ports (nozzles).
Pipes attach at true connection points, not bounding-box midpoints.

The symbols are sourced from `NTS_COMPONENTS.vssx`. To regenerate or extend the
library, run `scripts/extract_symbols.py NTS_COMPONENTS.vssx` (requires
LibreOffice on PATH — it carries the Visio import filter). Edit `SYMBOL_SPEC`
in that file to add masters, set tag prefixes, and define ports.

---

## Output is vector

PFDs are saved as **fully-vectorized SVG** plus a PNG preview, via `pfd.save()`.
The SVG embeds each symbol as nested vector geometry — never a rasterized
bitmap — so the diagram scales losslessly and can be opened in Inkscape or
Illustrator, or dropped into a disclosure document at any size. Always pass a
`.png` path to `save()`; the `.svg` sibling is written automatically with the
same base name.

```python
pfd.save("output/figures/embodiment_9_pfd.png")   # → also .svg
```

---

## The symbol library

Place components with `pfd.add(key, x, y, h)`. Width is derived from the
symbol's native aspect ratio — **set height, never width** (same discipline as
the plot skill: the visual scale of equipment must stay consistent across a
sheet, so size by height and let aspect set the rest).

| key | component | tag | ports |
|---|---|---|---|
| `heat_exchanger` | HEAT EXCHANGER | E- | in, out, top, bottom |
| `shell_tube_hx` | SHELL AND TUBE HEAT EXCHANGER | E- | in, out |
| `plate_hx` | PLATE HEAT EXCHANGER | E- | in, out |
| `pump` | PUMP | P- | in, out |
| `compressor` | COMPRESSOR | C- | in, out |
| `vessel` | VESSEL | VE- | in, out, top, bottom |
| `rounded_vessel` | ROUNDED/ANGLED VESSEL | VE- | in, out, top, bottom |
| `membrane_permeate` | MEMBRANE 1 PERMEATE | M- | in, out, permeate |
| `general_valve` | GENERAL VALVE | V- | in, out |
| `globe_valve` | GLOBE VALVE | V- | in, out |
| `check_valve` | CHECK VALVE | V- | in, out |
| `column` | tray column (composite) | T- | feed, top, bottom, side |

The full stencil holds ~54 components; the table above is the core PFD set.
Add more by editing `SYMBOL_SPEC` and re-running the extractor.

**Tray column caveat.** The dedicated "Tray column" Visio master is a *group*
shape that the headless renderer cannot expand, so `column` is a composite: the
real DISTILLATION TOWER shell with parametric trays. It is visually a tray
column and the tray count is a parameter. To use the exact master geometry,
export that one master to SVG from Visio (drop it on a page, File > Export >
SVG) and replace `assets/symbols/column.svg`.

---

## Tag numbering

Tags come from the stencil's own convention — the prefix is baked into each
master (E- exchangers, P- pumps, C- compressors, T- towers, VE- vessels,
M- membranes, V- valves). `add()` **auto-numbers** within each prefix starting
at 101: the first compressor is `C-101`, the next `C-102`, the first exchanger
`E-101`, and so on. Pass `tag=` to override (e.g. `tag="E-104"` to match an
existing drawing). The tag is drawn centered under the component.

---

## Stream / line classes

Connect ports with `pfd.connect(a, b, stream=...)`. Colors match the figure
legend — use the class that matches the physical service, never an arbitrary
color:

```python
STREAMS = {
    "process":      "#1a1a1a",   # process (Ar/CO2)
    "oxygen":       "#1f6fb2",   # blue
    "condenser":    "#2e7d32",   # condenser coolant loop (green)
    "feed_precool": "#7b3fb0",   # feed-precool coolant loop (purple)
    "water":        "#c0392b",   # water utility (red)
}
```

Default stream is `process`. Always add a `pfd.legend(x, y, [...])` listing the
stream classes actually used on the sheet.

---

## Ports and routing

- Connect by **named port**, not coordinates: `pfd.connect(c.port("out"),
  e.port("in"))`. Ports resolve to the real nozzle position, so a pipe meets
  the nozzle tip cleanly.
- Routing is **orthogonal** (Manhattan): the router reads each port's exit
  direction from its position (`in`/`out` exit horizontally, `top`/`bottom`
  vertically) and lays a right-angle path with a short nozzle stub at each end.
  This matches PFD drafting practice — no diagonal pipes.
- Override the exit/entry direction with `start_dir=` / `end_dir=` ("L","R",
  "U","D") only when the automatic choice routes awkwardly.

---

## Off-sheet labels (pennants)

Inlet/outlet streams use pennants (the OFF SHEET LABEL convention):

```python
gsu = pfd.pennant(20, y, "GSU PERMEATE", direction="out")   # flag points right (into sheet)
pfd.connect(gsu, c.port("in"))
co2 = pfd.pennant(x, y, "LIQUID CO2", direction="out")      # product
```

`direction="out"` points right (a feed entering from the left edge or a product
label); `direction="in"` points left.

---

## Figure sizes

A PFD canvas is `PFD(width, height)`. Keep the **process train horizontal,
left to right**, utilities entering from above, products leaving below — the
house layout. Size the canvas to the content with a comfortable margin; grow a
busy sheet by adding height (stack utility loops vertically) rather than
sprawling horizontally. Give a title and one-line subtitle:

```python
pfd = PFD(1020, 640, title="Embodiment 9 — O2 Warm-End Turboexpander",
          subtitle="Noble Thermodynamic Systems — invention disclosure figure (not to scale)")
```

---

## Quality control

`pfd.save()` runs `validate(fix=True)` first — a geometric QC pass over the
retained model — and prints a short report. It **fixes deterministically**:

- **Truncated / overflowing labels** — every pennant is sized to its text width
  (measured with real font metrics), so a label is never clipped by its flag.
- **Pipe crossing text** — a pipe to a pennant attaches on the side facing the
  equipment, with the chevron pointing off-sheet; any label a pipe still crosses
  is nudged clear of the line.
- **Clipping at the canvas edge** — the canvas is grown so every symbol, label,
  pennant, route, and the legend sits inside it with a margin. (You can start
  with an approximate canvas size and let QC size it.)
- **Overlapping tag labels** — nudged apart vertically. Tall equipment
  (columns, vessels) gets its tag placed beside the base, clear of the centred
  top/bottom nozzles.

It **reports, rather than hides**, anything it cannot safely auto-fix —
overlapping symbols, or a pipe still crossing a label — as
`QC WARNING (unresolved): …`. Treat any warning as a defect to fix in the
script (re-space components, reroute), not something to ignore. A clean sheet
prints `QC: no unresolved overlaps / truncation / clipping`.

Run it explicitly while drafting with `pfd.validate()`; it returns the list of
unresolved issues.

---

## Conventions checklist

- Size components by **height**; never set width directly.
- Connect by **named port**; never hand-place pipe coordinates.
- Use the **stream class** matching the service; include a legend.
- Let tags **auto-number** from 101; override only to match an existing sheet.
- Save once with `pfd.save("…​.png")` — runs QC, then writes vector SVG + PNG.
