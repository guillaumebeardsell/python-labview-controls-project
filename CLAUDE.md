# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The Python **supervisory layer** for the **MONARCH** control system — a Noble Thermodynamics
Argon Power Cycle research engine whose full stack currently runs in LabVIEW across two NI
CompactRIO controllers (cRIO-9049 FPGA+RT, cRIO-9056 RT) and a Windows PC. This repo owns the
migration of the *upper* stack (state machines, sequencing, supervisory decisions) into Python;
it talks to a LabVIEW "gateway" VI over localhost TCP.

## The safety invariant (read this first)

**LabVIEW/cRIO/FPGA permanently owns hardware I/O, hard safety interlocks, command validation,
and safe fallback. Python is supervisory only and must never be in the safety-critical path.**
The system must stay safe when the Python process is absent, crashed, or wrong — i.e.
**Python-offline == LabVIEW safe hold.** Separate *authority* from *safety*: Python may hold
decision authority (choose modes/sequences/setpoints), but every command it sends is a *request*
LabVIEW independently validates, and LabVIEW enforces the hard limits + safe fallback regardless.
Design every feature so a dead/hung/misbehaving Python side can only ever cause a rejected
request or a safe hold — never an unsafe actuation.

MONARCH context: the system has been **built but never commissioned or run on hardware**, and its
original developer has left. Don't propose capturing a real engine run; drive states/inputs
synthetically. Because the LabVIEW logic is unvalidated and unowned, its value as a shadow-mode
"ground truth" is limited — favor unit-testing the ported logic against the spec.

The safe-hold invariant is **already enforced in hardware**: the 9049 FPGA watchdog kills spark/DI
if the RT loop stops toggling it (>4 Hz), so a supervisor dropout is a safe hold — *provided Python
stays above that RT loop and never pets the watchdog*. Known gap: no documented watchdog on
`PC_ControlSettings`/loss-of-PC — a cRIO-side stale-command→SAFE watchdog must be resolved before
Python holds command authority (vs. read-only). See `docs/migration-seam.md` for the full
FLOOR/MIDDLE/BRAIN boundary and the port backlog; the scope is broader than the state machine
(sequencing/recipes — which don't exist in LabVIEW yet — plus warning policy and setpoint scheduling).

## Commands

```bash
pip install -e ".[dev]"                 # package (editable) + pytest; needs internet once
pytest                                   # full suite (testpaths=tests, pythonpath=. via pyproject)
pytest tests/test_control_settings.py -q            # one file
pytest tests/test_labview_mapping.py::test_faithful_capture_agrees   # one test

# Fake gateways for offline testing (no LabVIEW/hardware), plus their clients:
python -m supervisory.simserver                     # generic toy gateway  (127.0.0.1:5020)
python examples/hello_link.py                       #   connectivity smoke test / PASS-FAIL
python -m supervisory.monarch.simserver_monarch --speedup 5   # MONARCH telemetry gateway
python examples/monarch_listen.py                   #   read-only observer -> records monarch.jsonl

python tools/compare_flatten.py <labview_flatten.json>   # diff a LabVIEW cluster flatten vs the contract
python tools/shadow_compare.py monarch.jsonl              # replay decisions vs the ported StateMachine
python examples/monarch_operate.py                        # operator CLI (needs source=PYTHON on the gateway)
python tools/gen_warning_matrix.py                        # SIL-1 false-trip drill suite (7 sets + drill XML + manifest)
```

Environment: developed on a Windows control-room PC (Python 3.10, `.venv`). `requires-python` is
`>=3.10`; the suite is verified on 3.10.

## Architecture

Two layers, deliberately decoupled:

- **`supervisory/`** — the generic, project-agnostic framework:
  - `messages.py` — pydantic models for the wire protocol (`Telemetry`, `Command`, `CommandAck`,
    `Heartbeat`); `parse()`/`dump()`. Unknown fields are ignored (forward-compat).
  - `link.py` — `PlantLink` protocol + `TcpPlantLink` (background thread, LF-framed JSON,
    auto-reconnect with backoff). Takes a `parser=` so a MONARCH observer can decode richer
    payloads on the same transport.
  - `engine.py` — `Supervisor` tick loop + `StateMachine` base class. **The core design rule:**
    state machines are *pure decisions* — each tick they get a `PlantView` (latest telemetry,
    staleness, acks) and return `CommandRequest`s; no sockets/clocks/globals inside them. The
    `Supervisor` owns all side effects. This is what makes logic unit-testable and replayable.
  - `sim.py` / `simserver.py` — a socket-free `SimPlantLink` and a real-TCP fake gateway, so the
    engine runs with no LabVIEW. `recorder.py` — JSONL traffic recorder.
- **`supervisory/monarch/`** — MONARCH-specific payloads (the generic layer knows nothing about
  these):
  - `control_settings.py` — the `ControlSettings` cluster + `SystemState` enum (−1 SAFE, 0
    STAND_BY, 1 MOTORING, 2 IDLING, 3 FIRING), transcribed from the LabVIEW typedefs and
    **confirmed field-for-field against a live capture**.
  - `labview_mapping.py` — `LABEL_TO_PATH` bridges LabVIEW's raw `Flatten To JSON` field labels
    (which have embedded newlines, stray spaces, etc.) to the model's clean snake_case paths;
    `control_settings_from_labview()` / `_to_labview()` convert both ways; `compare_flatten()`
    powers the diff tool.
  - `telemetry.py` — `MonarchTelemetry` envelope + `monarch_parser`. The gateway sends the
    ControlSettings **raw flatten** and Python maps it (so the LabVIEW side does no key-renaming).
  - `simserver_monarch.py` — fake MONARCH gateway streaming real-shaped telemetry.

**Contract convention:** wire JSON keys are clean snake_case defined by the Python models (each
field comments its LabVIEW source label). LabVIEW DBL/SGL → `float`, I8 enums → `int`. Whenever
the `APC_ControlSettings.ctl` typedef changes, re-run the flatten diff (`docs/monarch-flatten-diff.md`)
to keep the model and gateway in lockstep.

## The LabVIEW side (not in this repo)

The LabVIEW project lives at `C:\LabVIEW PROJECT\MONARCH\` on the Windows PC. The gateway VI
(`APC_PC_PythonGateway.vi`, a copy of the connectivity-test `hello-vi.vi`) runs as its own
**read-only** loop, `Flatten To JSON`s the live `PC_ControlSettings` cluster, and sends a
telemetry envelope at 1 Hz. `original-labview-codebase/MONARCH-CODEBASE/` is a curated copy of
the LabVIEW source tree (binary `.vi`s) — **read its `README.md` first**: it documents every VI
(role, call graph, shared-variable I/O, loop rates, as-built gotchas). The sibling folders hold
PNG/PDF/HTML **exports** of the key MONARCH VIs (the HTML files carry terminal labels as
grep-able text; most "DAQmx Custom Scales" VI descriptions are boilerplate — ignore them). The first port target is
`APC_9056_StateMachine.vi` (the 2026 version — `_v2` is an older 2024 draft, not newer).

## Docs

`docs/icd.md` (wire protocol + failure/reconnect semantics), `docs/monarch-control-settings.md`
(the data contract), `docs/monarch-flatten-diff.md` (contract-verification workflow),
`docs/monarch-telemetry.md` (telemetry envelope + the gateway build recipe, incl. the
shadow-mode fields), `docs/hello-vi.md` + `docs/labview-notes.md` (LabVIEW gateway build guides);
`docs/migration-seam.md` (the FLOOR/MIDDLE/BRAIN boundary + prioritized port backlog);
`docs/migration-plan.md` (the phased execution plan A–E: shadow brain → command path +
watchdog proof → bench command → sequencing → commissioning; authority gates + exit criteria;
**authoritative status home**); `docs/phases/` (step-by-step instructions, one file per phase);
`docs/handoff.md` (how to continue this project — what's done, what only humans supply,
task guidance for smaller models, and the invariants that must never be weakened);
`docs/9049-openloop-audit.md` (the cRIO-9049 RT/FPGA audit for open-loop commissioning +
the layered SIL plan + the F3a–F3d as-built defect dispositions — EPT built-in crank
simulator, synthetic pressure traces via `tools/gen_cas_traces.py`, pre-fuel checklist);
`docs/sil0-scope-of-work.md` + `docs/sil1-scope-of-work.md` (**click-level SIL procedures**;
SIL-0 complete 07-11, SIL-1 Steps 0–3 + the 7/7 false-trip matrix complete 07-14 —
Steps 4–5, spark/DI scheduling + drills, are the live next work); `docs/deployed-bringup.md`
(deployed-mode build/deploy procedure + the rules learned at first autonomous bringup,
2026-07-09 — PC apps as EXEs only, single shared-variable host, no builds from out-of-sync
VIs); `docs/command-path-asbuilt.md` (the **verified** PC⇄cRIO command path — source-select,
`PC_HB` ownership, WatchDog, the loss-of-PC SAFE clamp armed in both modes — with per-VI
diagram-page evidence; the "how does the command path actually work as-built" reference);
`docs/9056-warning-policy-asbuilt.md` (the as-built 9056 warning→state-clamp chain — 4-tier
raster limits, per-state arming masks, latch/clear semantics, cylinder error scoring, the
W1–W7 gap list, and the 9056 FPGA RT-stall safe-hold — the Phase-A3 ground truth);
`docs/engine-only-9056-tradeoff.md` (decision memo — **decided 2026-07-16: engine-only
testing runs the 9056 alongside the 9049**; dyno command + all engine-health reads live
on the 9056); `docs/hb-hardening-clicklevel.md` (click-level builds closing the
loss-of-9056 holes: 9049 staleness→SAFE clamp, PC-computed watchdog LEDs, gateway
`operator_requests`); `docs/crio-file-access.md` (WinSCP/PuTTY file access to the cRIOs);
`docs/cRIO9049 Warnings.xlsx` (warning/error reference: definitions + motoring/fired
values) + `docs/cRIO9049 Warning Matrix.xlsx` (the filled 7/7 false-trip record sheet);
`docs/session-handoff-2026-07-11.md` (handoff: autonomous deployment, SIL-0, robustness
gaps, tools — with 07-14/15/16 update blocks; **status itself lives in
`docs/migration-plan.md`**).

## Conventions

- End commit messages with the `Co-Authored-By: Claude ...` trailer; work on a branch off `main`
  and only commit/push when asked.
- Telemetry is the single source of truth: an `ack` means a command passed validation, not that it
  took effect — effects are confirmed by observing subsequent telemetry. After a reconnect, rebuild
  state from telemetry, never from memory.
- Staleness: no telemetry for 3 s ⇒ stop sending commands and hold; LabVIEW safe-holds 5 s after
  Python's heartbeat stops.
