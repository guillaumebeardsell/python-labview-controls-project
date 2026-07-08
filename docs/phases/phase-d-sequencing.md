# Phase D — Sequencing Engine (detailed instructions)

**Objective:** build the layer that has never existed — automated operating
procedures (start, purge, light-off, venting, recovery) — test-first in Python.

**Authority level:** sequences issue the same commands Phase C already proved;
no new command surface. A sequence is "authorized" only for the plant
capabilities already commissioned at that time.

**Entry criteria:** D1/D2 can start **now** (no dependencies). D3 requires
Phase C exit. D-content (real procedures) requires D0.

**LabVIEW changes in this phase: none required.** Sequences are pure Python,
issuing the same `set_control_settings` commands Phase C proved, confirmed by
the same telemetry. The one foreseeable exception: a D0 procedure's
*confirmation* needs a plant signal that isn't in telemetry yet (a pressure,
a temperature, a valve feedback). The fix is one repeatable recipe — click
level, using `WF-PT-004` (working-fluid pressure, the venting sequence's
confirmation) as the worked example:

1. **Find the signal on the 9056.** In `APC_9056_TS_loop.vi`, locate the
   scaled value's wire (the AI-loop output feeding that sensor's indicator /
   control loop — `Ctrl-H` + hover to confirm which wire carries the scaled
   engineering value, not raw counts).
2. **Publish it:** `APC_SharedVars.lvlib` (9049 target) → *New → Variable* →
   name it after the tag (`WF_PT_004_bar`), **DBL**, Network-Published →
   *Deploy All*. Branch the scaled wire (click it, drag a branch) → a
   shared-variable **write** (*Access Mode → Write*), outside any case so it
   publishes every iteration. Redeploy the 9056 from the project.
3. **Envelope:** in the gateway's telemetry `Format Into String`, add a
   `plant` object. First tag:
   `,"plant":{"WF-PT-004_bar":%g}` — one new `%g` argument wired from the
   shared-variable read. More tags extend the same object:
   `,"plant":{"WF-PT-004_bar":%g,"EC-TT-001_degC":%g}` etc.
   **NaN caveat (the A2.1 lesson):** a channel that isn't being written — DAQ
   loop stopped, sensor task not running — flattens as `NaN`, which is
   invalid JSON and kills every frame. Only publish channels the running DAQ
   writes every iteration, and check with `python tools/capture_line.py`
   after each tag you add.
4. **Tag names must match the sim** so a sequence runs unchanged against sim
   and bench. The sim's current tags (`SimPlantModel.readings()` in
   `supervisory/monarch/simserver_monarch.py`): `WF-PT-004_bar`,
   `WF-OA-001_O2pct`, `EC-TT-001_degC`, `EO-TT-001_degC`, `WF-TT-004_degC`.
   Adding a tag the sim doesn't have? Add it to `SimPlantModel` too (a
   first-order lag is fine) — sequences confirm on `tm.plant["<tag>"]` via
   `plant_below()`/`plant_within()` and won't pass in sim otherwise.
5. **Python side needs nothing:** `MonarchTelemetry.plant` already parses any
   tags that appear. Log each addition in `docs/monarch-telemetry.md` so the
   envelope stays documented.

---

## D0 — Operating-procedure spec (team input — the critical path)

*Owner: you + team. I formalize whatever you produce.*

For each procedure — cold-start/cranking, purge, motoring→firing light-off,
normal shutdown, emergency vent, recovery-from-venting, misfire recovery,
working-fluid quality check — capture, in any format (bullet notes fine):

1. **Goal + preconditions** (state, temperatures, pressures, valve lineup).
2. **Steps in order**: action (what to command) + **confirmation** (what
   telemetry proves the step took) + **timeout** (how long before it's a fail).
3. **Holds**: points requiring operator confirmation before proceeding.
4. **Abort conditions per step** and where the abort lands (SAFE? STAND_BY?
   specific vent lineup?).
5. **Invariants** that must hold throughout (e.g. combustion stop ⇒ NG+O2 cut;
   never close all vents below state X; coolant flow before firing).

A one-page template lives at the bottom of this file — one copy per procedure.
Where the team is unsure (never run!), write the *intent* and mark `TBD`; the
sim work in D2 is where TBDs get exercised safely.

## D1 — Sequence framework

*Owner: Claude. Start immediately with placeholder sequences.*

`supervisory/sequencing.py` (generic layer, MONARCH-agnostic):
- **Step primitives:** `command(intent)`, `wait_for(condition, timeout)`,
  `hold(message)` (operator confirm), `branch(condition, then, else)`,
  `abort_to(state)`.
- A `Sequence` is **data** (a list of steps), executed by a `SequenceRunner`
  that is itself a `StateMachine` (pure decisions per tick — reuses the whole
  engine/test/replay stack).
- **Semantics:** every step's confirmation comes from telemetry, never from
  "command sent". Timeouts and telemetry staleness both abort. Aborts are
  always reachable (checked every tick, not between steps), always land in the
  declared safe state, and always run the invariant checks. Operator can
  pause/abort any sequence at any tick.
- **Invariant hooks:** a list of predicates evaluated on every tick of every
  sequence; violation ⇒ immediate abort path. First entries: combustion-stop ⇒
  NG+O2 cut; vent lineup rules (from D0).
- Tests: framework semantics (timeout, abort mid-step, staleness abort,
  invariant trip, hold behavior) with scripted fake telemetry.

## D2 — Plant simulator upgrade

*Owner: Claude, with plant sanity checks from you.*

Extend `simserver_monarch` into a minimal plant: first-order responses for the
thermal loops, pressure dynamics for Ar feed/venting, gas-analyzer lag, warning
injection hooks, and state-consistent behavior (e.g. temperatures only move
when their loop mode > 0). Fidelity target: *good enough to exercise sequence
logic*, not physics. Then:
- run every D0 sequence against the sim;
- **property tests**: random fault injection (warning trip, telemetry dropout,
  NACK, plant stall) at random steps ⇒ the runner always lands in the declared
  abort state with invariants intact — hundreds of randomized runs in CI.

## D3 — Bench execution

*Owner: joint. Requires Phase C exit + commissioned plant pieces.*

Order sequences by hardware needed, not by operational order — the
non-combustion ones both come first and are what commissioning itself needs:
1. Venting / vent-lineup sequences (valves only).
2. Working-fluid quality check (sensors + venting).
3. Thermal warm-up (coolant/oil/exhaust loops).
4. Purge and Ar fill (gas handling).
5. Cranking/motoring (needs dyno + 9049 commissioned).
6. Light-off / firing (last, with the team, as commissioning dictates).

Each: dry-run in sim the same day → bench run under C3 handover → archive
recording → mark the sequence "bench-proven" in its spec file.

**Ownership handback rule (ICD §7.7 corollary):** a sequence owns the intent
only while `RUNNING`/`HOLDING` (a Hold pauses the procedure, not the
ownership). The tick it reaches DONE or **ABORTED**, the panel resumes full
ownership — so an abort's safe landing persists only until the mirror
re-asserts the panel's current values. Consequence for procedures: the C3
lineup-check discipline applies **after every sequence end, especially
aborts** — the operator confirms the panel reads the intended post-sequence
lineup (or takes the plant back to one) before anything else.

---

## Phase exit gate

- Framework + sim property tests green in CI.
- Every D0-specced sequence has spec-traceable tests.
- Non-combustion sequences (1–4) bench-proven.

**Artifacts:** `sequencing.py`, upgraded plant sim, `sequences/` (one file per
procedure: spec header + step data), property-test suite, bench recordings.

---

## Appendix — procedure spec template (copy per procedure)

```
PROCEDURE: <name>                     AUTHOR/DATE:
GOAL:
PRECONDITIONS:  state=       plant conditions=       valve lineup=
INVARIANTS (throughout):
STEPS:
  1. ACTION:            CONFIRM (telemetry):          TIMEOUT:      ABORT→
  2. ...
HOLDS (operator confirm before step #):
ABORT LANDING (default):              NOTES/TBD:
```
