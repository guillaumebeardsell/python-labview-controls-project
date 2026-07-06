# MONARCH Supervisory Migration — Phased Plan

Turns the seam analysis (`docs/migration-seam.md`) into an executable sequence. Each
phase has a fixed **authority level**, concrete Python and LabVIEW deliverables, and
**verifiable exit criteria**. Phases overlap where dependencies allow; nothing advances
Python's authority until the phase gating it is closed.

**This document is the authoritative home of project status** — other docs describe
their own piece and point here. Step-by-step instructions for each phase live in
`docs/phases/` (one file per phase, linked from each section below).

## Current status (2026-07-06)

Foundations — done and verified on the real system:

- [x] Transport + ICD v0.1 validated end-to-end against real LabVIEW 2020 SP1
      (hello-VI experiment, PASS), including disconnect/reconnect resilience.
- [x] `ControlSettings` contract transcribed and confirmed against a live LabVIEW
      `Flatten To JSON` capture (diff → AGREE, all 64 leaves; `tools/compare_flatten.py`
      guards future typedef drift).
- [x] **Read-only telemetry pipeline LIVE**: `APC_PC_PythonGateway.vi` (in the MONARCH
      project) streams the live `PC_ControlSettings` + `CURRENT SYSTEM STATE` (published
      via a new network shared variable) at 1 Hz; Python decodes with 0 unmapped fields
      and records to `monarch.jsonl` (`docs/monarch-telemetry.md`).
- [x] Shadow-mode envelope fields Python-ready (optional; decode+record on arrival).
- [x] Seam analysis + this plan (`docs/migration-seam.md`); loss-of-PC **detection**
      confirmed in `APC_9056_WatchDog.vi` (stall counters on PC_HB/MTR_HB/9049/9056
      heartbeats → `*notResponding` flags); the **response** is unconfirmed pending
      `APC_9056_TS_loop.vi`.

Position: **start of Phase A** (nothing of A1–A3 built yet). B1/B2 can proceed in
parallel. Immediate blockers, all on the LabVIEW-export side: the StateMachine
per-limitation case frames (A1 exactness), `APC_9056_TS_loop.vi` +
`APC_9056_WarningIntegration.vi` exports (A3, B0 — currently behind a typedef-update
error in `APC_9056_TexhControl.vi`), and the operating-procedure spec (D0).

Ground rules that hold in every phase:

- **LabVIEW/cRIO/FPGA keeps the FLOOR** (I/O, interlocks, validation, safe fallback).
  The 9056 StateMachine limiter stays in place permanently as the independent clamp,
  even after Python holds decision authority above it — defense in depth, not a
  transitional crutch.
- **Python-offline == safe hold** must be demonstrable at every authority increase, not
  assumed.
- All Python logic lands as **pure decisions** (`StateMachine.step(view) → requests`)
  with exhaustive unit tests; sockets/clocks stay in the framework.
- No hardware runs exist: everything is verified on the bench against synthetic inputs
  and the plant simulator.

---

## Phase A — Shadow brain (authority: none; read-only)

*Detailed instructions: [phases/phase-a-shadow-brain.md](phases/phase-a-shadow-brain.md)*

Goal: Python computes every supervisory decision the 9056 makes today, verified
against spec and bench captures — without sending anything.

**A1. Port `APC_9056_StateMachine`** *(next up — not started)*
- Python `MonarchStateMachine`: MIN-aggregation over {requested mode, warnings limit,
  e-stop → −1, force-motoring → ≤1, force-idling → ≤2}, increase-by-1 rule,
  `ForceState`/`ManualState` override, and the MAX-LEVEL-OF-CONTROL limiter producing
  `limited_settings`.
- Unit tests over the full transition matrix (every state × every input combination),
  plus the vent/feed polarity cases and the combustion invariant (leaving
  IDLING/FIRING ⇒ NG and O2 feed modes clamp to 0).
- *Input needed:* zoomed export of the per-limitation case frames in the current
  (2026) VI to pin exact clamp values; the empty "specific conditions" case is
  confirmed empty.

**A2. Shadow-compare harness**
- Pre-wire the shadow-mode envelope fields in the gateway (`warnings_limit`,
  `manual_state`, `force_state`, `limited_settings` — Python side already decodes;
  see `docs/monarch-telemetry.md` §Shadow-mode extras).
- `tools/shadow_compare.py`: replay `monarch.jsonl` (or watch live), recompute
  state + limits from inputs, diff against LabVIEW's outputs, report divergences.
- Bench input sweeps from the UI (requested mode, forces, e-stop, warning injection)
  to generate coverage.

**A3. Port the warning → state policy**
- Model `APC_9056_WarningIntegration` (+ the severity map: yellow=info self-clearing,
  orange→IDLING cap, red→MOTORING cap, black→SAFE+vent; latching until operator clear)
  producing `STATE LIMITATION FROM WARNINGS` in Python.
- *Input needed:* exports of `APC_9056_TS_loop.vi` and `APC_9056_WarningIntegration.vi`
  (also closes the `PCnotResponding` question — see B0).

**Exit criteria:** unit suite covers the full matrix; shadow compare shows 0
unexplained divergences across bench sweeps; any real divergence is dispositioned
(LabVIEW bug vs. port bug — with the LabVIEW side unvalidated, disagreement is a
finding, not automatically a Python defect).

---

## Phase B — Command path + watchdog proof (authority: none until B-exit; this phase *builds* the authority plumbing)

*Detailed instructions: [phases/phase-b-command-path.md](phases/phase-b-command-path.md)*

Goal: a hardened Python→LabVIEW command channel whose failure modes are all proven
safe on the bench. This is the gate for everything after it.

**B0. Close the loss-of-PC question** *(first — it shapes B3)*
- Trace `APC_9056_TS_loop.vi`: what consumes `PCnotResponding`?
  - If it already forces SAFE / caps the state: document thresholds; the command path
    simply must satisfy it.
  - If it's indicator-only: **add the response in LabVIEW** (feed `PCnotResponding`
    into the state limitation, clamping to SAFE) before any Python authority.

**B1. ICD v0.2 — command semantics**
- One command, atomic: `set_control_settings` carrying a **complete desired
  `PC_ControlSettings`**, serialized with `control_settings_to_labview()` (real
  LabVIEW labels), so the gateway can `Unflatten From JSON` straight into the typedef
  — no key mapping on the LabVIEW side, mirroring the telemetry direction.
- Whole-cluster writes (mirrors how the UI writes today; no partial-update races).
  Python always sends its full intent at 1 Hz while in command.
- **`pc_hb` toggling:** Python flips `pid_control_references.pc_hb` on every send, so
  the *existing* `APC_9056_WatchDog` stall-counter directly supervises Python. MTR HB
  passes through unchanged from the last telemetry.
- ACK = gateway-side validation only (parse, ranges, rate); *effect* confirmation is
  observing `limited_settings`/`system_state` in telemetry. NACK carries a reason.
- **Single-writer rule:** exactly one writer of `PC_ControlSettings` at a time. A
  gateway-side source-select (`UI` | `PYTHON`, default `UI`) with the active source
  shown on the HMI and echoed in telemetry. Switching sources requires the values to
  be handed over bumplessly (Python initializes its intent from last telemetry).
- Failure matrix to design against (each with defined behavior): Python crash
  mid-command; TCP drop; stale/frozen commands (pc_hb stops); malformed JSON; command
  flood; source-select flip mid-sequence; conflicting e-stop (e-stop from *any* source
  always wins, latches, and cannot be cleared by Python).

**B2. Python side**
- `Supervisor` command emission (already designed: `CommandRequest` → ack tracking),
  a `MonarchCommander` that renders `ControlSettings` intents, staleness hold-off
  (no telemetry ⇒ stop commanding), and reconnect-rebuild-from-telemetry.
- Extend `simserver_monarch` to accept `set_control_settings`, run the *ported* limiter
  against it, and reflect the result in telemetry — full closed loop with no LabVIEW.

**B3. LabVIEW gateway write path**
- Gateway VI: parse command → validate → write shared variable (when source=PYTHON) →
  ACK/NACK. Read-only telemetry loop unchanged. Keep the gateway out of the control
  path: it writes the same `PC_ControlSettings` the UI writes; the StateMachine still
  limits everything downstream.

**B4. Bench failure drills (the exit gate)**
- Kill Python mid-command ⇒ `PCnotResponding` trips within threshold ⇒ verified safe
  response (B0 behavior), system recovers when Python returns.
- Pull the network / freeze the process (pc_hb constant) / send garbage / flood ⇒ same
  safe outcome, every time, demonstrated live on the bench.

**Exit criteria:** all failure drills pass repeatably; round-trip command→ACK→
telemetry-effect verified; source-select handover is bumpless; e-stop precedence
proven. Only after this may any phase grant Python authority.

---

## Phase C — Python in command on the bench (authority: setpoints + mode requests, behind the LabVIEW limiter)

*Detailed instructions: [phases/phase-c-bench-command.md](phases/phase-c-bench-command.md)*

Goal: Python is the acting supervisor for bench operation — no engine, hardware not
ready — exercising real authority against the real cRIOs.

- Python drives `requested_mode`, control-loop modes (safe/manual/closed-loop), and
  setpoints for the 9056 MIDDLE loops via the B command path; LabVIEW StateMachine
  keeps limiting; FLOOR untouched.
- Operator interaction: keep the LabVIEW HMI for monitoring + e-stop + source-select;
  Python exposes a minimal operator surface (CLI first) for intents. (A fuller
  operator UI is deliberately out of scope until sequences exist.)
- Shadow compare (A2) keeps running in reverse: LabVIEW's limiter output vs Python's
  predicted limit — divergence alarms.
- Soak: hours-long bench runs with fault injection; verify no drift, no leaks, clean
  reconnects.

**Exit criteria:** a scripted bench session (mode walks, setpoint changes, forced
warnings, e-stop, kill-and-recover) executes entirely under Python command with zero
unsafe outcomes and zero unexplained limiter divergences.

---

## Phase D — Sequencing engine (greenfield; authority: sequences issue the same commands C already proved)

*Detailed instructions: [phases/phase-d-sequencing.md](phases/phase-d-sequencing.md)
(includes the procedure-spec template for D0)*

Goal: the layer that doesn't exist in LabVIEW — automated procedures — built
test-first in Python.

- **D0. Operating-procedure spec** *(team input — the critical path)*: cold-start /
  purge / motoring→light-off / normal shutdown / vent + recovery / misfire recovery /
  WF quality check, as steps with guards, holds, timeouts, and abort conditions. Even
  informal notes suffice; I'll formalize them.
- **D1. Sequence framework**: declarative steps (`command`, `wait_for(condition,
  timeout)`, `hold`, `branch`, `abort_to(state)`), every sequence interruptible, every
  abort path lands in SAFE or STAND_BY, invariants checked at every step (combustion
  stop ⇒ NG+O2 cut). Pure-decision core, so sequences unit-test like everything else.
- **D2. Plant simulator upgrade**: extend the MONARCH sim with enough plant response
  (pressures, temps, warning injection) for sequences to run closed-loop offline;
  property-based tests (random fault injection mid-sequence ⇒ always safe).
- **D3. Bench execution** of the non-combustion sequences (venting, purge, WF checks,
  thermal warm-up) as hardware becomes available — these are also the sequences
  commissioning needs first.

**Exit criteria:** each authored sequence has spec-traceable tests, survives random
fault injection in sim, and the non-combustion subset runs on the bench.

---

## Phase E — Commissioning support & expansion (authority: as commissioned, step by step)

*Detailed instructions: [phases/phase-e-commissioning.md](phases/phase-e-commissioning.md)*

- Use D sequences to drive commissioning itself (cold flow → motoring → first fire),
  each new plant capability unlocked only after its bench drill.
- Author the **temporal warning rules** the original developer left unbuilt
  ("X low for Y s while in state Z ⇒ action") in the Python policy layer.
- **Setpoint scheduling** (operating-point tables → loop setpoints) as data, not code.
- Revisit what remains in the LabVIEW BRAIN (UI conditioning, MTR commanding) for
  later consolidation; the FLOOR never moves.

---

## Dependency graph & parallelism

```
A1 StateMachine port ──► A2 shadow harness ──► (C divergence alarm)
A3 warning policy ────┘
B0 TS_loop trace ──► B1 ICD v0.2 ──► B2 Python cmd ──► B4 drills ──► C bench command ──► E
                                └──► B3 gateway write ┘                    ▲
D0 procedure spec ──► D1 framework ──► D2 sim ──► D3 bench sequences ──────┘
```

Parallel now: A1/A2/A3 (needs exports), B1/B2 (needs nothing), D0 (needs the team),
D1/D2 (can start on framework + sim before D0 lands, using placeholder sequences).

## Inputs owed by the team (blocking markers)

| Input | Blocks | Who |
|---|---|---|
| Zoomed export: StateMachine per-limitation case frames | A1 exactness | you (LabVIEW export) |
| Exports: `APC_9056_TS_loop.vi`, `APC_9056_WarningIntegration.vi` | A3, B0 | you (fix the typedef-update error first) |
| Operating procedures (informal ok) | D0→D1 content | you + team |
| Decision: source-select UX (where the UI/PYTHON switch lives) | B3 detail | joint, during B1 review |
