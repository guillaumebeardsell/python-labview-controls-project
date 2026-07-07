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

1. **Close the remaining detection-without-response gaps.** As-built status
   (2026-07-07): the B0 wiring already clamps on **`PCnotResponding` OR
   `9049notResponding`** (both from the WatchDog VI) — so PC loss and 9049
   loss are covered. Remaining candidate: WarningIntegration's
   **`9056 FPGA not responding`** stall detector (indicator-only today).
   Click level, in `APC_9056_TS_loop.vi`:
   1. Get the flag onto a wire: if the WarningIntegration subVI exposes it as
      a connector-pane output, branch it; if it only drives a front-panel
      indicator *inside* the subVI, first open `APC_9056_WarningIntegration.vi`
      and wire that indicator's value to a spare connector-pane terminal
      (right-click the pane → choose a free terminal → click terminal, click
      indicator), save, then wire it at the call site.
   2. Add it to the existing B0 clamp: the `Select`(−1:3) + `Min` chain is
      already there. Drop one more `Select` (TRUE → I8 `−1`, FALSE → I8 `3`),
      wire the new flag to its selector. Past two clamp sources, replace the
      chained `Min`s with **`Build Array` → `Array Max & Min`** (Array
      palette) and use the **min** output into the StateMachine's
      `STATE LIMITATION FROM WARNINGS` input.
   3. Threshold: WarningIntegration's internal stall threshold is a constant
      10 — at the ~50 Hz control loop that's 0.2 s, much hotter than the 5 s
      house standard. Consider raising it toward `5000 / Iteration Time` for
      consistency before arming the clamp.
   4. Re-run the affected B4 drills after wiring; capture one episode and
      check `shadow_compare` still agrees 100%.
2. **Warning-limit table hygiene** — E2's temporal rules live in Python, but
   the *instantaneous* per-channel limits stay in the LabVIEW XML/INI
   (`WarningLevels.xml` on the 9056). When commissioning tunes thresholds,
   update them there via the existing `_UI_Errors` screen (no diagram edits),
   and re-capture a flatten if `APC_ControlSettings.ctl` ever changes
   (`docs/monarch-flatten-diff.md`).
3. **MTR/membrane commanding** — the PC's Modbus-master code is built as its
   **own executable** (`APCModbusMaster` build spec in `MONARCH.lvproj`,
   separate from the `APC_Monarch` UI EXE) — so first trace **which process
   actually runs the Modbus loop** in the control room (the standalone EXE vs
   a UI-integrated loop). If/when setpoint scheduling (E3) should drive the
   membrane, the minimal-change route stands: whichever process owns Modbus
   keeps it; the values it writes come from `PC_ControlSettings` fields Python
   already commands (`AIC201_CO2_ConcTarget`, membrane mode) — **no new
   LabVIEW plumbing** if those fields are already consumed. Verify consumption
   before assuming. Moving the Modbus master itself into Python is explicitly
   **not** planned (it's FLOOR-adjacent I/O).
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
