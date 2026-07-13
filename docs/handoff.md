# Handoff — continuing this project without the original assistant

> **Newest state: `docs/session-handoff-2026-07-11.md`** — autonomous
> deployment working (cold-boot verified), SIL-0 analytics validated, the
> current next-steps, and the robustness gaps. Read that + `migration-plan.md`
> for *where things are*; this file is about *how to keep working*.

Written 2026-07-07 (Python deliverables front-loaded); the frontier has since
moved to LabVIEW/hardware — see the banner above. This file is about *how to
keep working* — with a cheaper/newer AI model, or by hand.

## What is DONE and verified (don't rebuild)

- **Autonomous deployment (2026-07-11):** both cRIOs boot startup `.rtexe`s, PC
  apps as EXEs, Python observes/commands; cold-boot verified. Runbook +
  symptom→cause table: `docs/deployed-bringup.md`.
- **SIL-0 analytics validated (2026-07-11):** 9049 HRL/IMEP/CA50 vs known truth,
  425 comparisons all within tol. `docs/9049-openloop-audit.md` §7; tools
  `gen_cas_traces.py` / `compare_hrl.py` / `tune_thresholds.py`.
- Transport + ICD v0.1, live telemetry pipeline, `ControlSettings` contract
  (confirmed vs live flatten), reconnect resilience.
- **Phase A code**: StateMachine port (validated LIVE — 100% agreement, all 5
  states), warning policy port, shadow-compare harness (+ `--alarm`).
- **Phase B Python**: ICD v0.2 draft (§7 of `docs/icd.md`), MonarchCommander,
  commandable sim gateway running the real ported logic, failure-matrix tests.
- **Phase C Python**: operator CLI (`examples/monarch_operate.py` — an
  engineering tool; the HMI stays the operator's console per ICD §7.7),
  reverse shadow alarm, and the **operator-request mirror**
  (`operator_mirror.py`: UI inputs flow to Python as requests while Python
  holds authority; safety inputs always mirror, sequences own the intent).
- **Phase D**: sequencing framework, sim plant model, draft venting/purge/
  thermal-warmup sequences (closed-loop tested, randomized fault injection).
- **Phase E engines**: temporal warning rules, setpoint scheduler (data-driven;
  values are TBD(team)).
- `Settings9049` model (doc-transcribed; flatten confirmation pending), CI
  (GitHub Actions, py3.10 + 3.12).

## The invariants that must never be weakened

1. **LabVIEW/cRIO/FPGA owns hardware, interlocks, validation, safe fallback.**
   Python only ever *requests*. If a change makes Python's absence unsafe, the
   change is wrong.
2. **Telemetry is the only truth**; ACK = validated, not done; rebuild from
   telemetry after reconnect; stale ⇒ stop commanding.
3. **The suite stays green** (`pytest`, 183 tests, CI enforces). A red test is
   a stop-the-line event, not an inconvenience.
4. **Contract lockstep**: any `APC_ControlSettings.ctl` change ⇒ re-run
   `tools/compare_flatten.py` on a fresh flatten (workflow:
   `docs/monarch-flatten-diff.md`).
5. E-stop: settable from anywhere, clearable only by the operator.

## Working with a smaller/cheaper model — task guidance

Safe to delegate (mechanical, pattern-following — the repo shows the pattern):
- Filling `TBD(team)` values into `SequenceConfig`, rule tables, schedule rows
  once the team supplies numbers (tests pin the mechanics).
- New sequences from completed D0 template sheets (copy `venting()`'s shape;
  keep `abort_change=safe_landing`, keep invariants; add a closed-loop test).
- New telemetry fields (gateway adds a tag → add the optional field to
  `MonarchTelemetry` + parse line + a test — mirror `plant`).
- New warning channels (`ChannelLimits` entries), new temporal rules, new
  schedule rows — data, not logic.
- Doc/status upkeep; new shadow-compare recordings + dispositions (follow
  `docs/shadow-findings.md` format).

Needs care (do slowly, verify hard, prefer a strong model or human review):
- Anything in `state_machine.py` / `warning_policy.py` semantics — these are
  *fidelity ports*; changes must trace to a VI change or a dispositioned
  divergence, never to taste.
- Commander/executor authority handling (`commanding`, staleness, source
  flips) — the safety posture lives there.
- ICD changes (both sides must move in lockstep with the LabVIEW gateway).
- Anything under "The invariants" above.

Prompting tip: point the model at `CLAUDE.md`, the relevant `docs/phases/`
file, and the nearest existing test file; ask it to follow the established
pattern and to run `pytest` before claiming done.

## What only humans can supply (the real remaining inputs)

| Input | Unblocks | Where specified |
|---|---|---|
| ~~B1 joint review~~ **done 2026-07-07**: 5 s threshold; UI toggles `PC_HB` (option a); `UI_HeartBeat` follow-on specified. Soft default remaining: `CommandSource` switch on the HMI System screen | ~~B0 wiring, B3 build~~ unblocked | `docs/icd.md` §7 (frozen) |
| LabVIEW B0 + B3 edits (fully specified, node-level) | B4 drills → any authority | phase-B file |
| A2.1 remaining gateway pre-wire (warnings/manual/force vars) + sweeps with the 9056 StateMachine running | Phase A exit | phase-A file |
| **D0 operating-procedure sheets** (template at the bottom of phase-D file) | Real sequences | phase-D file |
| TBD(team) numbers (SequenceConfig, rules, schedules) | E-layer activation | in-code markers |

## Orientation for a fresh session

1. `README.md` → `docs/migration-plan.md` (authoritative status) →
   `docs/migration-seam.md` (why the boundary is where it is).
2. `pip install -e ".[dev]" && pytest` — 183 tests, sub-2 s.
3. Offline demo of everything: terminal 1
   `python -m supervisory.monarch.simserver_monarch --source PYTHON --speedup 5`,
   terminal 2 `python examples/monarch_operate.py` → `status`, `mode motoring`,
   `seq run venting`.
4. The LabVIEW project lives on the control-room PC; exports for reference are
   under `original-labview-codebase/` (per-frame HTML/GIF export is the
   preferred format — see the phase-A A1.0 notes).
