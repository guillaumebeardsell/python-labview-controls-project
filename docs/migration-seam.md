# MONARCH LabVIEW → Python — Migration Seam & Port Backlog

Where to draw the boundary between what stays in LabVIEW/cRIO/FPGA and what moves to
Python, and in what order to port. Derived from the `MONARCH.lvproj` target map, the
shared-variable libraries, and the exported documentation (`APC Control System - LV
MONARCH Overview.pdf`, the FPGA design decks, and the SCADA/logging/report `.docx`
set under `original-labview-codebase/`). Where the sources are silent or a TODO, this
doc says so explicitly.

**This is the analysis document.** The executable sequence — phases A–E with authority
gates, exit criteria, and **current project status** — is `docs/migration-plan.md`;
the backlog at the bottom of this doc maps 1:1 onto its phases.

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

**Confirmed on the 9056 too (2026-07-14, from the `APC_9056_FPGA_main` print):** the 9056
FPGA runs its own RT-stall watchdog — an `RT watchdog` boolean the RT side must keep
toggling, checked on a 10 ms clock; on counter overflow (`Counter max` default 100 ⇒ 1 s)
it forces **all analog outs to 0 and all digital outs FALSE** ("SAFE state is applied if
RT watchdog is not alive"). So the plant/gas side has a below-RT hardware fallback
symmetric to the 9049's spark/DI kill; **both cRIOs safe-hold if their RT loop dies.**
Caveats: the RT-configured `Counter max` on the deployed build is unconfirmed, and
AO=0/DO=FALSE is safe only because actuators are fail-safe de-energized (vents 0=open).
Details in `docs/9056-warning-policy-asbuilt.md` (side findings).

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
  `PC_ControlSettings`, clamped. Python decodes it already (the optional
  `limited_settings` telemetry field); the gateway pre-wire is Phase A2.
- **`9049_ControlSettings`** — the 9049 command subset (STATE, InjectionEnable,
  Main{Enable/Duration/SOI}, SparkEnable, SparkTiming, Speed). **Not yet modeled**
  (needed by Phase C at the latest).

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

## The safety gap — loss-of-PC watchdog — **CLOSED (2026-07-07, live-verified)**

> **As-built resolution:** the WatchDog VI was refreshed (four stall counters,
> threshold controls, an `Iteration Time [ms]` indicator) and wired at the
> `TS_loop` call site: **`PCnotResponding` OR `9049notResponding` → Select
> (−1 : 3) → Min into the StateMachine's `STATE LIMITATION FROM WARNINGS`
> input** (MTR flag = indicator/alert only, per review). The UI toggles `PC_HB`
> (feedback-node → NOT in `APC_PC_UI_System.vi`, relayed through the PID-refs
> global and `UI_Main` — the heartbeat supervises the whole UI app), so the
> clamp arms ungated in both command modes. **Live-verified:** a real PC drop
> drove `warnings_limit → −1` and `SYSTEM STATE → SAFE`, with step-by-1
> recovery on return; `tools/shadow_compare.py` agreed **100%/100%** across the
> whole episode. The text below is kept as the historical finding.
>
> **Threshold sizing (2026-07-07).** The threshold is a **count of ~20 ms control-loop
> ticks** while the heartbeat is unchanged, so trip time = `count × 20 ms`. It must be
> **several heartbeat periods**, and the binding heartbeat is `PC_HB` at **~1 Hz** in
> both modes (Python Supervisor 1 Hz; UI toggle ~1 Hz) — i.e. one heartbeat period ≈ 50
> ticks. The agreed **5 s = 250 counts** (5 missed beats of margin). **Do not set 50
> counts (=1 s ≈ one heartbeat period): it false-trips to SAFE on normal jitter.** A
> faster clamp (e.g. 1 s / 50 counts) is only safe if `PC_HB` is first sped up to ≥5 Hz
> in *both* command modes. The threshold is bound by the slow 1 Hz heartbeat, not the
> fast 20 ms loop (the loop only sets detection *granularity*).

`APC_9056_WatchDog.vi` (2025-12-18) **does monitor loss-of-PC.** It watches four
heartbeats — `9056_HeartBeat`, `9049_HeartBeat`, and `PC_HB` + `MTR_HB` carried inside
`PC_ControlSettings` — each with a stall counter that increments while the heartbeat
value is unchanged and trips a `*notResponding` flag once the counter passes a
configurable threshold. So **`PCnotResponding` exists** on the 9056 RT.

**The response does not exist — confirmed from the `APC_9056_TS_loop.vi` export
(2026-07-06).** The WatchDog subVI sits on the TS_loop diagram **completely unwired**
(no inputs, no outputs): it executes each iteration (it reads the heartbeats via shared
variables internally) but its `*notResponding` flags are consumed by **nothing** — no
state clamp, no warning, not even a caller-level indicator. Two aggravating details:
its front-panel `*watchdogThreshold` defaults are 0 (actual configured values unknown —
possibly never set), and it is **unknown whether anything toggles `PC_HB` today** (if
the UI never toggles it, `PCnotResponding` would read permanently tripped — a plausible
reason the outputs were left dangling).

**Cadence (2026-07-07, corrected — confirmed with the user):** the WatchDog subVI is in
the fast control loop (StateMachine + limiter + actuator refs), which is **paced by the
NI9205 DAQmx block read** (`Analog 2D DBL NChan NSamp`, 20 samples/read) → **~20 ms per
iteration, ~50 Hz**. So the watchdog is evaluated ~50×/s. *(The `1000` `Wait Until Next
ms Multiple` elsewhere in the VI belongs to a separate, slower housekeeping/streaming
loop — TS_loop runs ~5 parallel loops — not the control loop.)* **Design implications:**
(1) a wired B0 loss-of-PC response reacts in ~20 ms granularity — far inside the 5 s
safe-hold budget; thresholds count in ~20 ms ticks, not seconds. (2) The 1 Hz telemetry
cadence is purely the **PC gateway's** sample rate; the 9056 decision loop underneath
runs ~50× faster. (3) Because ~50 SM ticks occur between two 1 Hz telemetry samples, the
state has **converged** by each sample — see the shadow-compare convergence caveat in
`docs/shadow-findings.md` (the 1-per-tick step-up rate limit is not observable at 1 Hz).

**Consequence:** building the loss-of-PC response is Phase B0 work (Case 2 in
`docs/phases/phase-b-command-path.md`): wire `PCnotResponding` → (Select −1 : 3) →
`Min` with the warning-integration output feeding the StateMachine's
`STATE LIMITATION FROM WARNINGS` input, pick real thresholds, and define who toggles
`PC_HB` per command source. The TS_loop diagram shows exactly where it plugs in (the
DIAG VI's output into the StateMachine call).

**Python requirement either way:** `PC_HB` is a boolean field inside `PC_ControlSettings`
(modeled as `pid_control_references.pc_hb`). The watchdog trips when it stops *changing*,
so whatever sends the settings must **toggle `pc_hb` every cycle** to keep the 9056 from
flagging the supervisor as dead. This is a concrete, testable requirement for the command
path.

## Prioritized port backlog (→ phases in `docs/migration-plan.md`)

1. **StateMachine** → **Phase A1** *(next up)* — fully specified, self-contained,
   foundational; port + exhaustive unit tests. Validates the whole toolchain.
2. **Command path + stale-command watchdog** → **Phase B** (prerequisite for any
   authority) — build the Python→LabVIEW command channel with ACK/NACK validation
   (telemetry/read is **done and live**), and confirm/implement the cRIO-side response
   to `PCnotResponding` (detection already exists — see the watchdog section above).
3. **Warning/diagnostic → state policy** → **Phase A3** — port the thresholds +
   warning→max-state clamp + severity→reaction map, and **author the temporal rules**
   the original dev left unbuilt. Pairs with (1): it produces
   `STATE LIMITATION FROM WARNINGS`.
   - **As-built ground truth now documented (2026-07-14):** the full 9056 chain
     (WarningIntegration's 4-tier × 16-slot × 5-raster limits, per-state arming masks,
     max-latch + soft/master clear, cylinder W→1/E→3 scoring, severity→state map) is in
     **`docs/9056-warning-policy-asbuilt.md`**, incl. the W1–W7 gap list (per-cylinder
     state-arming table likely inert, no temporal rules, clamp output still unwired).
   - **Motoring vs fired warning-limit profiles (NEW — not in the as-built).** Today the
     9049 has a *single* limit set (`9049_WarningLevels` → one hardcoded `CylWarningLevels.xml`,
     no state input; the UI edits one slot). Motoring and firing need different thresholds and
     different *armed* diagnostics (CA50/MAPO/DevFromExpectedIMEP disarmed for motoring). Needs
     a second persisted profile **and** a state-driven selector that swaps the active limits at
     the MOTORING↔FIRING transition, with a cRIO-side fail-safe default (load-fail ⇒ tighter
     set / safe-hold). Profile *selection* is BRAIN/Python scope; profile *load + enforcement*
     stay on the 9049. See `docs/9049-openloop-audit.md` Step 3.
   - **F3d follow-ups for any 9049 warning-chain port (decided 2026-07-15):** the three
     misfire checks are ONE-SIDED low-side (no Abs — keep it that way); `Expected IMEP`
     must be wired from the commanded `IMEP-REF` (as-built it's an unwired 0 ⇒ the check
     is INERT); the 9049 now state-gates late-combustion + misfire-from-IMEP on
     `SYSTEMSTATE ≥ 2` (built + live-verified). Any change to `Pcyl_Diag` ⇒ re-run the
     false-trip matrix (`tools/gen_warning_matrix.py`) as the regression gate. Note the
     Python port `supervisory/monarch/warning_policy.py` still lacks per-state arming
     (gap documented in its docstring).
4. **Run sequencing / recipes** → **Phase D** (greenfield, highest operational value) —
   cranking, purge, light-off, venting + recovery, misfire recovery, WF quality check.
   Needs an operating-procedure **spec from the team** (not in the code/docs). Build in
   Python, test-first.
5. **Setpoint scheduling / control-mode selection** → **Phase E** — the "what targets,
   which mode" layer above the 9056 MIDDLE loops.

## Open questions to source from the team

- **Operating procedures / sequences** — the single biggest missing spec. The docs
  encode modes and a limit table but **no scripted PURGE / start / light-off / abort
  sequences**. These must be authored (they were never built).
- ~~Loss-of-PC response~~ **answered (2026-07-06): none exists** — the WatchDog call in
  `TS_loop` is unwired. Building the response is Phase B0 (see the safety-gap section).
  Open sub-questions: the real `*watchdogThreshold` values, and who toggles `PC_HB` today.
- **9056 loop rates** — undocumented except the membrane skid (200 ms).
- **As-built vs docs** — the overview flags developer TODOs (stroke-volume calc, a
  project/diagram mismatch), so treat the docs as intent, not ground truth; confirm
  against the VIs when porting each piece.
