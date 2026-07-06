# MONARCH LabVIEW → Python — Migration Seam & Port Backlog

Where to draw the boundary between what stays in LabVIEW/cRIO/FPGA and what moves to
Python, and in what order to port. Derived from the `MONARCH.lvproj` target map, the
shared-variable libraries, and the exported documentation (`APC Control System - LV
MONARCH Overview.pdf`, the FPGA design decks, and the SCADA/logging/report `.docx`
set under `original-labview-codebase/`). Where the sources are silent or a TODO, this
doc says so explicitly.

## The one invariant (and why it already holds in hardware)

Hard real-time and safety stay on the cRIO/FPGA; a dead/absent Python side must equal a
safe hold. This is **already enforced in hardware**: the 9049 FPGA runs a **watchdog
(`WatchdogIn`) that the RT loop must toggle > 4 Hz**, whose stated job is to *shut down
engine position tracking and all engine-synchronous outputs on loss of LabVIEW-RT
communication*. If the layer feeding the FPGA stalls, spark and injection stop on their
own. Giving Python supervisory authority is therefore structurally safe **provided
Python sits above the RT watchdog-toggle loop and never becomes responsible for petting
that watchdog.** Safe-state limiting (feeds closed, vents open, cooling max, dyno
stopped, IGN/DI off) is likewise enforced on the cRIOs (the 9056 StateMachine), not the
PC.

## Architecture (4 targets)

| Target | Top VI | Role |
|---|---|---|
| **PC (Windows)** | `APC_PC_UI_Main` | Thin HMI/SCADA over shared variables + Modbus master to the MTR membrane PLC. **Almost no control logic.** |
| **cRIO-9049** (FPGA+RT) | `APC_9049_RT_main` → `APC_9049_FPGA_main` | Engine-synchronous: encoder→crank-angle, spark & DI timing, cylinder-pressure/combustion analysis. |
| **cRIO-9056** (FPGA+RT) | `APC_9056_RT_main` | Plant: gas (NG/Ar/O2), thermal HX, vents, dyno, membrane — **and the supervisory StateMachine**. |
| **MTR PLC** | external | CO2/membrane gas-separation skid; own state machine + heartbeat, over Modbus TCP. |

Command path today: operator → PC writes `PC_ControlSettings` → **9056 StateMachine**
limits it to `Limited_ControlSettings` + sets `SYSTEM STATE` → 9056 controllers and 9049
consume it; 9049 publishes `9049_ControlSettings` back.

## The seam

**FLOOR — stays in LabVIEW/cRIO/FPGA (hard real-time, safety, or data-local):**
- **9049 FPGA:** engine position tracking (encoder→CAD @ 40 MHz), spark & DI pulse
  generation, encoder deglitch, crank-synchronous DAQ triggers, the **watchdog** and
  **sync-loss latching**, the on-FPGA IGN/DI supervisor + `Key` unlock.
- **9049 RT:** cylinder-pressure DAQ + combustion analysis (HRL/IMEP/CA50/MAPO/MFB) —
  per-cycle (7200 samples/cycle, ~67 ms at 1800 rpm), data-heavy, stays for locality;
  the **hard spark/DI enable gate** `(SYSTEMSTATE ≥ 2) ∧ ¬CylPressError ∧ Activate ∧ Enable`.
- **Everywhere:** DAQ config, valve/mA drivers, sensor calibration, Modbus I/O, heartbeats.

**MIDDLE — RT loop stays; Python supplies setpoint + mode:**
- 9056 control loops, each with a **3-mode pattern (0 = safe/bypassed, 1 = manual
  setpoint, 2 = closed-loop):** O2 (on concentration), NG (on lambda), Ar (on system
  pressure), coolant/exhaust/oil thermal HX (cascade PIDs), dyno/speed, membrane skid.
  The **PID execution stays real-time on the cRIO**; the mode and setpoint are the Python
  hand-off. Thermal loops fail to **max cooling** in SAFE.
- Knock/CA50 spark-trim PID (currently disabled): enable + CA50 setpoint from Python,
  PID stays on 9049.
- Spark/DI **timing setpoints** (spark advance, dwell, DI advance/duration/window):
  decided above, converted to crank-angle ticks and executed by RT/FPGA.

**BRAIN — Python port targets (supervisory, slow, testable):**
- **9056 StateMachine** — mode arbitration + the per-state max-level-of-control limit
  table + the transition rules. Fully specified (see below). *The first port.*
- **Warning/diagnostic → state policy** — thresholds/levels (editable, INI-persisted),
  the warning→max-state clamp, the severity→reaction map (yellow = self-clearing info,
  **orange → idle, red → motoring, black → emergency stop & vent**), and the
  **temporal rules the author flagged as not-yet-built** (e.g. "oil pressure low > X s").
- **Run sequencing / recipes** — cranking/start, purge, motoring→firing light-off,
  venting + recovery-from-venting, misfire recovery, working-fluid quality check.
  **These are named in the docs as still-to-build research goals — they do not exist in
  LabVIEW.** Greenfield: author in Python, testable from day one.
- **Setpoint scheduling** — choosing the 3-mode + setpoints for the MIDDLE loops as a
  function of state and operator intent. PC request conditioning and MTR commanding.

## Contracts Python must honor byte-for-byte

- **`PC_ControlSettings`** — the operator→cRIO command cluster. **Already modeled and
  confirmed** against a live capture (`supervisory/monarch/control_settings.py`,
  `docs/monarch-control-settings.md`).
- **`Limited_ControlSettings`** — the StateMachine output; same shape as
  `PC_ControlSettings`, clamped. (The optional `limited_settings` telemetry field.)
- **`9049_ControlSettings`** — the 9049 command subset (STATE, InjectionEnable,
  Main{Enable/Duration/SOI}, SparkEnable, SparkTiming, Speed). **Not yet modeled.**

## StateMachine transition rules (consolidated spec)

Inputs: `CURRENT SYSTEM STATE`, `STATE LIMITATION FROM WARNINGS`, `PC_ControlSettings`,
`ForceState`, `ManualState`. Outputs: `SYSTEM STATE`, `Limited_ControlSettings`.
States: −1 SAFE, 0 STAND_BY, 1 MOTORING, 2 IDLING, 3 FIRING.

- `SYSTEM STATE` = the **min** of {requested mode, warning-permitted max state, and the
  discrete-override limits}, then **clamped so it can only increase by 1 per step**.
- Discrete overrides (from `PC_ControlSettings`): **Force idling → ≤ 2**, **Force
  motoring → ≤ 1**, **EMERGENCY STOP → −1**.
- If `ForceState` = TRUE, `SYSTEM STATE` is overridden to `ManualState`.
- `Limited_ControlSettings` = each controller clamped to its per-state max level (the
  MAX-LEVEL-OF-CONTROL table, identical across StateMachine versions). Levels: 0 = safe,
  1 = open-loop/alternate, 2 = closed-loop; vents 1 = closed / 0 = open.
- Hard sequencing invariant (from the report): **discontinuing combustion must also cut
  NG and O2 feeds.**

Port the current `APC_9056_StateMachine.vi` (2026); `_v2` is an older 2024 draft.

## The safety gap to close before Python-in-command

The docs describe a watchdog on FPGA IGN/DI and an MTR heartbeat, but **do not document
any watchdog on `PC_ControlSettings` / loss-of-PC.** Whether a stale or absent
supervisor command auto-decays the cRIO to SAFE is **unspecified**. This is the top
safety question to resolve: a cRIO-side **stale-command → SAFE watchdog** (analogous to
the FPGA's) must exist before Python holds command authority (vs. read-only shadow).
The `9049_HeartBeat` / `9056_HeartBeat` shared variables exist but it's unconfirmed they
gate `PC_ControlSettings` staleness.

## Prioritized port backlog

1. **StateMachine** (in progress) — fully specified, self-contained, foundational; port
   + exhaustive unit tests. Validates the whole toolchain.
2. **Command path + stale-command watchdog** (prerequisite for any authority) — build the
   Python→LabVIEW command channel with ACK/NACK validation (telemetry/read is done), and
   resolve/implement the cRIO-side stale-`PC_ControlSettings`→SAFE watchdog.
3. **Warning/diagnostic → state policy** — port the thresholds + warning→max-state clamp
   + severity→reaction map, and **author the temporal rules** the original dev left
   unbuilt. Pairs with (1): it produces `STATE LIMITATION FROM WARNINGS`.
4. **Run sequencing / recipes (greenfield, highest operational value)** — cranking,
   purge, light-off, venting + recovery, misfire recovery, WF quality check. Needs an
   operating-procedure **spec from the team** (not in the code/docs). Build in Python,
   test-first.
5. **Setpoint scheduling / control-mode selection** — the "what targets, which mode"
   layer above the 9056 MIDDLE loops.

## Open questions to source from the team

- **Operating procedures / sequences** — the single biggest missing spec. The docs
  encode modes and a limit table but **no scripted PURGE / start / light-off / abort
  sequences**. These must be authored (they were never built).
- **Loss-of-PC behavior** — is there (or should there be) a cRIO-side stale-command→SAFE
  watchdog? (See the safety gap above.)
- **9056 loop rates** — undocumented except the membrane skid (200 ms).
- **As-built vs docs** — the overview flags developer TODOs (stroke-volume calc, a
  project/diagram mismatch), so treat the docs as intent, not ground truth; confirm
  against the VIs when porting each piece.
