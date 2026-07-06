# Phase A — Shadow Brain (detailed instructions)

**Objective:** Python computes every supervisory decision the 9056 makes today —
state arbitration, control limiting, warning policy — verified against spec and
bench captures, **without sending anything**.

**Authority level:** none. Read-only throughout.

**Entry criteria (all met as of 2026-07-06):** read-only telemetry pipeline live
(`docs/monarch-telemetry.md`), `ControlSettings` contract confirmed, `monarch.jsonl`
recordings available.

---

## A1 — Port `APC_9056_StateMachine` to Python

*Owner: Python (Claude). LabVIEW input needed: one export (step 0).*

**A1.0 — Pin the last unknowns (LabVIEW export, ~15 min)**
Export a zoomed PDF/PNG of the current (2026) `APC_9056_StateMachine.vi` block
diagram showing, readably:
- the small per-limitation case frames (the `True/False` cases feeding
  "Aggregate (MIN) State Limitation") — we need the exact clamp value inside each;
- the `ManualState`/`ForceState` case and the `DisregardWarnings` case contents;
- what triggers `PostMortemSave`.
Drop it in `screenshots/`. Until then the port proceeds on these **assumptions**
(each marked in code with `# ASSUMPTION`): E-STOP → −1; Force Motoring → ≤1;
Force Idling → ≤2; no-warning sentinel = 3 (no limit); `DisregardWarnings`
bypasses only the warnings clamp; `PostMortemSave` fires on entry to SAFE.

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

---

## A2 — Shadow-compare harness

*Owner: split — LabVIEW pre-wire (you), harness (Claude).*

**A2.1 — LabVIEW: pre-wire the shadow-mode extras (gateway change)**
Per `docs/monarch-telemetry.md` §Shadow-mode extras. Concretely:
1. Publish to the PC what isn't yet reachable there (same pattern as
   `SystemState`): add network-published shared variables for
   `STATE LIMITATION FROM WARNINGS` (I8), `ManualState` (I8), `ForceState`
   (bool), and `Limited_ControlSettings` (the typedef) to the shared-vars
   library; write them at the StateMachine call site on 9056; deploy.
2. In `APC_PC_PythonGateway.vi`, extend the envelope `Format Into String`:
   ```
   {"type":"telemetry","seq":%d,"ts":%.3f,"system_state":%d,"warnings_limit":%d,"manual_state":%d,"force_state":%s,"settings":%s,"limited_settings":%s}\r\n
   ```
   New args in order: `warnings_limit` (%d), `manual_state` (%d), `force_state`
   (Select True→`true`/False→`false` constant → %s), `limited_settings`
   (`Flatten To JSON` of the Limited cluster → %s).
3. Verify with `python examples/monarch_listen.py` — the extras appear in the
   log line and `unmapped=[]` still holds. No Python change needed.

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

---

## A3 — Port the warning → state policy

*Owner: Python (Claude). LabVIEW input needed: exports.*

**A3.0 — Exports (you)** — blocked behind the `APC_9056_TexhControl.vi` typedef
error; fix first (LabVIEW: open `APC_9056_TexhControl.vi`, right-click the
`PC_ControlSettings` front-panel control → **Review and Update from Type Def**,
resolve the flagged defaults, save). Then export:
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

---

## Phase exit gate

- A1 + A3 suites green, assumptions resolved or dispositioned.
- Shadow compare: 0 unexplained divergences across all bench sweeps.
- Artifacts: `state_machine.py`, `warning_policy.py`, `tools/shadow_compare.py`,
  sweep recordings, divergence dispositions (a short `docs/shadow-findings.md`
  if any are LabVIEW bugs — likely commissioning gold).
