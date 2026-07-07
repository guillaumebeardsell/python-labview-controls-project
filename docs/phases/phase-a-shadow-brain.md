# Phase A — Shadow Brain (detailed instructions)

**Objective:** Python computes every supervisory decision the 9056 makes today —
state arbitration, control limiting, warning policy — verified against spec and
bench captures, **without sending anything**.

**Authority level:** none. Read-only throughout.

**Entry criteria (all met as of 2026-07-06):** read-only telemetry pipeline live
(`docs/monarch-telemetry.md`), `ControlSettings` contract confirmed, `monarch.jsonl`
recordings available.

**LabVIEW changes in this phase:** A2.1 only (shared variables + TS_loop taps +
gateway envelope). A1 and A3 are pure Python; their LabVIEW inputs (exports) are
already delivered.

---

## A1 — Port `APC_9056_StateMachine` to Python

*Owner: Python (Claude). LabVIEW input needed: one export (step 0).*

**A1.0 — Pin the last unknowns** ✅ **done (2026-07-06)** — resolved from the
re-exported `APC_9056_StateMachine/` per-frame images (`d1`–`d8` + main diagram
crops). Confirmed semantics:
- Per-source limits: E-STOP → −1, Force Motoring → 1, Force Idling → 2 (True
  cases); each **False case → 3** (no restriction).
- Arbitration implemented as **Build Array → Sort 1D Array → Index[0]**, i.e.
  MIN over {requested mode, warnings limit, e-stop, force-motoring,
  force-idling, current+1}; the `current+1` step-up element is gated by the
  per-state "forced transition condition" cases, which are **all constant TRUE**
  (no plant-feedback guards implemented).
- `ForceState` TRUE ⇒ `SYSTEM STATE` = `ManualState` **absolutely** (the
  override case output wires directly to the indicator, after/independent of
  the MIN — bypasses the +1 rule too).
- `DisregardWarnings` — **misleading name**: it wraps the controller-level
  limiter, not the warnings clamp. FALSE case = a For loop taking the
  element-wise `min(requested_level[i], state_row[i])`; TRUE case = **bypass**
  (limited = requested, no per-state caps). It does not affect the state
  arbitration itself.
- `PostMortemSave` is a **shared-variable write** (TRUE) gated by a `>`
  comparator AND the per-state forced-transition condition — i.e. it fires on a
  forced (downward) state transition, presumably triggering the post-mortem
  file save in the logging loop (matches the logging doc: error/forced-mode
  transitions trigger the A-file capture).
Residual (single, cosmetic): the `>` operand order wasn't traceable pixel-level
— assumed `current > new` (downward). Mark `# ASSUMPTION` in code.

**A1.1 — Data model**
New module `supervisory/monarch/state_machine.py`:
- `StateDecisionInputs`: `current_state: SystemState`, `warnings_limit: int`,
  `settings: ControlSettings` (carries `requested_mode`, `force_idling`,
  `force_motoring`, `emergency_stop`), `force_state: bool`, `manual_state: int`,
  `disregard_warnings: bool = False`.
- `StateDecision`: `system_state: SystemState`, `limited_settings:
  ControlSettings`, `limits: dict[str, int]` (per-source limit values, for
  the shadow-compare report), `post_mortem: bool`.

**A1.2 — State arbitration (pure function)**
`decide_state(inputs) -> SystemState`:
1. Compute per-source limits: `requested = settings.requested_mode`;
   `warnings = warnings_limit` (skipped if `disregard_warnings`);
   `estop = −1 if settings.emergency_stop else 3`;
   `force_motoring = 1 if settings.force_motoring else 3`;
   `force_idling = 2 if settings.force_idling else 3`.
2. `target = min(all of the above)`.
3. **Increase-by-1 rule:** `if target > current_state: target = current_state + 1`.
   (Decreases are immediate and unlimited — SAFE is always reachable in one step.)
4. **Override:** `if force_state: target = manual_state` (bypasses everything —
   confirm against the export whether it also bypasses the +1 rule; assumed yes).
5. Return the clamped `SystemState`.

**A1.3 — The limiter (MAX LEVEL OF CONTROL)**
`limit_settings(settings, state) -> ControlSettings`: apply the table below —
each actuator's commanded level is `min(requested_level, max_for_state)`; boolean
actuators (vents, IGN/DI enables, feed valves) clamp to their safe value when the
column says 0. Encode the table as **data** (a dict), not branching code.

| Controller | SAFE −1 | STANDBY 0 | MOTORING 1 | IDLING 2 | FIRING 3 | safe value |
|---|---|---|---|---|---|---|
| NG feed | 0 | 0 | 0 | 0 | 6* | closed |
| Ar feed | 0 | 0 | 2 | 2 | 2 | closed |
| O2 feed | 0 | 0 | 2 | 2 | 2 | closed |
| Coolant temp | 1 | 2 | 2 | 2 | 2 | max flow |
| Exhaust temp | 1 | 3 | 3 | 3 | 3 | max flow |
| Oil temp | 1 | 3 | 3 | 3 | 3 | max flow |
| Intake/Cross/Exh vent | 0 (open) | 1 (closed) | 1 | 1 | 1 | open |
| Dyno | 0 | 0 | 2 | 2 | 2 | stopped |
| IGN | 0 | 0 | 0 | 1 | 1 | deactivated |
| DI | 0 | 0 | 0 | 1 | 1 | deactivated |
| MTR | 0 | 0 | 2 | 2 | 2 | TBD |

\* the NG=6 cell is suspected a typo in the VI (levels are 0–2 elsewhere); port it
**as-is** (fidelity first), flag it in the shadow report, and decide with the team.

**A1.4 — Test matrix (the phase's real deliverable)**
`tests/test_monarch_state_machine.py`:
- **Exhaustive arbitration sweep:** all `current_state × requested_mode ×
  warnings_limit × {e-stop, force_motoring, force_idling} × force_state`
  combinations (5×5×5×8×2 = 2000 cases, trivially fast) asserting the MIN +
  step-by-1 + override semantics.
- **Directed cases:** SAFE reachable in one step from FIRING; step-up chain
  STAND_BY→…→FIRING takes exactly 4 ticks; warnings clamp mid-run forces
  step-down; e-stop wins over ForceState? (**confirm in export** — assumed
  e-stop wins); latched-warning behavior is A3's job, not here.
- **Limiter:** per-state spot checks of every row; vent polarity (SAFE ⇒ vents
  open = `false`); **combustion invariant:** any transition out of
  IDLING/FIRING ⇒ NG and O2 modes clamp to 0 in the same tick.
- **Fidelity fixture:** feed the recorded `monarch.jsonl` frames through
  `decide_state` and assert no crashes + plausible outputs (full comparison is A2).

**Definition of done (A1):** suite green; every `# ASSUMPTION` either confirmed
against the A1.0 export or listed in the shadow-compare report as open.

> **Status: BUILT (2026-07-06).** `supervisory/monarch/state_machine.py` +
> `tests/test_monarch_state_machine.py` (28 tests incl. the ~30k-case sweep),
> all green. Two cosmetic `# ASSUMPTION`s remain (the `>` operand order,
> valve rows reusing feed rows) — both listed in `docs/shadow-findings.md`.

---

## A2 — Shadow-compare harness

*Owner: split — LabVIEW pre-wire (you), harness (Claude).*

**A2.1 — LabVIEW changes required (the only LabVIEW work in Phase A)**
Per `docs/monarch-telemetry.md` §Shadow-mode extras. Full detail:

*Part 1 — create the shared variables (`APC_SharedVars.lvlib`).*
In the Project Explorer, right-click the library → **New → Variable**, once per
row. All **Network-Published**, no buffering, no RT-FIFO (single 1 Hz values),
hosted on the same target as the existing `SystemState` variable:

| Variable | Data type | Carries |
|---|---|---|
| `WarningsLimit_SM` | I8 (or the state enum typedef) | the value **on the StateMachine's `STATE LIMITATION FROM WARNINGS` input terminal** |
| `ManualState_SM` | I8 | the StateMachine's `ManualState` input |
| `ForceState_SM` | Boolean | the StateMachine's `ForceState` input |
| `Limited_ControlSettings` | **Custom Control → `APC_ControlSettings.ctl`** | the StateMachine's `Limited_ControlSettings` output |

**Deploy** the library after adding (right-click → Deploy). Undeployed
variables silently read defaults.

> **Prerequisite fix — wire the warning clamp (confirmed disconnected, 2026-07-07).**
> The StateMachine's `STATE LIMITATION FROM WARNINGS` input is **not** wired to
> `WarningIntegration`'s output — it runs on its front-panel default, so the
> warning→state clamp is currently inert (`docs/shadow-findings.md`). The right
> fix is to **make that wire** in `APC_9056_TS_loop.vi`: `WarningIntegration`'s
> `STATE LIMITATION FROM WARNINGS` output → the StateMachine's same-named input.
> It's FLOOR safety logic that belongs in LabVIEW, it activates a dormant safety
> feature, and it survives into the target architecture (LabVIEW keeps its own
> independent warning clamp even once Python holds authority). **Once wired, the
> SM input equals the WI output**, so a single `WarningsLimit_SM` variable
> suffices (the earlier two-variable scheme was only to expose the disconnect).
> *Behavior caveat:* wiring it means active warnings now actually drive the state
> down. Pre-commissioning, sensors reading zero/ambient may fire spurious
> warnings that peg the state to SAFE/idle — that is the *correct* safe response,
> but validate it deliberately (set warning thresholds wide, or use operator
> clear, during bench work) rather than being surprised on the bench.

*Part 2 — write them on cRIO-9056, inside `APC_9056_TS_loop.vi`.*
At the `APC_9056_StateMachine.vi` call site (main loop, next to the DIAG VI):
0. **First make the warning wire — recipe (do this cleanly).** Goal: a single
   direct wire, `WarningIntegration.STATE LIMITATION FROM WARNINGS` output →
   `StateMachine.STATE LIMITATION FROM WARNINGS` input, both inside `TS_loop`.
   No shared variable between them — they're on the same diagram, so a wire is
   the correct (and lowest-latency) way to pass the value.
   1. **Identify the two nodes.** Open `Context Help` (Ctrl-H) and hover each
      subVI to confirm names: the `STATE ?` icon is `APC_9056_StateMachine.vi`;
      the adjacent `DIAG` icon should be `APC_9056_WarningIntegration.vi`
      (confirm — if it isn't, find where WarningIntegration is actually called).
   2. **Expose the terminals.** Right-click each subVI → *Visible Items →
      Terminals* (or just hover a terminal with Ctrl-H open to read its label).
      On WarningIntegration find the `STATE LIMITATION FROM WARNINGS` **output**;
      on the StateMachine find the same-named **input**.
   3. **Confirm the input is free.** The StateMachine's warnings input should
      have no wire today (the finding). If a front-panel control's terminal is
      wired to it instead, delete that stub first.
   4. **Draw the wire.** Click the WarningIntegration output terminal, drag to
      the StateMachine input terminal. **Non-destructive branch:** if that output
      already goes somewhere (a shared-variable write or an indicator), don't
      disconnect it — start the new wire by clicking anywhere on the existing
      wire and dragging a branch to the StateMachine input.
   5. **Match the data type — no coercion dot.** Both should be `I8` (or the same
      state-enum typedef). A grey/red coercion dot at the input means the types
      differ; make them identical (tidier and avoids silent enum↔I8 surprises).
   6. **Execution order is now correct automatically.** The wire makes
      WarningIntegration run *before* the StateMachine each iteration (compute
      warnings → arbitrate state) — the order you want. **No cycle:** both read
      `CURRENT SYSTEM STATE` from the loop's feedback node (last iteration's
      value), and only the StateMachine writes the new state back, so there is no
      SM→WI→SM loop.
   7. **Verify:** the run arrow is not broken; run once and confirm behavior (see
      the caveat above — warnings will now clamp the state).
   8. **Forward note (avoid rework):** this same `STATE LIMITATION FROM WARNINGS`
      input is where the other detection-without-response fixes also belong — the
      B0 loss-of-PC clamp (`PCnotResponding → −1`) and the 9049/9056-FPGA
      not-responding clamps. When you add those, don't run separate wires: feed
      them and the WarningIntegration output through one `Min` (Build Array →
      Array Max & Min → *min*) into this single input. Wire WarningIntegration
      directly now; leave room to insert that `Min` later.
1. For each **input** (`warnings`, `ManualState`, `ForceState`): branch the
   wire that feeds that StateMachine terminal (click the wire → Ctrl-drag a
   branch), and wire the branch into a shared-variable **write** node (drag the
   variable from the Project Explorer, right-click → *Access Mode → Write*). Tap
   the **terminal wire itself** — not the source VI's output — so telemetry
   reports what the StateMachine actually received.
2. For the **output**: branch the `Limited_ControlSettings` wire leaving the
   StateMachine and write it to the `Limited_ControlSettings` variable.
3. Writes execute once per loop iteration — negligible cost at the TS-loop
   rate; keep them outside any case structure so they always publish.
4. Redeploy the 9056 startup app / run the VI so the new writes are live.

*Part 3 — extend the gateway envelope (`APC_PC_PythonGateway.vi`, PC).*
Replace the telemetry format-string constant (keep **'\' Codes Display**):
```
{"type":"telemetry","seq":%d,"ts":%.3f,"system_state":%d,"warnings_limit":%d,"manual_state":%d,"force_state":%s,"settings":%s,"limited_settings":%s}\r\n
```
Grow `Format Into String` to **8 arguments**, wired in this exact order:

| # | Format | Wire | Type |
|---|---|---|---|
| 1 | `%d` | `seq` (existing) | I32 |
| 2 | `%.3f` | `ts` (existing) | DBL |
| 3 | `%d` | `system_state` (existing shared-var read) | I8/I32 |
| 4 | `%d` | `WarningsLimit_SM` read | I8 |
| 5 | `%d` | `ManualState_SM` read | I8 |
| 6 | `%s` | `ForceState_SM` read → **Select** (TRUE→`true` string const, FALSE→`false`) | String |
| 7 | `%s` | `Flatten To JSON` of the `PC_ControlSettings` read (existing) | String |
| 8 | `%s` | **new** `Flatten To JSON` of the `Limited_ControlSettings` read | String |

Notes: the boolean must go through the Select — `%d` would emit `1/0`, and
LabVIEW booleans don't format as `true/false` on their own. If you also wired
`WarningsLimit_WI`, add `"warnings_limit_wi":%d,` after arg 4 (Python ignores
unknown fields until modeled).

*Part 4 — verify, and troubleshooting.*
Run `python examples/monarch_listen.py`: the log line should now show
`warn_lim=… force=… | limited: …` and still `unmapped=[]`.

If instead you get **`discarding malformed message`** warnings (the observer
connects but decodes nothing):
- **Capture one full line** to see the actual defect (the log truncates at
  200 chars): `python tools\capture_line.py` — prints the whole line, then
  pinpoints the JSON error position (and hints at the NaN case below).
- **Most common cause — NaN/Inf:** LabVIEW's `Flatten To JSON` renders NaN as
  `NaN`, which is **invalid JSON** (Python rejects the whole line). An
  uninitialized `Limited_ControlSettings` shared variable (never written, or
  9056 not running) is the usual source. Fix: complete Part 2 and deploy, or
  default-initialize the variable.
- **Arg order/count:** one missing `Format Into String` input shifts every
  later `%` — compare the captured line field-by-field against the table above.
- **Quoting:** string-valued fields need quotes *in the format string*
  (`"force_state":%s` is correct because Select supplies bare `true`/`false`;
  a quoted string like command_source later needs `"%s"`).
- The framing/`\r\n` is proven — don't touch the TCP write while debugging
  content.

**A2.2 — Python: the compare tool**
`tools/shadow_compare.py`:
- Modes: `--replay monarch.jsonl` (offline) and `--live` (connect like the
  observer).
- Per frame: build `StateDecisionInputs` from the envelope, run the A1 port,
  diff `system_state` and every `limited_settings` leaf vs LabVIEW's.
- Report: agreement %, first-divergence detail (frame, inputs, both outputs),
  histogram of diverging fields, and the open-assumption list. Exit code 0 only
  on 100% agreement.
- Caveat printed in the header: **a divergence is a finding, not automatically a
  Python bug** — the LabVIEW side is unvalidated; disposition each one.

**A2.3 — Bench input sweeps (you, at the UI; observer recording)**
With the rig unpowered (pre-commissioning — StateMachine logic runs regardless):
walk `Requested mode` up and down; toggle Force idling / Force motoring; press
and clear EMERGENCY STOP; exercise `ManualState`+`ForceState`; if warning
thresholds can be provoked synthetically (e.g. set a threshold below ambient),
trigger orange/red/black severities. Each sweep = one `monarch.jsonl` recording,
named and kept under `recordings/` (add to repo or keep local — team choice).

**Definition of done (A2):** shadow compare runs clean (100% agreement or every
divergence dispositioned) across all sweep recordings.

> **Status: Python half BUILT (2026-07-06).** `tools/shadow_compare.py`
> (replay + live modes, session-reset handling, limiter diffing) with its own
> tests. First replay of `monarch.jsonl`: sim session **247/247 (100%)**; all
> real-session divergences dispositioned as "StateMachine not running during
> capture" — see `docs/shadow-findings.md`. Remaining: the A2.1 gateway
> pre-wire (LabVIEW) and bench sweeps **with the 9056 StateMachine actually
> running** and writing the SystemState shared variable.

---

## A3 — Port the warning → state policy

*Owner: Python (Claude). LabVIEW input needed: exports.*

**A3.0 — Exports (you)** — the `APC_9056_TexhControl.vi` typedef-update error
that blocked these is **fixed (2026-07-06)**; just export:
- `APC_9056_TS_loop.vi` (also closes B0),
- `APC_9056_WarningIntegration.vi`,
- `APC_9056_WarningBool.vi` / `APC_9056_ClearSoftWarning.vi` /
  `APC_9056_MaskErrors.vi` if small.

**A3.1 — Port** `supervisory/monarch/warning_policy.py`: severity→max-state map
(yellow = info, self-clearing; orange → cap IDLING; red → cap MOTORING; black →
SAFE + vent), latching non-yellow until operator clear, producing
`warnings_limit`. Tests mirror A1's style. Temporal rules ("X for Y s") are
**Phase E** — do not add them here; fidelity first.

**Definition of done (A3):** ported policy reproduces LabVIEW's
`STATE LIMITATION FROM WARNINGS` in shadow compare across the warning sweeps.

> **Status: BUILT (2026-07-06).** `supervisory/monarch/warning_policy.py` +
> `tests/test_warning_policy.py` (18 tests), transcribed from the
> WarningIntegration per-frame export. Confirmed semantics: levels 0–4
> (0 none, 1 soft/self-clearing, 2 → idle, 3 → motoring, 4 → safe+vent);
> per-channel 4-threshold evaluation with a ±sign direction and per-level
> enables; latch ratchets via feedback max, soft (1) self-clears, ≥2 holds
> until APC_MASTER/SLAVE_ClearWarnings (multiply-by-0 reset); aggregate =
> max level → mapping {0/1→3, 2→2, 3→1, 4→−1} (Default→3). Simplification:
> cylinder warnings enter as pre-merged levels (`extra_levels`) — the
> CylPres bitfield decode belongs to the 9049 contract. Remaining for A3
> done-ness: shadow-verify against live sweeps once the gateway pre-wire
> lands. Finding: the VI's 9049/9056-FPGA heartbeat stall detectors drive
> indicators only (same detection-without-response pattern as the PC
> watchdog) — logged in `docs/shadow-findings.md`.

---

## Phase exit gate

- A1 + A3 suites green, assumptions resolved or dispositioned.
- Shadow compare: 0 unexplained divergences across all bench sweeps.
- Artifacts: `state_machine.py`, `warning_policy.py`, `tools/shadow_compare.py`,
  sweep recordings, divergence dispositions (a short `docs/shadow-findings.md`
  if any are LabVIEW bugs — likely commissioning gold).
