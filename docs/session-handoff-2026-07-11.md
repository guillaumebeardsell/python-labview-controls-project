# Session Handoff — 2026-07-11 (deployment + SIL-0)

Written so a future session (human or model) can pick up cold. This session
took the project from "Python logic built, nothing deployed" to **both cRIOs
running autonomously on hardware** and **the 9049 combustion analytics
validated on synthetic data**. Read `docs/migration-plan.md` for the phase
plan; this doc is the *current state + what to do next + what's still soft*.

---

## TL;DR — where things stand

- **Autonomous deployment WORKS and is cold-boot-verified.** Both cRIOs boot
  their startup `.rtexe`s at power-on; the PC HMI + Python gateway run as
  standalone EXEs; Python observes and can command. Five latent deployment
  bugs were found and fixed (all invisible in dev mode). Runbook +
  symptom→cause table: **`docs/deployed-bringup.md`**.
- **SIL-0 analytics math VALIDATED.** `APC_SIL0_HRL_Desktop.vi` (globally-free,
  on My Computer) runs synthetic pressure traces through the real
  `support/APC_HRL.vi`; **425 metric comparisons, all within tolerance**
  (IMEPg Δ0.001, Pmax Δ0.002 bar, CA50 Δ0.11°). The 9049 heat-release / IMEP /
  CA50 code is proven against known truth. Recipe in
  **`docs/9049-openloop-audit.md` §7**.
- **Test suite: 191 green** (`pytest`; was 183 at this handoff's writing).
- **The frontier is now LabVIEW + hardware**, not Python. Python phases A/B are
  done and live-verified; the open work is thresholds → SIL-1 → bench →
  fire, plus a few real safety gaps below. *(⇒ see the Update blocks below:
  as of 2026-07-16 the thresholds + SIL-1 protection half are DONE.)*

---

## Update 2026-07-14 — SIL-1 bench started + tooling

- **SIL-1 begun on the real 9049 (EPT sim).** **Trig0 follows the sim — CONFIRMED
  (Step 2 closed):** CAS `rpm from DAQ` = the `SimPeriod` rpm set on TS10ms,
  `Graph time` delivers full 7200-sample cycles, DAQ error 0. ⇒ the
  CAS → analytics → `Pcyl_Diag` chain runs in sim mode on-target; **SIL-2's encoder
  is not needed for acquisition testing.** Resolved the audit §9 open question.
- **Click-level SOWs now exist:** `docs/sil0-scope-of-work.md` (thresholds/math) and
  `docs/sil1-scope-of-work.md` (sync → CAS → gating → drills → false-trip matrix),
  written against the real front panels (TS10ms `EPTControl`/`EPTData`, CAS `Graph time`,
  IGNDI `NumberOfActiveIGN_DI`).
- **Correction from the panels:** the 9049 crank is a **3600-line encoder** (54 kHz A
  @ 900 rpm, 108 kHz @ 1800), **not** a missing-tooth wheel; sync is Z-index + cam.
- **Tooling:** `tools/compare_hrl.py` is now **header-aware** — matches CSV columns by
  name, so one metrics file (with the added `mapo`/`imepstd` columns) feeds both
  `compare_hrl` and `tune_thresholds`; covered by `tests/test_compare_hrl.py`
  (**suite 180 green**). New `docs/crio-file-access.md` (WinSCP/PuTTY to the cRIO).
- **Flagged as NEW work (not built):** motoring-vs-fired warning-limit **profiles** —
  the 9049 has a single slot (`9049_WarningLevels` → one `CylWarningLevels.xml`, no state
  input). Needs a second profile + a state-driven selector. Backlog item in
  `docs/migration-seam.md` (3), detail in `docs/9049-openloop-audit.md` Step 3.

---

## Update 2026-07-15/16 — false-trip matrix COMPLETE + F3 dispositions

- **SIL-1 Step 6 false-trip/latch matrix COMPLETE 7/7** (2026-07-14): synthetic
  pressure fed through the real chain via the new CAS_loop sim branch
  (`SIM pressure?`, pattern **`cycle_????.csv`**); every warning/error tripped on
  exactly its target cylinders, latched, and cleared. Record sheet:
  `docs/cRIO9049 Warning Matrix.xlsx`. Tool: `tools/gen_warning_matrix.py`
  (7 sets + all-armed drill XML + manifest + `--xlsx`).
- **Four as-built defects found + dispositioned** (audit F3a–F3d): F3a non-finite
  CA50 noise trips → cured by sim pressure + the user-built **SYSTEMSTATE ≥ 2
  state gate** in `CombCluster2Array` (live-verified both directions); **F3b root
  cause: `Pcyl_Diag` "Load INI on startup" saved FALSE — thresholds NEVER loaded
  since the system was built** (fixed; carry into deployed builds; verify
  protections by probe, never the display); F3c display order verified correct
  (name-bound); **F3d: all three misfire checks are one-sided low-side** —
  misfire-from-IMEP INERT until `Expected IMEP` is wired from IMEP-REF (decision:
  no Abs; any `Pcyl_Diag` change ⇒ re-run the matrix as regression gate).
- **W2 settled by the matrix runs** (per-state arming observed live).
- **Steps 4–5 remain** — click-level SOW rewritten 2026-07-15/16
  (`docs/sil1-scope-of-work.md` 4a–4f, drills 5a–5i). ~~Pending architecture
  decision~~ → DECIDED 07-16: run both cRIOs (see next update block).
- Close-out still OWED on the bench: restore the **motoring**
  `CylWarningLevels.xml` (drill XML must never ride into a fueled run) +
  `SIM pressure? = FALSE`.

---

## Update 2026-07-16 (PM) — Step 4 bench day: 4a–4d PASSED, W5 refuted, loss-of-9056 gap

- **Architecture DECIDED: engine-only runs BOTH cRIOs** — dyno command (`DYNO-REF`) and
  all engine-health reads (oil/coolant/exhaust/torque/fuel) live on the 9056
  (`docs/engine-only-9056-tradeoff.md`).
- **SIL-1 4a–4d PASSED** over the real command path + Python CLI: state ladder (+1 per
  step up, instant down), **panel e-stop verified in PYTHON mode** (clamps −1), DI-module
  health (F9 CLOSED — `Fault1=126` was a stale saved panel; live = 0/0), gate LEDs, and
  `NumberOfActiveIGN_DI = 12` (⇒ **Key present**, spark edges scheduling). Counters
  surfaced into TS10ms via grown R/W Control node (rtexe now stale — rebuild). Next:
  4d.3 truth test (count=2), then 4e scope + SA/SOI sweep, 4f HMI sweep.
- **W5 REFUTED LIVE:** the warnings→state clamp IS consumed — a latched severity-3
  warning drove `warn_lim=1` and pinned the state at MOTORING in both modes until CLEAR
  WARNINGS. Diagnostic order now: `status`→`warn_lim` first; photograph UI_Errors before
  clearing (source of this trip was lost). Floating plant channels CAN clamp — manage
  9056 limits/masks every engine-only session.
- **Loss-of-9056 gap (new, `docs/command-path-asbuilt.md` §6a):** killing `APC_9056_RT`
  raises NOTHING — 9056-published SVs freeze, 9049 gate stays open on stale state ≥2.
  Build tasks: PC-computed watchdog LEDs on `UI_Main` (operator decision) + 9049-side
  staleness→−1 clamp on the state relay. Drill **5i** added.
- **CLI hardened** (`examples/monarch_operate.py`, 202 tests green): >+1 upward mode
  requests REFUSED with the step to request; `set` values validated against field types
  (a bad `set ign_enable FALSE` had poisoned the intent → infinite `parse`-NACK loop).
- Traps codified: FPGA-subVI panels show saved defaults (never read
  `FPGA_IGNDI_supervisor`'s panel); UI_Main watchdog LEDs are `9056_*`-prefixed 9056
  verdicts (no 9056-liveness LED). **Verify:** does gateway telemetry carry
  `operator_requests`? If absent, the safety-only mirror is inert (check
  `operate_traffic.jsonl`).

---

## What to do next (in order)

*(Items 1 and 3 below are DONE as of the 07-15/16 update above; item 2's matrix
half is done — Steps 4–5 remain. Kept for the historical record.)*

1. ~~**Set the motoring warning thresholds**~~ ✅ DONE (2026-07-14; and the real
   #1 risk turned out to be F3b — thresholds never loaded — see update above).
   (closes the #1 pre-fuel risk, 9049
   audit F3: `CylPressError` false-tripping and vetoing first fire).
   - Generate a motored set:
     `python tools/gen_cas_traces.py trace-sets/motored_set --cycles 30 --mode motored --bore 0.112 --stroke 0.149 --conrod 0.217 --cr 12.8 --pin-offset=-0.00099`
   - Run it through `APC_SIL0_HRL_Desktop.vi` → `trace-sets/motored_set/labview_metrics.csv`.
   - `python tools/tune_thresholds.py trace-sets/motored_set/labview_metrics.csv --mode motored --pmax-hard-limit <engine limit>`
     → recommended `MaxPCylMax` / `MaxIMEPstdError` / `MaxDevFromAvg` + the
     **disarm list** (`CA50max`, `MaxDevFromExpectedIMEP` — motored false-trippers).
   - Enter those into the 9049 warning XML via the UI CYLINDER (Errors) screen.
     Keep a **separate fired profile** (re-run with a `--mode fired` set).
2. **SIL-1 — virtual crankshaft.** ⇒ *Half done (see update above): Steps 0–3 +
   the Step-6 matrix are complete (sync, CAS, analytics, latch/veto, W2 settled);
   **Steps 4–5 remain** — `docs/sil1-scope-of-work.md` 4a–4f + drills 5a–5h.*
   On the real 9049, set `EPTControl.SimEnable`
   TRUE (`SimPeriod = 60·4e7/(rpm·3600)`) and watch the whole engine-sync stack
   run with no engine: sync, spark/DI scheduling, CAS acquisition, the analytics
   above, IGNDI supervisor, both watchdogs. Agenda: `docs/9049-openloop-audit.md`
   §7 SIL-1. **Pre-fuel checklist there is mandatory before any fueled step.**
3. ~~**Fix the broken 9049 combustion VIs**~~ ✅ RESOLVED — the chain runs on
   the 9049 again (the complete Step-6 matrix executed through
   `CombCluster2Array`/`PressureAnalytics`/`keyCA50`/`keyKnock`, incl. the new
   state gate). Residual: the F3c typedef-order alignment stays as rebuild debt.
   (Original issue: the SIL-0 trace-harness work left them non-executable via a
   **target-relative** `9049_Global_CylPressError` node; fix = keep those VIs
   under the **9049 target**; don't network-publish the safety globals.)

---

## Current status by phase (audited 2026-07-11)

| Phase | State | Notes |
|---|---|---|
| **A — Shadow brain** | ✅ COMPLETE | Live shadow-compare 100% across all 5 states + inputs. |
| **B — Command path + watchdog** | ✅ COMPLETE (exit-gate passed 2026-07-09) | Command path built **end-to-end** (gateway does the full validation ladder, not a stub — see robustness gaps). Loss-of-PC watchdog live-verified. |
| **C — Bench command** | Python built; **C3/C4/C5 unverified** | Needs bench time + a 2nd operator. Autonomous-deploy platform (was a soft blocker) is now ready. |
| **D — Sequencing** | Framework + sim + fault-tests built; **never bench-run** | Blocked on **D0 operating-procedure sheets (team)** — the single biggest missing spec. |
| **E — Commissioning/expansion** | Mechanics unit-tested | Blocked on TBD(team) rule/schedule values + live campaign. |

Cross-cutting done this session (not in the phase docs yet): autonomous
deployment (verified), 9049 open-loop audit (F1–F9 + pre-fuel checklist), SIL-0
validation.

---

## Robustness gaps for a production Python⇄LabVIEW system (address before firing-relevant authority)

The command path is genuinely built and its **machine-failure** modes are
live-verified (Python crash / freeze / TCP drop / malformed / flood → all
drove SAFE, 3× each). What's weak or missing:

   **Command-path architecture (confirmed 2026-07-11 from the PC-side exports):**
   - **UI write path:** `UI_System` (P&ID tabs) bundles operator inputs into the
     LabVIEW global `PC_GlobalVariables_PIDsyst2main`; **`UI_Main` reads that
     global, assembles the full command cluster** (EMERGENCY STOP, Requested
     mode, spark/DI advance+duration, Speed ref, IGN/DI enable, Activate
     cylinder, Force idling/motoring, PID refs) **and writes `PC_ControlSettings`.**
     `APC_PC_VariableMapping.vi` is the *telemetry* return (cRIO→PC cluster
     merge, "9056 prevails"), **not** the command writer — earlier note corrected.
   - **Gateway (`APC_PC_PythonGateway.vi`) — source-select IS real:** a
     `CommandSource_IsPython` SV gates every command; non-Python source →
     NACK `"source is UI"`. Accepted commands write `PC_ControlSettings` and get
     a `command_ack`. The telemetry frame emits `system_state, warnings_limit,
     manual_state, force_state, settings, limited_settings, command_source,
     operator_requests` (verified).

1. **`UI_HeartBeat` — specified but NOT yet built (the one uncovered dropout
   case).** *Resolved 2026-07-11 from the fresh `UI_Main` export + ICD §7.5:*
   the source-select and `PC_HB` handover work correctly and single-writer holds
   end-to-end — the open item is narrower than I'd written. As-built:
   - `UI_System` self-toggles `PC_HB`; `UI_Main` writes operator inputs to
     `PC_OperatorRequests` **always**, and — gated on `CommandSource_IsPython` —
     **promotes `PC_OperatorRequests` → `PC_ControlSettings` only in UI mode**
     (the B3.c redirect, now as-built; `PYTHON (effective)` LED + the
     `9056_PCnotResponding` reads are on the panel too). In PYTHON mode the UI
     does **not** promote; the gateway writes `PC_ControlSettings`. Clean
     single-writer, exactly per ICD §7.4.
   - `PC_HB` is by design sourced by whoever holds authority: **UI toggles it in
     UI mode, Python toggles it (via the gateway relay) in PYTHON mode** (ICD
     §7.5 option a). So `PC_HB` tracks the *command path*, not the UI.
   - **The genuine gap:** because `PC_HB` follows Python in PYTHON mode, it
     **cannot** detect the operator console (HMI holding the software e-stop +
     monitoring) dying while Python commands. ICD §7.5 already **specifies** the
     fix — a standalone `UI_HeartBeat` SV toggled by the UI loop regardless of
     source, watched as a 5th WatchDog channel — but it is **not implemented**.
     Build it before Python holds firing-relevant authority (response phase-in:
     alert + Python-side sequence-abort first, LabVIEW SAFE clamp value
     team-decided). *No re-print needed — this is a build task, not a discovery.*
   - **Loss-of-PC clamp confirmed armed in BOTH modes** (2026-07-11): `TS_loop`
     OR's `9056/9049/PCnotResponding` → `Select(−1 SAFE : 3 FIRING)` → SM
     warnings-limit, **no `CommandSource` gate**. So a frozen command path →
     SAFE in either mode. This does *not* close the `UI_HeartBeat` gap (a dead
     UI in PYTHON mode doesn't freeze `PC_HB`). **Full as-built with per-VI
     evidence: `docs/command-path-asbuilt.md`.** Owed: one hardware UI-mode
     `PC_HB`-freeze drill (logged drills cover only PYTHON-mode freeze).
2. **Thin gateway setpoint validation (confirmed from the gateway diagram).**
   The validation ladder range-checks **only `Speed ref` (0..3000)** — the NACK
   reasons are `rate / source is UI / parse / range: Speed ref / operator only`.
   DI duration, spark advance, and every PID ref pass through unrange-checked.
   The cRIO FLOOR must catch unsafe actuations — but widen the gateway range
   checks before firing-relevant authority.
3. **Unauthenticated TCP on :5020.** Any host on the network can inject
   commands. Single-writer (`CommandSource_IsPython` gateway NACK) + e-stop
   precedence mitigate, but there's no auth — fine for a bench, revisit for the
   plant network.
4. **Frozen-but-present telemetry has no content-staleness guard** (same class
   as 9049 audit F7): a 9056 that keeps publishing a stuck value would let the
   commander seed intent from stale data. Timestamp/counter staleness check
   wanted on the content, not just the connection.
5. **Command-effect is open-loop.** The commander emits and relies on the
   operator / `shadow_compare.py` (reverse-verify) rather than an inline "did my
   command take effect?" check against `limited_settings`/`system_state`.
6. **Drill evidence gap.** `migration-plan.md` claims "all nine B4 drills passed
   3×+ … log in docs/drill-logs/", but the folder holds **only B4-1..6**
   (machine-run). B4-7 (source flip), B4-8 (e-stop precedence — caught a real
   bug), B4-9 (stale telemetry) were operator-run and **not logged**. Formalize
   with logs — they're the actual Phase-B exit gate.

**Patterns done right (keep):** one-flag heartbeat supervising the whole PC→cRIO
chain; single-writer source-select (gateway-enforced NACK); telemetry-as-truth
(ack ≠ effect); reconnect-rebuild-from-telemetry (bumpless re-seed); pure-decision
state machines; belt-and-braces staleness (commander *and* engine drop); e-stop
set-only through Python (latch cleared operator-direct only); `safety_only` mirror
floor; NaN sanitization at the edge (LabVIEW Unflatten rejects the NaN literal —
real 2026-07-08 bench bug).

---

## VIs to export next (to complete the picture)

Print (LabVIEW → File → Print → HTML, or the export you've been using) and drop
under `original-labview-codebase/<name>/`.

**✅ DONE (printed + analyzed 2026-07-11)** — `CombCluster2Array`, `Pcyl_Diag`,
`LoadWarningConfig`, `PC_UI_System`, `TS10ms_loop`, `HRL`, `SIL0_HRL_Desktop`.
The threshold picture is now fully resolved: the confirmed field↔flag↔metric map
and the Warnings-vs-Errors **latch** split are in `docs/9049-openloop-audit.md`
F3; `tools/tune_thresholds.py` emits the exact 7-metric × {Warning,Error} set.

The whole PC-side command path is now resolved from in-repo exports
(2026-07-11): `VariableMapping` = telemetry-return (not the command writer); the
gateway = source-select + thin validation + telemetry contract; the fresh
`UI_Main` (re-printed 07-11) = the B3.c source-select redirect + `PC_HB`
handover, confirmed as-built per ICD §7.4/§7.5.

**✅ Second print batch DONE (delivered + analyzed 2026-07-14)** — the 9056 warning
chain (`ErrorMask`, `MaskErrors`, `MergeCylErrors`, `ClearSoftWarning`), PC
`ClearErrorButton`, `9049_checkAI`, `9049_CycleAvgSignals`, `9056_FPGA_main`.
Findings write-up: **`docs/9056-warning-policy-asbuilt.md`** — the Phase-A3
as-built reference (4-tier raster limits, per-state arming masks, latch/clear
semantics, cylinder error→"send to motoring" scoring, gaps W1–W7) plus the
**9056 FPGA RT-stall safe-hold confirmation** (both cRIOs now have verified
below-RT fallbacks). Note before citing a VI as live: check membership in
`MONARCH.lvproj`, not the disk listing — `TS100ms_loop`, `MODBUSTCP_HealingLoop`,
`HRLtest`, `SIL0_TraceHarness` are on-disk orphans.

**Still outstanding: one print** — `APC_9056_LoadINI.vi` (requested with the
batch, not delivered; wanted as the 9056 config-persistence pattern for the
second warning profile + load-fail default).

The remaining non-VI item:
- ~~**A MAPO/knock harness column**~~ ✅ DONE (2026-07-14) — the harness metrics
  file carries `mapo`/`imepstd` columns and both `compare_hrl.py` and
  `tune_thresholds.py` read them by header name.

Actual build tasks (not discoveries): implement `UI_HeartBeat` (ICD §7.5) and
widen gateway range validation — see robustness gaps #1–2.

---

## Tools built this session (`tools/`)

| Tool | What it does |
|---|---|
| `gen_cas_traces.py` | Synthetic CAS cycles: raw `cycle_NNNN.csv` (9×7200, full chain) + phased `cycle_NNNN_phased.csv` (6×7200, feed `APC_HRL` directly) + `truth.json`. Real MONARCH geometry via `--bore/--stroke/--conrod/--cr/--pin-offset`. Motored/fired/mixed, injectable misfire/knock; `--q-jitter` (cyclic variability) + continuous cyclic drift ramps (added 07-14/15). |
| `compare_hrl.py` | Scores the harness `labview_metrics.csv` vs `truth.json`; header-aware column matching (incl. `mapo`/`imepstd`); per-metric worst-Δ + pass/fail. |
| `tune_thresholds.py` | Reads a motored/fired `labview_metrics.csv` → recommended 9049 warning limits with margin + the disarm list. `--pmax-hard-limit` clamps to the physical ceiling. |
| `gen_warning_matrix.py` *(added 07-14)* | One command → the whole SIL-1 false-trip suite: 7 trace sets under `trace-sets/warning_matrix/`, the all-armed `CylWarningLevels.drill.xml`, expected-trip `manifest.md`/`.json` (one-sided-check-aware), `--xlsx` record sheet. |

LabVIEW harness: `APC_SIL0_HRL_Desktop.vi` (My Computer). Gotchas baked into the
recipe: `APC_HRL` has **no geometry input** (internal `VOL`) and runs its **own
per-cylinder loop** (outputs are 6-element arrays); **wire `exhaust pressure`**
(flat `Initialize Array(3.0,7200)`) or pegging → NaN; **Read Delimited delimiter
= comma** (defaults to tab); label columns cycle-first, cylinder second (+1).

---

## Two debugging lessons worth carrying (cost real time this session)

- **DSM shows a blank cell for array / "Advanced" shared variables — blank ≠
  empty.** A genuinely unwritten SV reads "(No Known Value)". We chased a
  phantom "empty MeasAndCalc" for hours; it was a full array DSM couldn't render.
- **A subVI's front panel shows stale *default* values while the real data flows
  through its wires.** Trust the caller's indicators or a probe, never the subVI
  panel. This is what made "generic config in the EXE" look real when it wasn't.
- **When a cRIO app "won't come up," pull its RT log over SSH first:**
  `ssh admin@<ip>` → `/var/local/natinst/log/` → `cat errlog.txt / lvrt_*_cur.txt`.
  One real error message (the `DAbort` FPDCO crash, the `-200088` DAQ error)
  ended hours of black-box guessing.

---

## Needs from the team (blocking markers)

- **Operating-procedure sheets** (D0) — cold-start / purge / motoring→light-off /
  shutdown / vent+recovery / misfire recovery. The single biggest missing spec;
  even informal notes suffice.
- **Real 9049 sensor calibrations** (cylinder-pressure channels are NI-example
  placeholders — 9049 audit F2).
- **Engine physical max cylinder pressure** — the hard over-pressure trip ceiling.
- **Bench + a second operator** for the C3 command-authority handover rehearsal.
- Confirm a couple of as-built items from the audit: `9049_ControlSettings` echo
  semantics (live capture), and the `SimEnable`/`Override PC settings`/`Enque?`
  saved defaults on the deployed builds (pre-fuel checklist).
