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
the same telemetry. The one foreseeable exception: if a D0 procedure's
*confirmation* needs a signal that isn't in telemetry yet (e.g. a valve
position feedback or a plant sensor outside the ControlSettings cluster),
the fix is the established A2.1 pattern — publish it as a shared variable on
the owning cRIO, add one field to the gateway envelope, `capture_line.py` to
verify — and nothing else. Log any such addition in `docs/monarch-telemetry.md`
so the envelope stays documented.

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
