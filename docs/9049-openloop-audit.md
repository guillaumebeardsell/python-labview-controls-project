# APC_9049_RT_main — Open-Loop Commissioning Audit & SIL Plan

Does the cRIO-9049 application (RT + FPGA, `APC_9049_RT_main.vi` and every
sub-VI) work as intended for the **first commissioning campaign — engine
operation only, open-loop** (motoring, then firing with manual spark/DI
settings; no closed-loop combustion or plant control)? And how do we exercise
it **software-in-the-loop, with synthetic data, before anything is fueled or
sparked**?

Audited 2026-07-08 from the fresh VI exports under
`original-labview-codebase/` (HTML + full-res diagram GIF/PNG, read page by
page), the two FPGA PDFs ([Deck] = `20251020ERD01GUI01 FPGA on cRIO 9049.pdf`,
[GDoc] = `9049 FPGA VIs - Google Docs.pdf`), the Overview PDF, the E1/M1
report ([Report] = `20231130ENG02CWN01_E1_M1report_GUI.docx`), and the vendor
EPT manual ([EPT-UM] = `EPT_VI_UM_RevB.pdf`, Drivven/NI Powertrain). Where the old
PNG thumbnails and the fresh GIF exports disagree, the GIFs (current live VIs)
were used. **Caveat:** everything here is read from rendered diagrams; items
marked ⚠VERIFY need a check in LabVIEW or on the bench — saved front-panel
defaults especially, because on a headless RT deployment the compiled panel
defaults *are* the configuration.

Companion tool: `tools/gen_cas_traces.py` generates synthetic CAS
cylinder-pressure cycles (correct 9×7200 shape, phasing, pegging behavior)
with a ground-truth `truth.json` for verifying the analysis chain.

**Currency & where to start (as of 2026-07-13).** The static audit (F1–F9,
§§2–6) stands unchanged. Since it was written: **SIL-0 is validated** (§7 — 425
metric comparisons all in tolerance), the **engine geometry is resolved and in
use** (picture15 values, §7), and the **threshold recommender is built**
(`tools/tune_thresholds.py` — emits the full `9049_WarningLevels` Warning+Error
set with the motoring disarm list). **→ Execution order = §7, layered SIL-0 →
SIL-1 → SIL-2 → SIL-3, then the §8 pre-fuel checklist.** The immediate next
action is the "Still to do in SIL-0" block: run a `--mode motored` set through
the harness and `tune_thresholds.py` to produce the motoring warning-XML. One
prep item unlocks knock/cyclic-variability tuning: add `MAPO` + `IMEPstd`
columns to the harness Build-Array (both already in `CombustionAnalysisCluster`;
one-line change — see §7). Tool pipeline map: `tools/README.md`.

---

## 1. The short answer

The 9049 application is in **substantially better shape than the 9056 side
was**: the architecture is sound, the safety anchors are real and fail-safe,
and the core engine-synchronous chain (sync → spark/DI scheduling →
encoder-clocked acquisition) was **already validated at TTL level by the
original developer** using a physical encoder emulator ([Report], Fig. 20 —
an Arduino generating encoder/cam signals, spark & injection TTL outputs
loop-verified, CAS processing proven to 4250 rpm and "aligned with NOBLE
calculation script").

What was **never** validated: physical actuation (real coils/injectors),
sensor calibration (placeholders in the VI today), the pressure *diagnostics*
added after the 2023 report (they gate spark/DI and **will false-trip as-built
— see F2/F3**), and data recording end-to-end.

And the headline for SIL: **a virtual crankshaft is built in and
vendor-documented.** The NI Powertrain EPT position-tracking core on the FPGA
has a pattern simulator (`EPTControl.SimEnable`/`SimPeriod`, reachable from
the `TS10ms_loop` front panel, saved `SimPeriod=500` ≈ 1333 rpm — the
developer clearly used it). Per [EPT-UM]: with `SimEnable` TRUE the physical
`CrankSig`/`CamSig` inputs are internally disconnected and replaced by
simulated counterparts — the simulator generates **both** the crank *and* the
cam/Z reference for the configured pattern, so full sync is achievable; the
feature exists exactly "to bench test the engine control system functionality
… without the need for external simulation hardware" (the manual's own FPGA
example runs with *no external signals wired at all*). The exports further
show the CAS DAQ sample clock (`cRIO_Trig0`) is wired from EPT's
`CrankSigOut`, which carries the simulated signal in sim mode ([GDoc]). Flip
one boolean and the whole engine-synchronous stack runs against a phantom
engine on the real cRIO — no encoder, no rotation.
`APC_9049_PPhaseCorrection` additionally has a built-in canned-pressure mode
(`UsePcylDatabase`). Both are also *hazards* if left enabled — see the
pre-fuel checklist.

## 2. Verdict summary

| VI | Verdict for open-loop commissioning |
|---|---|
| `RT_main` | ✅ Works. Two-frame sequence: SensorCalibration, then CAS/SAVE/TS10ms in parallel forever. The Diagram-Disable frames (Modbus healing loop, legacy System-PID loop) are **deleted outright** in the live VI (README's "currently Disabled" is outdated). No error gating: loops start even if DAQ-task creation failed (benign on-target; see §5 for dev-PC behavior). |
| `TS10ms_loop` | ✅ Works, 3 risks (F1, F5, F6). Gate logic confirmed: `enable = ¬CylPressError ∧ ActivateCylinder ∧ UI-enable ∧ (SYSTEMSTATE ≥ 2)` per cylinder, spark and DI separately. FPGA `WatchdogIn` toggled unconditionally each 10 ms tick — fail-safe by dataflow (an upstream error that stops the FPGA write also stops the toggle → FPGA kills outputs). Loop never exits; errors latch to a border indicator only. |
| `SparkSettings` | ✅ Works. SA/cutoff → CAT conversion correct; dwell **hard-coded 4 ms (2–6 clamp)** via saved defaults (unwired at call site); cutoff −60 DBTDC from caller. |
| `KnockCA50Control` | ✅ Inert as configured (both enables come from `PC_ControlSettings`, off ⇒ manual SA passes through untouched). Not usable for closed loop later without new values (knock retard/advance params saved 0, PID gains dummy, SA clamp ±100 CAD is no protection). |
| `ControlSettingsRaster` | ⚠ DEFECT-grade echo issues (F4). |
| `CAS_loop` | ✅ Works. Self-healing acquisition (1 s DAQ timeout → stop/restart task, no error latch-up, ~1 Hz idle retry with no encoder); lossy bounded queues (1000-cycle rolling pre-trigger buffer) — no deadlock/growth path found. Risks: `Enque?` is an unbound panel control (compiled default decides whether SAVE ever gets data ⚠VERIFY); analytics still run on timeout garbage (feeds F3). |
| `SensorCalibration` | ❌ NEEDS-CONFIG (F2): pressure "calibrations" are NI-example placeholders. Task: AI voltage, sample clock `/cRIO0/cRIO_Trig0` falling ("encoder sample clock"), start trigger `cRIO_Trig1` rising, continuous, 7200-buffer. |
| `SAVE_loop` | ✅ Design sound (flush/buffer/post-mortem paths, no-disk branch), idle-safe. Config risks: `Cycles to measure` saved 0, `BufferingTimeLimit` saved 0, `DataSaveControl` write-back race with the PC UI, panel "No disk" LED saved red ⚠VERIFY recording end-to-end on the bench. |
| `9056SharedVarPolling` | ✅ Works; absent/wrong-size 9056 array ⇒ all-NaN ⇒ `NaN ≥ 2 = FALSE` ⇒ gate fails safe. **No staleness check** — a *frozen* 9056 publisher holds the last state forever (F7). |
| `PressureAnalytics` chain | ⚠ Two structural findings (F2 cal, F3 diagnostics) + known author flags (§6). Data path and per-cylinder re-phasing confirmed correct (offsets 0,4800,2400,6000,1200,3600 ⇔ firing order 1-5-3-6-2-4, consistent with the TS10ms TDC offsets ×10). |
| `FPGA_main` + EPT/di_supv/esttl | ✅ Safety anchors confirmed (§3). |
| `FPGA_IGNDI_supervisor` | ✅ Works; indicator-only consumer, but it's a ready-made pass/fail probe for bench spark/DI tests (12 = all channels active). Saved-panel snapshot shows `Fault1 = 126` on both NI 9751 modules — decode before trusting DI health telemetry ⚠VERIFY. |

## 3. Safety anchors (confirmed as-built)

1. **FPGA watchdog**: `EPTControl.WatchdogIn` must toggle > 4 Hz; trip shuts
   down position tracking and all engine-synchronous outputs (spark/DI die
   with sync — both consume EPT's `FuelSparkSupervisor`). RT toggles it every
   10 ms unconditionally. *Auto-recovery on resumed toggling is undocumented —
   bench-verify (SIL-1 drill).*
2. **Sync-loss latch**: `MissedCrankFlag`/`MissedCamFlag` latch and block
   re-sync until explicitly cleared (UI "Clear Sync Errors" → RT, or the
   TS10ms panel switch). Confirmed by [EPT-UM] (encoder pattern): Z-edge
   early / Z-edge missing ⇒ loss of sync, "re-sync is not allowed until the
   flag is cleared". Falling below stall speed also drops sync
   (CrankCount/CurrentPosition → 0, `SyncStopped` TRUE) but does not latch.
3. **Spark Key interlock**: spark output (`esttl_vt_spark_reva`) requires the
   `Key` emitted by the DI supervisor — **spark cannot fire unless the NI 9751
   DI chain is powered and enabled, even for spark-only tests.** Plan bench
   sessions accordingly (and note: motoring is doubly spark-safe).
4. **Power-up/no-encoder state is safe**: modules configured then idle;
   unsynced EPT + no DI enables + no Key ⇒ all engine-sync outputs dead until
   RT connects *and* sync + state + enables all line up.
5. **RT-side hard gate**: spark/DI enables ANDed with `SYSTEMSTATE ≥ 2` and
   `¬CylPressError` (per cylinder) — confirmed on the diagram. The state input
   is the 9056-relayed echo, so the 9056 StateMachine (and its warning clamp +
   the B0 watchdog) sits above 9049 actuation, as designed.

## 4. Findings that need action (ranked)

**F1 — `Override PC settings` bypasses BOTH safety gates.** The TS10ms True
case substitutes panel-manual enables/settings for the PC-derived ones
*upstream of nothing*: the `SYSTEMSTATE ≥ 2` and `¬CylPressError` gates are
simply not applied in override mode. It's a deliberate dev/bench feature (and
genuinely useful for SIL — §7), but it must never ride into a fueled system
enabled. ⚠VERIFY saved default = FALSE in LabVIEW; add to the pre-fuel
checklist; longer-term consider re-wiring the override *downstream* of the
gates or deleting it from the deployed build.

**F2 — Sensor calibrations are placeholders.** The CAS task's per-channel
custom scales (saved panel defaults of a headless VI) read like NI-example
leftovers: slopes 1.00 (one 100.00), intercepts 0/5/10/15/0…, all "bar",
±10 V. Until real transducer calibrations are entered, every pressure number
— including the `CylPressError` decision that gates spark/DI — is
meaningless. Enter real cals (and preferably move them to a config file, like
the 9056's XML pattern) before any pressure-dependent step. Channel order:
[Pcyl1–6, Ppre, Psyst, Pexh] = rows 0–8.

**F3 — The pressure diagnostics will false-trip and then silently veto
firing.** Confirmed semantics: per-category *error* flags latch (cleared only
by the PC CLEAR WARNINGS → `APC_MASTER_ClearWarnings` → 9049 relay
`APC_SLAVE_ClearWarnings`); any latched error on any cylinder ⇒
`9049_Global_CylPressError` = TRUE ⇒ spark and DI gated off. The chain has
**no state awareness** (checks run identically motored or fired), and:
- `Expected IMEP` — the reference for the misfire-from-IMEP check — is an
  **unwired front-panel control, saved 0.0, not on the connector pane**;
  nothing can set it at runtime. As-built, `MaxDevFromExpectedIMEP` trips on
  any healthy firing (IMEP ≫ 0) *and* on motoring (IMEP ≈ −1 bar) unless its
  thresholds are opened wide.
- CA50 on motored data is noise (the MFB rescale normalizes whatever it gets)
  → `CA50max` errors latch randomly while motoring.
- The first cycle after acquisition start is zero-padded garbage (2-cycle
  circular buffer init) → running-IMEP-std / cyclic-variability errors likely
  latch at every acquisition start.
- The deployed thresholds live in an XML on the cRIO (via
  `LoadWarningConfig` → `9049_WarningLevels`) whose contents are unknown —
  possibly never set. ⚠VERIFY on target.

**Confirmed from the exports (2026-07-11 — `LoadWarningConfig` / `Pcyl_Diag` /
`CombCluster2Array`).** `Pcyl_Diag` compares each metric to a **Warning** and an
**Error** limit and emits two flag clusters; `CombCluster2Array` treats them
differently — this is the crucial detail:
- **Warnings** (index 0) → simple OR → the `WarningsAndErrors` indicator only
  (advisory, non-latching).
- **Errors** (index 1) → **feedback-node latch** per category → OR across all →
  `9049_Global_CylPressError`. Only the *Error* level latches and vetoes fire;
  the latch clears only when `APC_SLAVE_ClearWarnings` fires (True case).

The exact field↔flag↔metric map (each field has a `…Warning` and `…Error`
variant; the trip is `metric > threshold`):

| Error flag | `9049_WarningLevels` field | metric compared |
|---|---|---|
| maximum pressure | `MaxPCylMax` | Pmax |
| cyclic variability | `MaxIMEPstd` | running IMEPn std |
| misfire cyl-to-cyl | `MaxDevFromAvg` | \|IMEPg − cyl-mean\| |
| misfire self reg | `MaxDevFromSelfAvg` | \|IMEPn − own running mean\| |
| misfire from IMEP | `MaxDevFromExpectedIMEP` | \|IMEPn − Expected IMEP\| |
| knock | `MAPOmax` | MAPO |
| late combustion | `CA50max` | CA50 |

plus `samples for running IMEP std` (I32). `tools/tune_thresholds.py` emits this
exact set (Warning+Error) from a SIL metrics CSV.

Actions: build a **motoring threshold set** (MaxDevFromExpectedIMEP, CA50max and
MAPOmax disarmed — motoring can't knock and has no combustion phasing; IMEP-std
and dev-from-avg generous; MaxPCylMax ≈ observed motored peak ×1.3, capped at the
hardware ceiling) and a separate **fired set**. `tools/tune_thresholds.py` emits
both directly from a metrics CSV. **Knock (`MAPOmax`) and cyclic-variability
(`MaxIMEPstd`) auto-tune only if the harness CSV carries `mapo`/`imepstd`
columns** — add them to the `APC_SIL0_HRL_Desktop` Build-Array (both are already
in `CombustionAnalysisCluster`); until then `MAPOmax` stays hand-set for firing.
Add the procedural step *"after sync is stable under motoring: CLEAR WARNINGS,
confirm `CylPressError` = FALSE, then request IDLING/FIRING"*; decide the
Expected-IMEP fix (wire it from `PC_ControlSettings`/a shared variable, or
permanently disarm that category — as-built it is dead weight that only false-trips).

**F4 — `9049_ControlSettings` echo is not what consumers think.** Fresh
export shows: element **[0] is wired to the `PFI0 mode` panel control
(constant 0), not the system state** (author note: "…used for broadcasting
current combustion mode through PFI0"); **[1] InjectionEnable and [5]
SparkEnable pass through Boolean-Array-To-Number** — i.e. 6-cylinder bitmasks
0–63, not 1/0 (this contradicts the earlier 2026-07-07 reading recorded in
`supervisory/monarch/settings_9049.py`; a live capture decides — drive all
six cylinders enabled and read whether [1] is 1 or 63); and the raster taps
the **pre-Override wires**, so in override mode the echo reports what the PC
*would have* commanded, not what fires. Consequences: the PC/9056/Python
consumers of the echo see a stale state 0 in [0] today. Reconcile with a live
capture during SIL-1, then fix `settings_9049.py` to match reality.

**F5 — Simulation provisions must be OFF for any fueled run.** Saved panel
values found: `SimPeriod = 500` (and a non-zero EPTData snapshot — the sim
was used); `UsePcylDatabase` render ambiguous. A build deployed with
`SimEnable` TRUE "syncs" happily to a phantom engine; with `UsePcylDatabase`
TRUE the diagnostics run on canned data. Both ⚠VERIFY = FALSE before
deployment; both belong on the pre-fuel checklist permanently.

**F6 — Compiled-default configuration debt (headless deploy).** Several
behavior-defining controls are unbound panel controls whose saved value is
the deployed configuration: `Override PC settings`, `Enque?` (CAS→SAVE data
flow!), `1/2 Z pulse`, `Must Use Cam & Z`, `toggle TDC`, the DIControl enable
switches, SimEnable/SimPeriod, `Cycles to measure`, `BufferingTimeLimit`.
⚠VERIFY each in LabVIEW and record the intended values in a deployment sheet
(candidate for a small INI, same pattern as the 9056).

**F7 — No 9049-side staleness guard on the 9056 state relay.** If the 9056
*stops publishing but the value stays* (process frozen), the 9049 holds the
last `SYSTEMSTATE` indefinitely — including ≥ 2, which keeps spark/DI
enabled with a dead supervisor above them. (Total absence is safe: NaN →
gate closed. And the 9056-side WatchDog covers the reverse direction,
9049-loss → SAFE.) Cheap mitigation when wanted: stall-count
`TimeStamp9056` (element 0 of the polled array) in CAS_loop and treat stale
as state −1. Log as a commissioning watch item; same family as the closed
loss-of-PC gap.

**F8 — Analytics accuracy debt (author-flagged, inherited).** `HRL_volume`:
"FIX STROKE CALC", crankpin-offset inaccuracy, IVC/EVO/EVC "to be updated" ⇒
absolute IMEP bias (motored and fired); threshold calibration inherits it.
`APC_9049_CA`: the CA97 detector constant renders as 0.9 (same as CA90) —
if real, CA97/CA10CA90 are wrong ⚠VERIFY. Pegging window = cylinder-frame
samples 6900–7100 (+330…+350 CADATDC), additive peg to LP-filtered exhaust —
fine, but Pmax-class metrics are offset-sensitive to a bad exhaust channel.
None of this blocks motoring; it blocks *trusting* absolute numbers. The
2023 "aligned with NOBLE calculation script" claim gives the cross-check
route: rerun that alignment via SIL-0 with `truth.json`.

**F9 — DI hardware unknowns for the firing step (from [Report], still
open).** Injector current profile inherited from a single-cylinder project
("could be biased"); physical actuation of all six never verified; 9751
`Fault1 = 126` snapshot to decode. Bench DI dry-fire (SIL-3) before fuel.

## 5. What the open-loop use case does / doesn't need

Not needed (and confirmed inert when off): KnockCA50 closed loop (both
enables off ⇒ manual SA passthrough), PFI (strategy replaced by intake flow
regulator), MTR/membrane, all 9056 closed-loop combustion-adjacent modes
(9056 loops run mode 0/1), Modbus healing loop + legacy System-PID loop
(deleted from RT_main). The dyno speed loop and thermal loops are 9056
territory and out of scope here.

Needed and used: EPT sync chain, spark path (manual SA + fixed 4 ms dwell,
cutoff −60), DI path (manual duration/SOI, window constants now **200/0
DBTDC** on the diagram — matches [GDoc]; the older 90/−30 reading is
outdated), per-cylinder activate flags, CAS acquisition + analytics (as
monitor + `CylPressError` gate), SAVE recording (the commissioning product),
the state echo, and both watchdog directions.

Minimal command surface (all already modeled in
`supervisory/monarch/control_settings.py`): Activate cylinder ×6, DI enable +
duration + advance, IGN enable + spark advance, CA50/Knock control = OFF,
requested mode, speed selector. The existing Python command path (Phase B/C)
can drive all of it.

## 6. On "working as intended" — the honest scoreboard

- **Proven by the 2023 campaign** ([Report]): sync + filtering + TDC toggle;
  CAS clock/trigger generation; 6-cyl CAS processing to 4250 rpm; spark/DI
  TTL outputs incl. per-cylinder disconnect; TDMS logging toolchain.
- **Confirmed by this audit (static)**: gate logic, watchdog dataflow,
  restart/queue robustness, phasing consistency, safety anchors, limiter
  independence (9056 above 9049).
- **Broken/misleading as-built**: F1–F4 above.
- **Unprovable without a bench run**: watchdog auto-recovery, deployed panel
  defaults, warning-XML contents, Trig0-follows-sim, recording end-to-end,
  echo element semantics — exactly the SIL-1 agenda below.

## 7. SIL plan — layered, cheapest first

**SIL-0 — analytics on the dev PC (no hardware). — MATH VALIDATED
(2026-07-11).** → **Click-level step-by-step: `docs/sil0-scope-of-work.md`.**
Generate traces (real MONARCH geometry, from picture15 — bore 0.112,
½-stroke `Lm`=0.0745, rod `Lb`=0.217, CR 12.8, offset −0.00099):
`python tools/gen_cas_traces.py sil0_traces --cycles 20 --mode mixed
--fire-from 10 --misfire 3:14 --knock 1:16:2.5 --bore 0.112 --stroke 0.149
--conrod 0.217 --cr 12.8 --pin-offset=-0.00099 [--q-fired 6000]`. The
generator emits **`cycle_NNNN_phased.csv` (6×7200, already phased, TDC at
sample 3600)** + `truth.json`.

**Harness built:** `APC_SIL0_HRL_Desktop.vi` on My Computer (globals-free —
sidesteps the `9049_Global_CylPressError` target-relative trap): List Folder
(`*_phased.csv`) → For loop → Read Delimited Spreadsheet (**comma** delimiter)
→ **`support/APC_HRL.vi`** with `Pcyl`=6×7200, `exhaust pressure`=flat
`Initialize Array(3.0, 7200)`, `FilterCoefs` from `HRL_CreateFilter`
(`Expected IMEP` left unwired — feeds only the misfire diag). `APC_HRL` has
**no geometry input** (internal `VOL` constant) and runs its **own For loop
over the 6 cylinders**, so its cluster fields (`IMEPg/IMEPn/Pmax/CA50`) come
out as **6-element arrays**. Inner loop over those → rows
`[cycle, cyl, IMEPg, IMEPn, Pmax, CA50]` → concatenating tunnel → Write
Delimited Spreadsheet → `labview_metrics.csv`. Score with
`tools/compare_hrl.py truth.json labview_metrics.csv`.

**Result (2026-07-11): 425 comparisons, ALL within tolerance** — worst |Δ|
IMEPg 0.001 bar, IMEPn 0.000, Pmax 0.002 bar, CA50 0.112 CADATDC, across all
20 cycles × 6 cylinders (motored + fired). The 9049 HRL/IMEP/CA50 math is
faithful vs known truth (F8 verdict: the math is sound; any absolute IMEP
bias would show as a consistent offset — none seen at this geometry).
*Python side (generator + `compare_hrl.py` + tests) done and self-tested.*

**Still to do in SIL-0 (the false-trip matrix + thresholds) — the immediate
next action.** This produces the two warning-XML profiles (motoring, fired) the 9049 loads at
run time, and proves the false-trip/latch behaviour F3 warns about. **Scope
boundary:** the desktop harness runs `support/APC_HRL.vi` **only** (it computes
the metrics), so Steps 1–4 (generate → metrics → thresholds) run fully
off-hardware; the **latch** tests (Step 5) need the
`Pcyl_Diag → CombCluster2Array → 9049_Global_CylPressError` chain and are best
run in SIL-1 on the real 9049 — that global is a *target-relative single-process*
variable (the trap that kept those VIs off the desktop harness).

**Step 1 — Generate the motored trace set.**

```
python tools/gen_cas_traces.py motored_set --cycles 30 --mode motored \
  --bore 0.112 --stroke 0.149 --conrod 0.217 --cr 12.8 --pin-offset=-0.00099
```

Writes into `motored_set/`: raw `cycle_NNNN.csv` (9×7200 — Pcyl1–6, Ppre, Psyst,
Pexh), **`cycle_NNNN_phased.csv` (6×7200, each cylinder already in its own frame,
TDC at sample 3600 — these feed `APC_HRL` directly)**, and `truth.json` (the
computed IMEPg/IMEPn/Pmax/CA50 per cycle·cylinder). `--mode motored` =
compression/expansion only, no combustion, so IMEP ≈ −1 bar and Pmax is the
motored peak (~150 bar at this geometry/CR). Geometry is the picture15 as-built
(`--stroke 0.149` = 2×half-stroke 0.0745); raise `--cycles` for tighter
statistics. *Accept:* 30 `*_phased.csv` + `truth.json` present; the generator
prints the per-cycle period.

**Step 2 — Run the set through the harness → metrics, and re-confirm the math.**
Point `APC_SIL0_HRL_Desktop.vi` (My Computer) at `motored_set/`: List Folder
(`*_phased.csv`) → For loop → Read Delimited Spreadsheet (**comma** delimiter) →
`support/APC_HRL.vi` with `Pcyl` = the 6×7200 array, `exhaust pressure` =
`Initialize Array(3.0, 7200)` (flat — **must** be wired or pegging → NaN),
`FilterCoefs` from `HRL_CreateFilter`. `APC_HRL` runs its own loop over the 6
cylinders, so its `IMEPg/IMEPn/Pmax/CA50` come out as **6-element arrays**; the
inner loop writes one row per (cycle, cyl) — `[cycle, cyl, IMEPg, IMEPn, Pmax,
CA50]`, **cycle = outer i+1, cyl = inner i+1** — through a concatenating tunnel →
Write Delimited Spreadsheet → `motored_set/labview_metrics.csv`. Then sanity-check
before trusting any threshold derived from it:

```
python tools/compare_hrl.py motored_set/truth.json motored_set/labview_metrics.csv
```

*Accept:* `labview_metrics.csv` has 30×6 = 180 numeric rows and `compare_hrl`
prints "ALL metrics within tolerance". (If it fails, fix the harness before
Step 3 — every threshold below is derived from these numbers.)

**Step 3 — Recommend and enter the motoring thresholds.**

```
python tools/tune_thresholds.py motored_set/labview_metrics.csv --mode motored \
  --pmax-hard-limit <engine over-pressure ceiling, bar>
```

Prints the full `9049_WarningLevels` set (each field as `<field>Warning` /
`<field>Error`) plus the `samples for running IMEP std` window, with rationale:

- **`MaxPCylMax`** — Warning ≈ peak×1.2, Error ≈ min(peak×1.3, `--pmax-hard-limit`).
  The ceiling is the engine's physical over-pressure limit (get the number from
  the team); the Error limit is never allowed above it.
- **`MaxIMEPstd` / `MaxDevFromAvg` / `MaxDevFromSelfAvg`** — generous (motored
  cycles are repeatable; these mainly guard against acquisition glitches).
- **DISARMED for motoring** (the XML field set to the huge sentinel — effectively
  off): **`CA50max`** (motored CA50 is MFB noise), **`MaxDevFromExpectedIMEP`**
  (the unwired-Expected-IMEP-0 trap, F3), **`MAPOmax`** (motoring can't knock).

Enter each Warning + Error into the **UI CYLINDER (Errors) screen**
(`APC_PC_UI_Errors.vi`) → this sets `9049_WarningLevels` (`SetWarningLimits`);
**Save to INI** (`SaveWarningLimitsToINI`) so it survives redeploy, and
`LoadWarningConfig` loads it into the running 9049 at startup. Adjust margins with
`--pmax-margin` (default 1.30), `--std-margin` (5.0), `--imep-std-samples` (20 =
the I32 std window). *Accept:* the motoring profile saved on the 9049; a CLEAR
WARNINGS then `CylPressError = FALSE` confirmed before the first IDLING request.

**Keep a separate fired profile.** Once fired cycles exist (a `--mode fired`
synthetic set now, or captured light-off data later): same harness →
`tune_thresholds … --mode fired --pmax-hard-limit <ceiling>`. Fired mode arms
`CA50max` and `MaxDevFromExpectedIMEP` from the data — but the latter still
**requires Expected IMEP actually driven** (else leave it disarmed); `MAPOmax`
stays hand-set unless you add the MAPO column (Step 4). Save it as a **second**
XML profile; never fire on the motoring set.

> **⚠ The two-profile scheme is NOT built — this is new work, not "save a second file."**
> The as-built 9049 has a **single** profile slot: one `9049_WarningLevels` variable
> persisted to one hardcoded `CylWarningLevels.xml` (`APC_9049_LoadWarningConfig.vi`,
> no state input), and the UI edits that one slot — `SaveWarningLimitsToINI` **overwrites**
> the file, it does not keep two. A real motoring/fired split needs: (a) two persisted
> profiles; (b) a **state-driven selector on the 9049** that swaps the active limits at the
> MOTORING↔FIRING transition; (c) UI to edit each profile; (d) **fail-safe** handling —
> load-fail ⇒ hold the *tighter* set or safe-hold, tie the swap to *actual* (not commanded)
> state, and manage the `CylPressError` latch so the swap itself doesn't nuisance-trip.
> Until it's built, treat the two profiles as **operator-swapped by hand** (re-enter + Save
> the correct set before changing run type). Tracked in `docs/migration-seam.md` (backlog,
> item 3).

**Step 4 — (optional) add `MAPO` + `IMEPstd` harness columns to tune knock +
cyclic-variability from data.** `MAPOmax` (knock) and `MaxIMEPstd` (cyclic
variability) can't be derived from IMEP/Pmax/CA50 — they need the analytics' own
`MAPO` and `IMEPstd`, which `APC_HRL` already computes inside
`CombustionAnalysisCluster`; the harness just isn't writing them out. In
`APC_SIL0_HRL_Desktop.vi`, unbundle **`MAPO [bar/CAD]`** and **`IMEPstd [bar]`**
alongside the existing four, extend the inner-loop Build Array, and write a header
row naming the columns (the tool matches by name — `mapo`, `imepstd`,
order-independent):

```
cycle,cylinder,imep_g,imep_n,pmax,mapo,ca50,imepstd
```

Re-run `tune_thresholds`: the report now reads "analytics IMEPstd column" and, in
`--mode fired`, emits a numeric `MAPOmax` (×2/×3 of observed clean-combustion
MAPO — a starting point to refine from a knock-onset sweep). Motored still
disarms `MAPOmax` (no knock) but tightens `MaxIMEPstd` from the real column.

**Step 5 — the false-trip / latch matrix + clear-warnings path** (best done in
SIL-1 — needs the diagnostic chain, not just `APC_HRL`). Purpose: prove a genuine
fault latches `9049_Global_CylPressError` (which vetoes spark/DI) and that CLEAR
WARNINGS releases it — the behaviour F3 warns about. Synthesize each fault with
the generator, feed it through `Pcyl_Diag → CombCluster2Array`, and confirm the
mapped Error flag (see the F3 table) trips **and latches**:

- **Misfire** — `--misfire <cyl>:<cycle>`: a dead cylinder → IMEP collapses →
  `misfire from IMEP` / `misfire self reg` / `misfire cyl-to-cyl` Errors →
  `CylPressError` latches.
- **Knock** — `--knock <cyl>:<cycle>:<intensity>`: pressure oscillation → `MAPO`
  spikes → `knock` Error (requires `MAPOmax` armed + the MAPO column, Step 4).
- **First-cycle garbage** — the 9049's 2-cycle circular buffer makes the first
  acquired cycle zero-padded → `cyclic variability` may latch at every
  acquisition start; confirm the `MaxIMEPstd` floor (or a skip-first-cycle)
  suppresses it.

Then exercise the clear path: **PC CLEAR WARNINGS → `APC_MASTER_ClearWarnings` →
9049 relay `APC_SLAVE_ClearWarnings`** resets the feedback-node latches →
`CylPressError` returns FALSE and spark/DI gating is restored. *SIL-0 output:* the
finalized **motoring + fired warning-XML profiles**, plus a documented false-trip
matrix (which fault trips which metric at the chosen limits) in the commissioning
book.

**SIL-1 — virtual crankshaft on the real 9049 (EPT simulator).** → **Click-level
step-by-step: `docs/sil1-scope-of-work.md`.** Run
`RT_main` interactively from the dev environment (or a bench build), HV/fuel
physically absent. `SimEnable` TRUE; `SimPeriod = 60·4e7/(rpm·3600)` → 741 ≈
900 rpm, 370 ≈ 1800 rpm (or use the vendor `speed2ticks.vi`; the simulated
signals are also mirrored on `SimCrankSig`/`SimCamSig` indicators for scope
checks [EPT-UM]). Note the simulator injects *at the EPT input*, so the ½-Z
synthetic-cam logic, deglitch filters, and NI 9401 wiring are NOT exercised —
that's SIL-2's job. Agenda:
1. Sync acquired (CrankStalled/SyncStopped clear, CrankCount/CurrentPosition
   rolling, Speed(RPM) correct).
2. **Does Trig0 follow the sim?** The FPGA export shows `cRIO_Trig0` wired
   from `CrankSigOut` (which carries simulated signals in sim mode), so CAS
   acquisition should clock — the Deck's "Trig0 = ENC A" text describes
   pass-through. Confirm: CAS_loop stops timing out and delivers 7200-sample
   cycles (of whatever is on the 9222 terminals). **→ CONFIRMED on the bench
   (2026-07-14): `rpm from DAQ` = the TS10ms-set rpm, so Trig0 clocks acquisition in sim mode.**
3. Spark/DI scheduling: enable via `PC_ControlSettings` with the state gate
   satisfied (drive `9049_Global_SYSTEMSTATE` ≥ 2 by running the 9056, or SV
   injection, or — bench-only — Override mode w/ F1 noted); observe
   `NumberOfActiveIGN_DI` = 12, scope the Mod4 spark and Mod5/6 DI outputs,
   sweep SA/SOI from the Python command path and watch `dT inj`/`SparkOut`.
4. Drills: watchdog (stop the RT loop → outputs die; resume → document
   recovery behavior), sync-loss inject + clear, state-gate walk (spark/DI
   dead below state 2), `CylPressError` veto + clear, echo live-capture (F4),
   recording drill (REC → TDMS files appear, `Enque?` answered).
Pressure inputs during SIL-1 are whatever the 9222 terminals float at — use
the SIL-0-derived open thresholds, or drive 1–2 channels from a function
generator/AO, or (optional) the Seam-A sim-read below.

**SIL-2 — physical encoder emulation (the 2023 rig, resurrected).** Feed
real A(+B)+Z(+cam) TTL into Mod3 DIO0–3: the Arduino emulator from [Report]
Fig. 20 if it still exists in the lab, else a ~$20 microcontroller (in `1/2 Z
pulse` cam-less mode only **A + Z** are required; 1800 rpm = 108 kHz A, 30 Hz
Z, phase-locked — beyond typical two-channel function generators). Adds
coverage the internal sim can't: NI 9401 input path, deglitch filters, the
synthetic-cam logic, real quadrature. Also the path to *speed-transient*
tests the internal sim can't do without RT-side SimPeriod ramping.

**SIL-3 — actuation dry tests (commissioning entry, after SIL-1/2 pass).**
Spark coils on bench plugs; DI drivers into dummy loads/disconnected
injectors; remember the Key interlock (9751s must be powered+enabled for any
spark). Decode `Fault1=126` first (F9). This is the boundary where the
team's commissioning plan takes over.

**Optional Seam-A/B build (full-chain SIL with no cRIO at all):** CAS_loop's
DAQmx Read wrapped in a sim case that reads `cycle_*.csv` + waits one cycle
period (133 ms @ 900 rpm — printed by the generator); SensorCalibration's
task-creation frame already sits in a Diagram-Disable whose empty frame is
the natural stub. Worth building if the cRIO bench is a bottleneck;
otherwise SIL-1 covers more with less LabVIEW surgery.

## 8. Pre-fuel checklist (add to the commissioning book)

Every item ⚠ must be re-verified on the *deployed build*, not the dev copy:
1. `Override PC settings` = FALSE (F1) — and nobody's bench build leaks in.
2. `SimEnable` = FALSE, `UsePcylDatabase` = FALSE (F5).
3. Real sensor calibrations entered + spot-checked (F2).
4. Motoring warning XML loaded; CLEAR WARNINGS drill done; `CylPressError`
   = FALSE confirmed before first IDLING request (F3).
5. `Enque?` = TRUE + a recording drill has produced readable TDMS (F6).
6. Encoder mode flags (`1/2 Z pulse`, `Must Use Cam & Z`, `toggle TDC`)
   match the actual engine sensor set.
7. Watchdog drill + sync-loss drill passed on the deployed build (SIL-1 §4).
8. State-gate drill: spark/DI provably dead below IDLING from the real
   command path (not Override).
9. `9049_ControlSettings` echo reconciled with a live capture; Python
   `settings_9049.py` updated (F4).
10. E-stop path exercised end-to-end with the 9049 in the loop.

## 9. Open questions

- ~~Trig0-in-sim (decides SIL-1 item 2)~~ **RESOLVED (2026-07-14, bench): YES.** With the EPT
  sim running, `APC_9049_CAS_loop`'s `rpm from DAQ` tracked the `SimPeriod` rpm set on TS10ms —
  so `cRIO_Trig0` (from `CrankSigOut`) clocks CAS acquisition in sim mode. Acquisition testing
  does **not** need SIL-2's real encoder. (Also confirmed same session: `Graph time` delivers
  full 7200-sample cycles + DAQ error 0 — Step 2 fully closed.)
- Watchdog auto-recovery semantics (SIL-1 drill).
- Deployed warning-XML values; `Enque?`/Override/Sim saved defaults.
- Echo bitmask vs 1/0 (F4) — live capture.
- Does the Arduino encoder emulator still exist in the lab? (SIL-2)
- `Fault1 = 126` meaning (NI 9751 manual) (F9).
- ~~Engine geometry values~~ **RESOLVED** — bore 0.112 / stroke 0.149 / rod
  0.217 / CR 12.8 / pin-offset −0.00099 (picture15), used in SIL-0 and validated
  (§7, 425 comparisons in tolerance). Remaining: confirm picture15 matches the
  as-built engine, and the working-fluid (argon) kappas for the analytics.
