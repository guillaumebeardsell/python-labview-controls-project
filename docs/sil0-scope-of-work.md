# SIL-0 — Scope of Work (click-level)

**What SIL-0 is:** validate the 9049 combustion analytics (`APC_HRL` → IMEP / Pmax /
CA50 / MAPO / IMEPstd) and derive the warning-limit thresholds **on the dev PC, with no
hardware**, by feeding synthetic crank-angle pressure traces of known truth.

**Scope boundary (read first):** the desktop harness runs **`support/APC_HRL.vi` only** —
it computes the metrics. It does **not** run the `Pcyl_Diag → CombCluster2Array →
9049_Global_CylPressError` chain (that global is a *target-relative single-process*
variable that only exists on the 9049). So the **latch / false-trip matrix is SIL-1**, on
the real 9049 — not part of SIL-0. SIL-0 delivers *numbers and thresholds*; SIL-1 proves
*trip-and-latch behaviour*.

**Status (2026-07-11):** the **math is validated** — 425 comparisons, all within tolerance
(worst |Δ|: IMEPg 0.001 bar, Pmax 0.002 bar, CA50 0.112 CADATDC). Steps 0–2 below are the
*repro* of that; the **remaining SIL-0 work is Steps 3–4** (motoring thresholds, optional
MAPO/IMEPstd columns, fired profile). Step 5 is listed for completeness but belongs to SIL-1.

Derived from `docs/9049-openloop-audit.md` §7. Geometry flags throughout are the picture15
as-built: `--bore 0.112 --stroke 0.149 --conrod 0.217 --cr 12.8 --pin-offset=-0.00099`.

---

## Step 0 — One-time setup

**Terminal (dev PC):**
```
pip install -e ".[dev]"
python tools/gen_cas_traces.py  --help      # trace generator
python tools/compare_hrl.py     --help      # scores LabVIEW metrics vs truth.json
python tools/tune_thresholds.py --help      # recommends 9049_WarningLevels from metrics
```
**LabVIEW:**
1. Open `MONARCH.lvproj` → **My Computer** → open **`APC_SIL0_HRL_Desktop.vi`**.
2. On its front panel, locate the **`traces folder`** path control (top-left) — this is the
   only input you set. Outputs to watch: `Pressure Trace` / `HP filtered` graphs,
   `CombustionAnalysisCluster`, `PcylDiagWarningsAndErrors`.

*Accept:* the three tools print `--help`; the harness VI opens with no broken run-arrow.

---

## Step 1 — Generate the motored trace set

**Terminal:**
```
python tools/gen_cas_traces.py motored_set --cycles 30 --mode motored \
  --bore 0.112 --stroke 0.149 --conrod 0.217 --cr 12.8 --pin-offset=-0.00099
```
Writes into `motored_set/`: `cycle_NNNN.csv` (9×7200 raw), **`cycle_NNNN_phased.csv`
(6×7200, each cylinder in its own frame, TDC at sample 3600 — the harness reads these)**,
and `truth.json`. `--mode motored` = compression/expansion only → IMEP ≈ −1 bar, Pmax ≈
150 bar at this geometry.

*Accept:* 30 `*_phased.csv` files + `truth.json` present.

---

## Step 2 — Run the harness → metrics, re-confirm the math

**LabVIEW (click-level):**
1. In `APC_SIL0_HRL_Desktop.vi`, click the **`traces folder`** browse (folder) button and
   select the **`motored_set`** folder (the harness globs `*_phased.csv` inside it).
2. Click the **Run** arrow (or **Ctrl+R**). The For-loop steps every phased CSV → reads it
   (comma delimiter) → `support/APC_HRL.vi` (which loops over the 6 cylinders internally, so
   `IMEPg/IMEPn/Pmax/CA50` come out as 6-element arrays) → writes one row per (cycle, cyl)
   `[cycle, cyl, IMEPg, IMEPn, Pmax, CA50]` to **`motored_set/labview_metrics.csv`**.
3. Watch `Pressure Trace` sweep and `CombustionAnalysisCluster` update per file.

**Terminal (sanity gate before trusting any threshold):**
```
python tools/compare_hrl.py motored_set/truth.json motored_set/labview_metrics.csv
```
*Accept:* `labview_metrics.csv` has 30×6 = 180 numeric rows and `compare_hrl` prints
**"ALL metrics within tolerance"**. If it fails, fix the harness before proceeding.

---

## Step 3 — Recommend & enter the MOTORING thresholds  ← *core remaining SIL-0 work*

**Terminal:**
```
python tools/tune_thresholds.py motored_set/labview_metrics.csv --mode motored \
  --pmax-hard-limit <engine over-pressure ceiling, bar — get from the team>
```
Prints the full `9049_WarningLevels` set (each field as `<field>Warning` / `<field>Error`)
+ the `samples for running IMEP std` window, with rationale. Expect:
- **`MaxPCylMax`** — Warning ≈ peak×1.2, Error ≈ min(peak×1.3, `--pmax-hard-limit`); the
  Error limit is never allowed above the physical ceiling.
- **`MaxIMEPstd` / `MaxDevFromAvg` / `MaxDevFromSelfAvg`** — generous (motored cycles repeat).
- **DISARMED for motoring** (field set to the huge sentinel): `CA50max` (motored CA50 is MFB
  noise), `MaxDevFromExpectedIMEP` (the unwired-Expected-IMEP-0 trap, F3), `MAPOmax`
  (motoring can't knock).
Tuning knobs: `--pmax-margin` (1.30), `--std-margin` (5.0), `--imep-std-samples` (20).

**LabVIEW UI (click-level) — enter the profile on the 9049:**
1. Open the operator UI **`APC_PC_UI_Errors.vi`** (needs the 9049's shared variables live —
   see `docs/deployed-bringup.md` for host/SV setup).
2. Select the **CYLINDER** (9049 diagnostics) tab.
3. Type each printed **Warning** and **Error** value into the matching field (`MaxPCylMax…`,
   `CA50max…`, `MAPOmax…`, `MaxDevFrom…`, plus `cycles for std` / `samples for running IMEP
   std`).
4. Click **set new warning levels** (`SetWarningLimits`) → pushes them into `9049_WarningLevels`
   (live).
5. Click **save to ini file** (`SaveWarningLimitsToINI`) → persists to `CylWarningLevels.xml`
   on the 9049 so it survives redeploy (`LoadWarningConfig` reloads it at startup).
6. *(Optional verify)* pull `CylWarningLevels.xml` off the 9049 and eyeball it — see
   `docs/crio-file-access.md`.

*Accept:* the motoring profile saved on the 9049; a **CLEAR WARNINGS** then
`CylPressError = FALSE` confirmed before the first IDLING request.

> ⚠ **One profile slot only.** Steps 3 and 5 both write the *same* `CylWarningLevels.xml`.
> There is no motoring/fired auto-switch in the as-built — swapping profiles is manual
> today (re-enter + Save before changing run type). See `docs/9049-openloop-audit.md` Step 3
> and the port backlog in `docs/migration-seam.md` (item 3).

---

## Step 4 — (optional) add MAPO + IMEPstd columns to the harness

`MAPOmax` (knock) and `MaxIMEPstd` (cyclic variability) can't be derived from IMEP/Pmax/CA50
— they need the analytics' own `MAPO` and `IMEPstd`. `APC_HRL` **already computes** both
inside `CombustionAnalysisCluster` (visible on the harness panel); the harness just isn't
writing them to CSV yet.

**LabVIEW (click-level), in `APC_SIL0_HRL_Desktop.vi` block diagram:**
1. Unbundle **`MAPO [bar/CAD]`** and **`IMEPstd [bar]`** from `CombustionAnalysisCluster`
   alongside the existing four metrics.
2. Extend the inner-loop **Build Array** to include them.
3. Write a header row naming the columns (the tool matches by name, order-independent):
   ```
   cycle,cylinder,imep_g,imep_n,pmax,mapo,ca50,imepstd
   ```
4. Re-run Steps 1–2, then `tune_thresholds`: the report now reads "analytics IMEPstd column"
   and, in `--mode fired`, emits a numeric `MAPOmax`. Motored still disarms `MAPOmax` but
   tightens `MaxIMEPstd` from the real column.

---

## Step 5 — Fired profile + false-trip / latch matrix  → **SIL-1, not SIL-0**

*(Click-level SIL-1 procedure: `docs/sil1-scope-of-work.md`.)*

Generate a fired set and tune a fired profile the same way:
```
python tools/gen_cas_traces.py fired_set --cycles 30 --mode fired --fire-from 0 \
  --bore 0.112 --stroke 0.149 --conrod 0.217 --cr 12.8 --pin-offset=-0.00099 [--q-fired 6000]
python tools/tune_thresholds.py fired_set/labview_metrics.csv --mode fired --pmax-hard-limit <ceiling>
```
Fired mode arms `CA50max` (from data) and, with the MAPO column, `MAPOmax`;
`MaxDevFromExpectedIMEP` stays disarmed unless Expected IMEP is actually driven.

**The latch tests themselves are SIL-1** — they need `Pcyl_Diag → CombCluster2Array →
9049_Global_CylPressError` on the real 9049. Inject each fault with the generator
(`--misfire <cyl>:<cycle>`, `--knock <cyl>:<cycle>:<intensity>`, first-cycle zero-pad) and
confirm the mapped Error **trips and latches**, then that **PC CLEAR WARNINGS →
`APC_MASTER_ClearWarnings` → 9049 `APC_SLAVE_ClearWarnings`** releases it and spark/DI gating
is restored.

---

## SIL-0 exit criteria / deliverables

- [x] Math validated: `compare_hrl` "ALL within tolerance" on a mixed set (done 2026-07-11).
- [ ] `labview_metrics.csv` regenerated with the **MAPO + IMEPstd** columns (Step 4).
- [ ] **Motoring** `9049_WarningLevels` profile derived, entered, and **saved to
      `CylWarningLevels.xml`** on the 9049; CLEAR→`CylPressError=FALSE` confirmed.
- [ ] **Fired** profile derived and recorded (kept as a *separate* set — see the one-slot
      caveat; do not overwrite the motoring set on the 9049 before a motoring run).
- [ ] False-trip matrix (which fault trips which metric at the chosen limits) documented in
      the commissioning book — **verified in SIL-1**.

## Known gotchas (from the audit)

- **`exhaust pressure` must be wired** on `APC_HRL` (flat `Initialize Array(3.0, 7200)`) or
  pegging → NaN.
- Read Delimited Spreadsheet must use the **comma** delimiter.
- `APC_HRL` has **no geometry input** (internal `VOL` constant) — geometry lives in the
  *generator* flags, so both must match the as-built engine.
- **First acquired cycle is zero-padded** (2-cycle circular buffer) → can nuisance-trip
  `cyclic variability`; the `MaxIMEPstd` floor (or skip-first-cycle) must suppress it —
  a SIL-1 check.
- The two-profile split is **not built** — see Step 3's caveat.
