# MONARCH Supervisory Migration — Phased Plan

Turns the seam analysis (`docs/migration-seam.md`) into an executable sequence. Each
phase has a fixed **authority level**, concrete Python and LabVIEW deliverables, and
**verifiable exit criteria**. Phases overlap where dependencies allow; nothing advances
Python's authority until the phase gating it is closed.

**This document is the authoritative home of project status** — other docs describe
their own piece and point here. Step-by-step instructions for each phase live in
`docs/phases/` (one file per phase, linked from each section below).

## Current status (2026-07-16)

**Phases A & B COMPLETE and live-verified. Both cRIOs run AUTONOMOUS on hardware
(cold-boot verified). SIL-0 COMPLETE (9049 analytics math validated). SIL-1
half-complete: the diagnostics/protection half is DONE — the false-trip/latch
matrix passed 7/7 on the real 9049 — the actuation half (Steps 4–5) remains.**
The frontier is now LabVIEW/hardware, not Python.

- **SIL-1 (2026-07-14, bench)** — Steps 0–3 done; **Step 2 CLOSED: Trig0 follows
  the sim** (no SIL-2 encoder needed for CAS-acquisition testing); **Step 6
  false-trip matrix COMPLETE 7/7** (synthetic pressure via the CAS_loop sim
  branch; every warning/error trips on exactly its target cylinders, latches,
  clears; record sheet `docs/cRIO9049 Warning Matrix.xlsx`). Four as-built
  defects found + dispositioned (audit F3a–F3d): non-finite-CA50 noise trips
  (cured: sim pressure + the user-built **SYSTEMSTATE ≥ 2 state gate** in
  `CombCluster2Array`, live-verified); **thresholds never loaded since build**
  (`Pcyl_Diag` "Load INI on startup" saved FALSE — fixed; must be carried into
  deployed builds); display order verified correct (name-bound); **misfire
  checks are one-sided low-side** (misfire-from-IMEP INERT until `Expected
  IMEP` is wired from IMEP-REF — decision: no Abs; any `Pcyl_Diag` change ⇒
  re-run the matrix as regression gate). **Remaining: Steps 4–5** (state-gated
  spark/DI scheduling + drills) — click-level SOW: `docs/sil1-scope-of-work.md`
  (4a–4f, 5a–5h). Pending architecture decision for engine-only running:
  `docs/engine-only-9056-tradeoff.md`.

- **Phase A** — done; live shadow-compare 100% across all 5 states + inputs.
- **Phase B** — **exit gate passed 2026-07-09.** Command path built end-to-end
  (gateway does the full validation ladder); loss-of-PC watchdog live-verified.
  *Caveats surfaced 2026-07-11:* B4-7/8/9 drills were operator-run but not
  logged (only B4-1..6 in `docs/drill-logs/`); real gaps remain before
  firing-relevant authority — no `UI_HeartBeat`, thin gateway setpoint
  validation, unauth TCP, no content-staleness guard. See
  `docs/session-handoff-2026-07-11.md` §robustness.
- **Autonomous deployment (NEW, this session)** — both cRIOs boot startup
  `.rtexe`s, PC apps as EXEs, Python observes/commands; cold-boot verified.
  Five deployment bugs fixed. Full runbook: `docs/deployed-bringup.md`.
- **SIL-0 — COMPLETE (2026-07-11)** — 9049 HRL/IMEP/CA50 math validated vs known
  truth (425 comparisons all within tol) via `APC_SIL0_HRL_Desktop.vi` +
  `tools/compare_hrl.py`, incl. MAPO/IMEPstd columns. `docs/9049-openloop-audit.md`
  §7; click-level SOW: `docs/sil0-scope-of-work.md`. Threshold profiles derived
  (`tools/tune_thresholds.py` → `parameter-files/CylWarningLevels.xml` motoring +
  `tools/gen_warning_matrix.py` → all-armed drill XML); the latch tests ran in
  SIL-1 (Step 6, complete — see above).
- **Phase C** — Python built; C3/C4/C5 unverified (needs bench + 2nd operator).
- **Phase D** — framework + sim built; blocked on the **D0 procedure sheets (team)**.
- **Next:** SIL-1 Steps 4–5 (`docs/sil1-scope-of-work.md`): spark/DI scheduling
  from both writers + the drills (watchdog, sync-loss, state-gate walk,
  CylPressError veto, F4 echo capture, e-stop, recording). Team inputs owed:
  engine mechanical peak-pressure rating (drill Pmax limits are
  statistics-derived, uncapped), procedure sheets, bench + 2nd operator.
- Suite **191 green** (was 108 at the 2026-07-07 block below).

<details><summary>Prior status (2026-07-07) — Phase A validation detail</summary>

**Phase A logic validation COMPLETE (2026-07-07).** With the full A2.1 pre-wire
live (WarningIntegration→StateMachine warnings wire made; `warnings_limit`/
`manual_state`/`force_state`/`limited_settings` in the envelope; `system_state`
re-tapped to the 9056 StateMachine's fresh output), live shadow compare now
agrees across the **entire input space and all five states**: ForceState/
ManualState override sweep (incl. SAFE), requested-mode walk 0→3 to FIRING (after
clearing the latched warning), e-stop press→SAFE, and the warning clamp. Latest
210-frame walk: **SYSTEM STATE 208/209 (99.5%), Limited_ControlSettings 209/209
(100%)** — the sole state miss is a one-frame gateway snapshot-coherency artifact
on the e-stop press (input vs output cluster flattened a sample apart; LabVIEW
internally consistent), NOT a port defect. Full evidence + dispositions in
`docs/shadow-findings.md`. Suite 108 green. **Recommended before Phase B:** the
coherent single-snapshot gateway publish (`current_state` + SM-consumed inputs)
to eliminate the residual skew before command timing matters.

B-progress (2026-07-07): **B1 decisions frozen** (watchdog threshold 5 s = 250
loop-counts at ~20 ms; PC_HB toggler = option (a), UI also toggles) — the only
soft B1 item left is the `CommandSource` HMI switch. **B0 loss-of-PC response is
built, wired, and live-verified** (`PCnotResponding`/`9049notResponding` → Select
(−1:3) → Min into the SM warnings input; a real PC drop drove SYSTEM STATE→SAFE,
shadow compare 100%; see `docs/migration-seam.md`); threshold **set to 250 counts
(5 s) and the loss-of-PC drill re-verified at it** (pc_hb freeze → SAFE in ~5 s,
100%/100%; `docs/shadow-findings.md`). Next real build: **B3 gateway write path**.

</details>

<details><summary>Prior status (2026-07-06)</summary>

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
      confirmed in `APC_9056_WatchDog.vi`, and — from the `TS_loop` export
      (2026-07-06) — the **response confirmed absent**: the WatchDog call is unwired,
      so `PCnotResponding` gates nothing. Building the response is B0 (now concretely
      specified in the phase-B file).

Position (updated 2026-07-09): **PHASE B COMPLETE — exit gate passed.** All
nine B4 drills passed 3×+ against the live gateway (1–6 machine-run, 7–9
operator-run; log in `docs/drill-logs/`); the loss-of-PC watchdog held under
every kill/freeze/stall; ICD v0.2 frozen and bench-corrected; the command
path, source-select, operator-request mirror, and e-stop
recovery-by-demotion are all live-verified. **Python may hold bench command
authority (Phase C is open).** C0's HMI affordances are largely in place
(the B3.b switch + effective-LED, as-built on the `UI_Main` panel); next:
C3 handover rehearsal by a second operator, C4 scripted acceptance session,
C5 soak — plus the D0 procedure sheets in parallel.

Position (updated 2026-07-07): **the Python side of every phase is built.**
Phase A: A1/A2/A3 built; **live validation complete — 100% agreement, all 5
states, all inputs** (`docs/shadow-findings.md`). Phase B: B1 drafted (ICD v0.2
§7, review pending), B2 built + drill-tested; B0/B3 are LabVIEW work, fully
specified. Phase C Python: operator CLI + reverse shadow alarm built (bench use
gated on B exit). Phase D: sequencing framework + sim plant model + draft
venting/purge/thermal-warmup sequences built and fault-injection tested
(content gated on D0 sheets). Phase E engines: temporal rules + scheduler built
(values TBD(team)). `Settings9049` modeled (flatten confirmation pending); CI
runs the suite (191 tests) on 3.10/3.12. **What remains is LabVIEW work, joint
decisions, and team-supplied content — see `docs/handoff.md`.** **All export blockers cleared 2026-07-06**: StateMachine per-frame export
(A1.0 answered — clamp values, sort-based MIN, absolute ManualState override
confirmed), `TS_loop` (B0 answered — WatchDog unwired, response must be built) and
`WarningIntegration` (A3 input) both in `original-labview-codebase/`. Remaining
team inputs: the operating-procedure spec (D0), plus B0's threshold/PC_HB-toggling
decisions at B1 review.

</details>

Ground rules that hold in every phase:

- **LabVIEW/cRIO/FPGA keeps the FLOOR** (I/O, interlocks, validation, safe fallback).
  The 9056 StateMachine limiter stays in place permanently as the independent clamp,
  even after Python holds decision authority above it — defense in depth, not a
  transitional crutch.
- **Python-offline == safe hold** must be demonstrable at every authority increase, not
  assumed.
- All Python logic lands as **pure decisions** (`StateMachine.step(view) → requests`)
  with exhaustive unit tests; sockets/clocks stay in the framework.
- No *engine* runs exist. As of 2026-07-11 both cRIOs **do** run deployed on real
  hardware (autonomous startup apps, cold-boot verified) and the 9049 analytics are
  SIL-validated against synthetic truth — but nothing has been motored or fired.
  Supervisory logic is verified on the bench against synthetic inputs + the sim.

---

## Phase A — Shadow brain (authority: none; read-only)

*Detailed instructions: [phases/phase-a-shadow-brain.md](phases/phase-a-shadow-brain.md)*

Goal: Python computes every supervisory decision the 9056 makes today, verified
against spec and bench captures — without sending anything.

**A1. Port `APC_9056_StateMachine`** *(DONE — validated live, all 5 states)*
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

**A2. Shadow-compare harness** *(DONE — envelope pre-wired + re-tapped; live 100%)*
- Pre-wire the shadow-mode envelope fields in the gateway (`warnings_limit`,
  `manual_state`, `force_state`, `limited_settings` — Python side already decodes;
  see `docs/monarch-telemetry.md` §Shadow-mode extras).
- `tools/shadow_compare.py`: replay `monarch.jsonl` (or watch live), recompute
  state + limits from inputs, diff against LabVIEW's outputs, report divergences.
- Bench input sweeps from the UI (requested mode, forces, e-stop, warning injection)
  to generate coverage.

**A3. Port the warning → state policy** *(DONE — WarningIntegration ported + wired live)*
- Model `APC_9056_WarningIntegration` (+ the severity map: yellow=info self-clearing,
  orange→IDLING cap, red→MOTORING cap, black→SAFE+vent; latching until operator clear)
  producing `STATE LIMITATION FROM WARNINGS` in Python.
- *Input needed:* exports of `APC_9056_TS_loop.vi` and `APC_9056_WarningIntegration.vi`
  (also closes the `PCnotResponding` question — see B0).

**Exit criteria:** unit suite covers the full matrix; shadow compare shows 0
unexplained divergences across bench sweeps; any real divergence is dispositioned
(LabVIEW bug vs. port bug — with the LabVIEW side unvalidated, disagreement is a
finding, not automatically a Python defect).

**MET (2026-07-07).** Live shadow compare agreed across all five states via both
the requested-mode and force-override paths, plus e-stop and the warning clamp
(latest walk: state 208/209, limiter 209/209). Every residual is dispositioned in
`docs/shadow-findings.md` as a telemetry-timing artifact, not a port defect. **One
known limit:** the 1-per-tick step-up *rate limiter* is not observable at the 1 Hz
sample of the ~50 Hz loop (both converge between samples) — carried to Phase B
(iterate `decide()` to a fixed point, or sample faster). Logic validation complete.

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
| ~~Zoomed export: StateMachine per-limitation case frames~~ | A1 exactness | ✅ done 2026-07-06 (per-frame re-export; A1.0 answered) |
| ~~Exports: `APC_9056_TS_loop.vi`, `APC_9056_WarningIntegration.vi`~~ | A3, B0 | ✅ done 2026-07-06 (B0 answered: response absent, must be built) |
| B0 decisions: watchdog thresholds + who toggles `PC_HB` per source | B0/B3 | joint, at B1 review |
| Operating procedures (informal ok) | D0→D1 content | you + team |
| Decision: source-select UX (where the UI/PYTHON switch lives) | B3 detail | joint, during B1 review |
