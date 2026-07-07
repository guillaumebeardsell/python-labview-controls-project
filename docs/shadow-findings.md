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
