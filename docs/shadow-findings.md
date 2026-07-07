# Shadow-Compare Findings Log

Dispositions for divergences reported by `tools/shadow_compare.py` (Phase A2).
A divergence is a finding, not automatically a Python bug — the LabVIEW logic is
unvalidated. Every entry needs a disposition before Phase A's exit gate.

## 2026-07-06 — first replay of `monarch.jsonl` (347 frames, 7 sessions)

**Result: 291/340 agree (85.6%).** Per-session:

| Session | Kind | Agreement | Disposition |
|---|---|---|---|
| 1 (248 frames) | sim gateway | **247/247 (100%)** | Port reproduces the sim's state walk exactly. |
| 2–5 (28 frames) | real gateway, Part A/B bring-up | 12/24 | **Not StateMachine output** — `system_state` was the hand-set shared variable (user set 3/FIRING manually while `requested_mode` sat at 0). Divergences expected; no port defect. |
| 6–7 (71 frames) | real gateway, live Part B | 32/69 | Same: `requested_mode` toggled 0→1 in the UI but `system_state` stayed 0 — the 9056 StateMachine was **not running/wired to the shared variable** during these captures. Divergences expected; no port defect. |

**Net:** zero divergences attributable to the port. The real-session divergences
carry a useful lesson for Phase A's exit: **bench sweeps only count as
shadow-compare evidence when the 9056 StateMachine is actually running and
writing the `SystemState` shared variable.** Until then, real-gateway captures
validate the pipeline, not the state logic.

Also noted in these captures: coverage is reduced (shadow extras not yet
pre-wired), so warnings/force/manual inputs are assumed inactive.

## 2026-07-07 — ForceState/ManualState experiment: resolved (telemetry state source)

Bench experiment: `ForceState=TRUE`, `ManualState` walked 0→1→2. Telemetry
`system_state` stayed 0 while LabVIEW's `limited_settings` enabled IGN/DI (a
state≥2 row) — the two outputs looked internally inconsistent.

**Resolution (user):** telemetry's `system_state` is sourced from
**`9049_Global_SYSTEMSTATE`, written by `APC_9049_CAS_loop.vi`** — a 9049-side
*echo* of the state — and the 9049 loops weren't running, so it sat frozen at 0.
`limited_settings` is tapped directly at the 9056 StateMachine, and it followed
the override. Conclusions:

- **The SM honors ForceState→ManualState absolutely — the A1 port reading and
  code are correct.** The state "divergences" in this session were a telemetry-
  source artifact, not logic disagreement.
- **Action (LabVIEW):** re-tap telemetry `system_state` to the **9056
  StateMachine's `SYSTEM STATE` output** at the TS_loop call site (same place as
  the `limited_settings`/warnings taps) so all compared fields are same-source
  and same-tick. This also removes any 9049 dependency from Phase-A testing.
- **Team finding — state-echo skew:** the 9049's state copy (used in its local
  spark/DI enable gate, `SYSTEMSTATE ≥ 2`) can diverge from the SM's actual
  state when the relay chain (CAS_loop polling) is stale or down. Observed skew
  here was fail-safe (low copy blocks actuation), and the SM's limited enables
  provide a second gate — but consider a relay-staleness check during
  commissioning (e.g. publish both SM state and 9049 echo and alarm on
  sustained mismatch).

## 2026-07-07 — PHASE A COVERAGE COMPLETE: all 5 states, all inputs

Warning cleared (`warnings_limit` 1→3 at seq 86), then a 210-frame full-envelope
walk reached **every state {−1, 0, 1, 2, 3}** via BOTH paths: requested-mode
(seq 175–181 walked 1→2→3 to FIRING) and force-override (seq 41–43, ManualState
1→2→3). E-stop press→SAFE and release→recover. Warning clamp exercised at both
1 and 3.

**SYSTEM STATE: 208/209 (99.5%) · Limited_ControlSettings: 209/209 (100%).**

The single state miss (**seq 189**) is the two-snapshot skew landing on the
e-stop press, proven frame-by-frame:

| seq | input estop | LabVIEW *output* estop | published state |
|----|----|----|----|
| 188 | False | False | 0 |
| 189 | **True** | **False** | **0** |
| 190 | True | True | −1 |

LabVIEW is internally consistent — its output-cluster e-stop predicts its state
exactly (False→0, True→−1) — but the gateway's `PC_ControlSettings` *input*
flatten ran one sample ahead of the StateMachine's consumption, so the port
(which derives from the input cluster) predicted −1 one frame early. They agree
at seq 190. **Not a port defect — a gateway snapshot-coherency artifact**, now
demonstrated on the safety-critical e-stop. Echoed `emergency_stop` added to
`IGNORED_LEAVES` (the state check already validates e-stop).

**Disposition: Phase A logic validation is COMPLETE.** The port reproduces the
LabVIEW StateMachine across the full input space and all five states; the sole
residual is a one-frame telemetry-timing artifact with a fully-understood cause.

**Motivates the Phase-B coherent-snapshot publish:** this is the *second*
manifestation of the input/output flatten skew (first on limiter fields, now on
a state transition). Publishing `current_state` + the SM's actually-consumed
inputs in one coherent snapshot makes the comparison immune to it — recommended
before command timing matters in Phase B.

## 2026-07-07 — requested-mode walk + e-stop = 100%/100% (clamped at MOTORING)

52-frame session: requested_mode walked −1↔0↔1↔2 and an EMERGENCY STOP press
(seq 39, `state → −1`). **SYSTEM STATE 51/51 (100%) · Limited 51/51 (100%) · AGREE.**

**Operator note — couldn't get past MOTORING (1):** the whole session ran with
`warnings_limit = 1` (a latched level-3 warning), so `state = min(requested,
1, …)`. Requesting mode 2 (seq 15, 23) correctly clamped to 1 — **the warning
clamp working, not a fault**, and the port predicted the same clamp on every
frame. To reach IDLING(2)/FIRING(3) the latched warning must be cleared first
(Errors screen: widen the tripped channel's threshold or operator-clear), then
re-walk. Until then states 2 and 3 are **not yet covered** by shadow evidence.

**e-stop covered:** press → SAFE(−1), release → returns to the requested level;
port agrees. Step-up-by-one confirmed (0→1 one step per tick).

One transient limiter diff (seq 23) was the echoed `requested_mode` lagging one
frame at a 1→2 step-change — the same input/output snapshot skew as the
heartbeats and `wf_oa_002_ref`; added to `IGNORED_LEAVES`. All four exclusions
share one root cause (the two clusters flattened at different instants); the
clean permanent fix is a single coherent gateway snapshot.

## 2026-07-07 — MILESTONE: ForceState/ManualState override sweep = 100%/100%

After the `system_state` re-tap (now the 9056 SM's fresh output, before the
feedback node), a 137-frame session swept the override live: `ForceState=TRUE`
with `ManualState` walked through **2, 1, 0, −1** (every state incl. SAFE), then
`ForceState=FALSE` with `ManualState=2` (correctly **ignored** — state stayed 0).

**SYSTEM STATE: 136/136 (100%) · Limited_ControlSettings: 136/136 (100%) · AGREE**

This validates against live hardware the port's most safety-relevant, previously
unverifiable behavior: the **absolute ForceState override** — state follows
ManualState when force is on, and ManualState is inert when force is off. (This
is the exact experiment that "diverged" on 2026-07-07 when state was tapped from
the stale 9049 echo; the re-tap resolved it.)

Limiter divergences before the fix were all **one field**,
`pid_control_references.ng.wf_oa_002_ref`: a live-jittering O2-analyzer
reference the limiter **passes through**. LabVIEW flattens the input
(`PC_ControlSettings`) and output (`Limited_ControlSettings`) clusters a sample
apart, so a moving passthrough value differs between them — proven: when the
field holds still, in==out to the last digit; on the 19/137 moving frames,
LabVIEW's frame-N output equals its frame-N+1 input. Same class as the
`pc_hb`/`mtr_hb` heartbeat skew. **Disposition: not a port bug, not a limiter
disagreement** — added to `IGNORED_LEAVES` in `shadow_compare.py` with a test.
The real fix (optional) is LabVIEW flattening both clusters from one loop
iteration; until then the diff is limited to actual clamp decisions.

## 2026-07-07 — MILESTONE: first full-envelope live session = 100% agreement

With the complete A2.1 pre-wire live (WarningIntegration → StateMachine wire made;
`warnings_limit` / `manual_state` / `force_state` / `limited_settings` all in the
envelope; the force_state Select fixed), the newest session compares:

**SYSTEM STATE: 81/81 (100%) · Limited_ControlSettings: 81/81 (100%) · AGREE**

- The full input set was live, including a real warnings clamp
  (`warnings_limit = 1` — some channel is latched at level 3 with the plant cold,
  capping the state at MOTORING; identify/clear it before mode-walk sweeps).
- Two comparator artifacts were fixed to get a clean read (not LabVIEW/port
  disagreements): NaN==NaN now compares equal (LabVIEW emits NaN for some live
  refs, e.g. `WF-OA-002-REF`), and the `pc_hb`/`mtr_hb` heartbeat bits are
  excluded from the limiter diff (they toggle between LabVIEW's two cluster
  flattens — liveness bits, not limited fields).
- Remaining for Phase A exit: bench input sweeps (mode walk, forces, e-stop,
  warning provocation/clear) — agreement must hold across the swept space.

## 2026-07-07 — second replay, now with `limited_settings` (360 frames)

Ran `tools/shadow_compare.py monarch.jsonl` on a fresh recording that includes the
`limited_settings` envelope field. **SYSTEM STATE: 303/352 (86.1%)** — same
disposition as the first replay (real-session divergences are captures where the
9056 StateMachine wasn't driving `system_state`). **Limited_ControlSettings: 0/13**,
and the diagnosis is definitive:

- LabVIEW's published `Limited_ControlSettings` is the **unwritten shared-variable
  default** in all 13 frames: `activate_cylinder = []` (empty), `speed_ref = 0`,
  `ca50_setpoint = 0`, `mtr_modbus_* = []`. The real limiter only clamps the
  mode/enable/vent fields and passes scalars + arrays through (the port does:
  speed 900, activate_cylinder 6-elem, ca50 22.6). An **empty** array is the
  signature of a cluster shared variable that was created but never written.
- **Port not at fault.** The harness correctly flagged that LabVIEW's limited
  output isn't reaching telemetry.
- **Action (LabVIEW):** at the `TS_loop` StateMachine call site, confirm the
  StateMachine's `Limited_ControlSettings` **output** terminal wires to the new
  shared variable (not a default constant), and that the 9056 supervisory loop
  is actually running during the capture. Then the limiter comparison becomes
  meaningful — and should agree with the port.
- Also observed: `warnings_limit` / `manual_state` / `force_state` /
  `command_source` still parse as `None` in these frames — only `limited_settings`
  was added to the envelope so far; the other three A2.1 fields aren't wired yet.

## `ForceState` / `ManualState` are unbound dev controls (2026-07-07)

Where they're defined/changed: **front-panel controls on `APC_9056_TS_loop.vi`**
(`ForceState` = Boolean, `ManualState` = I8), wired directly into the
StateMachine. They are **not** shared/global variables (a project-wide search
confirms none exist — shared-var names like `PostMortemSave`/`9056_HeartBeat`
grep fine; these return nothing) and **not** in `PC_ControlSettings` (that
carries Force idling/motoring + Requested mode, a different mechanism). Nothing
on the diagram feeds them.

Consequence: `TS_loop` runs **headless on the cRIO-9056** (RT target, no runtime
front panel), so these controls hold their compiled defaults forever —
`ForceState = False`, `ManualState = 0`. The absolute manual-override path
(`ForceState → SYSTEM STATE = ManualState`) is therefore **inert as-built** —
likely leftover developer/debug controls. Fifth instance of the provisioned-but-
not-driven pattern.

- **For A2.1:** `ForceState_SM` / `ManualState_SM` telemetry will read `false`/`0`
  — correct (that's what the StateMachine receives), and shadow mode's
  `force_state=False` assumption is validated.
- **If a real operator override is wanted:** create `ForceState`/`ManualState`
  network shared variables, have the PC UI write them, and feed the *same*
  variables to both the StateMachine inputs and telemetry (one source). Or —
  cleaner long-term — let Python own the override once it holds authority
  (`decide_state` already implements it).

## Open question — is `STATE LIMITATION FROM WARNINGS` actually wired? (2026-07-07)

Raised by the user: the StateMachine's `STATE LIMITATION FROM WARNINGS` may be
running on its **front-panel default** rather than a live `WarningIntegration`
output — which, given the WatchDog/heartbeat precedents, is plausible. It is a
**subVI input terminal**, so the answer lives at the caller (`APC_9056_TS_loop`),
not inside the StateMachine. From the TS_loop export the StateMachine has several
inputs wired and a `DIAG` VI adjacent that appears to feed it, so it looks
*plausibly* wired — but the specific terminal can't be resolved from the export.

- **Confirmed disconnected (2026-07-07, user):** the input is not wired to
  `WarningIntegration` — it runs on the front-panel default, so the warning→state
  clamp is inert. **Resolution: wire it** (`WarningIntegration` output → the
  StateMachine input, in `TS_loop`) — a real safety improvement that belongs in
  LabVIEW and survives into the target architecture as the independent clamp.
  Once wired, telemetry needs only one `warnings_limit` variable. Behavior note:
  active warnings will then actually clamp the state. **Step-by-step wiring recipe:
  `docs/phases/phase-a-shadow-brain.md` A2.1 step 0** (incl. the forward note to
  combine this with the B0 / heartbeat clamps via one `Min` at the same input).
- **Self-answering via telemetry:** the A2.1 pre-wire should publish **both**
  (a) the value on the StateMachine's warnings input and (b) WarningIntegration's
  output. Same wire ⇒ one variable; different ⇒ telemetry proves the clamp is
  disconnected, and shadow compare will show LabVIEW ignoring warnings while the
  port honors them.
- **Port impact: none.** The port consumes `warnings_limit` as designed; this is
  an as-built LabVIEW fact for shadow mode to surface.

## Standing observations for the team (from the port itself)

- **`ForceState` overrides EMERGENCY STOP** (wired directly to the SYSTEM STATE
  indicator, after the MIN). If e-stop-always-wins is the intent, the VI needs a
  guard — flagged for review; the port reproduces the as-built behavior.
- **`DisregardWarnings` bypasses the entire MAX-LEVEL limiter**, not just the
  warnings clamp (misleading name). Whatever sets it disables per-state caps.
- **NG-feed FIRING cap = 6** in the table (levels elsewhere are 0–2) — suspected
  typo for 2; ported as-is.
- **More detection-without-response** (2026-07-06, from `WarningIntegration`):
  the VI stall-detects the **9049** and **9056-FPGA** heartbeats (counter vs
  threshold 10), but the resulting "not responding" booleans drive front-panel
  indicators only — they do not feed `STATE LIMITATION FROM WARNINGS`. Same
  pattern as the unwired PC watchdog: loss of the 9049 (the engine-synchronous
  controller!) produces no supervisory reaction. Recommend wiring these into
  the warnings max alongside the B0 `PCnotResponding` fix.
