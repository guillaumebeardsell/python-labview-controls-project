# Phase E — Commissioning Support & Expansion (detailed instructions)

**Objective:** use the Python supervisory stack to drive commissioning itself,
then grow the policy layers (temporal warning rules, setpoint scheduling) that
were never built in LabVIEW.

**Authority level:** grows with commissioning — each plant capability is
unlocked for Python command/sequencing only after its own bench drill, per the
team's commissioning plan. The LabVIEW limiter and all FLOOR mechanisms remain
permanently.

**Entry criteria:** Phase C exit (authority proven); D sequences bench-proven
as hardware becomes available. This phase is deliberately less prescriptive —
it tracks the commissioning campaign, which the team owns.

**LabVIEW changes in this phase** (all optional-but-recommended hardening;
none block E1–E3, which are Python/data work):

1. **Close the remaining detection-without-response gaps** — if not already
   done as B0 step 5: in `APC_9056_TS_loop.vi`, route WarningIntegration's
   `9049 not responding` and `9056 FPGA not responding` booleans through
   `Select`(−1 : 3) nodes into the same `Min` chain that feeds the
   StateMachine's `STATE LIMITATION FROM WARNINGS` input (Build Array → Array
   Max & Min's *min* output scales past two inputs). Loss of the
   engine-synchronous controller then produces a supervisory SAFE clamp, not
   just a lamp. Re-run the affected B4 drills after wiring.
2. **Warning-limit table hygiene** — E2's temporal rules live in Python, but
   the *instantaneous* per-channel limits stay in the LabVIEW XML/INI
   (`WarningLevels.xml` on the 9056). When commissioning tunes thresholds,
   update them there via the existing `_UI_Errors` screen (no diagram edits),
   and re-capture a flatten if `APC_ControlSettings.ctl` ever changes
   (`docs/monarch-flatten-diff.md`).
3. **MTR/membrane commanding** — today the PC UI is the Modbus master writing
   MTR targets. If/when setpoint scheduling (E3) should drive the membrane,
   the minimal-change route is: UI keeps the Modbus master loop; the values it
   writes come from `PC_ControlSettings` fields Python already commands
   (`AIC201_CO2_ConcTarget`, membrane mode) — i.e. **no new LabVIEW plumbing**
   if those fields are already consumed. Verify consumption before assuming;
   flag as a small trace task when E3 starts. Moving the Modbus master itself
   into Python is explicitly **not** planned (it's FLOOR-adjacent I/O).
4. **Retirement pass** — as Python sequences take over operator workflows,
   UI-side request-conditioning logic (mode-request buttons wired to
   `Requested mode`, force buttons) stays functional as the manual fallback;
   retire nothing until the team decides the manual path's final shape.

---

## E1 — Commissioning with sequences

- For each commissioning milestone (cold flow → gas handling → thermal →
  motoring → first fire), pair the team's checklist with the corresponding
  D-sequence: the sequence *is* the procedure record — its recording +
  `operate.jsonl` become the commissioning evidence.
- Shadow alarm (C2) stays armed through every session; divergences and NACKs
  reviewed same-day — during commissioning these are cheap discoveries of
  LabVIEW-vs-spec surprises.
- After each milestone: re-run the A2 shadow suite over that day's recordings;
  update sequence TBDs with measured values (real time constants, real
  thresholds) and re-run the D2 property tests.

## E2 — Temporal warning rules (authoring, not porting)

The original developer flagged these as needed-but-unbuilt. Build them in the
Python warning-policy layer (extends `warning_policy.py` from A3):
- Rule form: `WHEN <channel/predicate> FOR <duration> WHILE <state set> ⇒
  <action: cap state | force sequence | operator alert>`.
- Rules are **data** (a table the team reviews), evaluated in the tick loop;
  each rule gets a unit test with synthetic time series (the pure-decision
  engine makes time injectable).
- Start list (from the report's examples + commissioning experience): oil
  pressure low > X s while ≥ MOTORING; coolant flow absent > X s while thermal
  loops active; heartbeat degradation patterns. The team supplies X's.
- LabVIEW keeps its instantaneous hard trips unchanged — temporal rules are a
  *supervisory* layer on top, never a replacement.

## E3 — Setpoint scheduling

- Operating-point tables (state/speed/load → loop modes + setpoints) as
  versioned data files (`schedules/*.toml` or similar), applied by a small
  scheduler machine; every applied schedule row echoed to the log.
- Manual override always wins; scheduler re-asserts only on operating-point
  change (no fighting the operator).
- Tests: table lookup, interpolation (if any), override precedence.

## E4 — Consolidation & stewardship

- Revisit what remains supervisory in LabVIEW (UI request conditioning, MTR
  target commanding) — move or retire case-by-case; the FLOOR never moves.
- Model `9049_ControlSettings` in Python when direct 9049 observation/command
  becomes useful (was deferred; needed at latest here).
- Repo hygiene each milestone: `pytest` green, `tools/compare_flatten.py`
  re-run after any typedef change, docs' status sections updated
  (`docs/migration-plan.md` stays the authority).
- Decide the end-state operator surface (keep LabVIEW HMI + Python CLI, or
  build a Python UI) — explicitly out of scope until sequences are routine.

---

## Phase exit / steady state

There is no hard exit — E ends when commissioning does. Steady state:
sequences drive routine operation, temporal rules + schedules live as reviewed
data, LabVIEW holds the floor, and every supervisory change lands as a tested
Python PR instead of an unversioned VI edit.
