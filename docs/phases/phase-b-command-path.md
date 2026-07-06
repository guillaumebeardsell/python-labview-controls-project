# Phase B — Command Path + Watchdog Proof (detailed instructions)

**Objective:** a hardened Python→LabVIEW command channel whose failure modes are
all proven safe on the bench. This phase *builds* authority plumbing; it grants
none until its exit gate passes.

**Authority level:** none until B4 drills pass. Everything is testable against
the sim and with `source-select = UI` (Python's writes ignored) before that.

**Entry criteria:** telemetry pipeline live (done). A1 is *not* a prerequisite
for B1/B2 (they can run in parallel); B4 wants A2's shadow compare available as
a divergence alarm.

---

## B0 — Close the loss-of-PC question (FIRST — it shapes B3)

*Owner: you (LabVIEW), with my analysis on the export.*

1. ~~Fix the typedef-update error~~ **done (2026-07-06).**
2. ~~Export `APC_9056_TS_loop.vi`~~ **done (2026-07-06).**
3. ~~Trace what consumes the WatchDog outputs~~ **done — OUTCOME: Case 2, worse
   than expected.** The WatchDog subVI sits on the TS_loop diagram **completely
   unwired** — no inputs, no outputs. It runs (reads heartbeats via shared
   variables internally) but `PCnotResponding` is consumed by nothing.

**Remaining B0 work (LabVIEW, now concretely specified):**
- Wire the response: WatchDog's `PCnotResponding` output → `Select` (TRUE → −1,
  FALSE → 3) → `Min` with the warning-integration (DIAG) output that feeds the
  StateMachine's `STATE LIMITATION FROM WARNINGS` input. One Select + one Min at
  the existing call site; stays in LabVIEW (FLOOR logic).
- Set real `*watchdogThreshold` values (front-panel defaults are 0; nothing is
  known to configure them). Suggest: trip within 5 s at the TS-loop rate,
  matching the ICD's 5 s heartbeat semantics.
- Resolve **who toggles `PC_HB`**: it's unknown whether the UI toggles it today
  (if nothing does, the flag would read permanently tripped — likely why it was
  left unwired). Decide per command source: UI toggles it while source=UI;
  Python toggles it while source=PYTHON (B1 already requires this). Until the
  UI side toggles, gate the clamp on source=PYTHON or have the gateway toggle
  it on the UI's behalf — decide at B1 review.

**Definition of done (B0):** the sentence "if `PC_ControlSettings` goes stale
for N seconds, the 9056 does X" is true, written down in
`docs/migration-seam.md`, and N and X are chosen deliberately.

---

## B1 — ICD v0.2: command semantics (design, then freeze)

*Owner: Claude drafts; joint review before anything is built on it.*

Extend `docs/icd.md` to v0.2 with:

1. **One atomic command:**
   ```json
   {"type":"command","id":7,"name":"set_control_settings",
    "params":{"settings":{ …LabVIEW-label flatten of the full PC_ControlSettings… }}}
   ```
   Serialized by `control_settings_to_labview()` so the gateway can
   `Unflatten From JSON` directly into the typedef — zero key-mapping in
   LabVIEW, mirroring telemetry.
2. **Whole-cluster, 1 Hz, idempotent.** While in command, Python sends its
   complete intent every tick (not deltas, not on-change). Consequences: no
   partial-update races, a lost frame heals on the next tick, and the stream
   itself is the liveness signal.
3. **`pc_hb` toggling:** Python flips `pid_control_references.pc_hb` on every
   send. This is what the existing 9056 watchdog stall-counts, so the
   *original* safety mechanism supervises Python directly. `mtr_hb` passes
   through from last telemetry unchanged.
4. **ACK/NACK = validation only** (parse OK, in-range, rate OK, source is
   PYTHON). Effect confirmation = watching `limited_settings` / `system_state`
   in telemetry. NACK carries a machine-readable reason string.
5. **Single-writer + source-select:** exactly one writer of
   `PC_ControlSettings`. Gateway holds a `CommandSource` switch
   (`UI` | `PYTHON`, default `UI`, operator-owned — on the HMI, not settable
   by Python), echoed in every telemetry frame (`command_source` field).
   Commands received while source=UI are NACKed with reason
   `"source is UI"`. **Bumpless handover:** before requesting the switch,
   Python initializes its intent from the last telemetry frame, so the first
   Python frame equals the UI's last one.
6. **E-stop precedence:** e-stop TRUE from *any* source (three UI panels or a
   Python command) latches; Python **cannot** clear it — `clear_emergency_stop`
   from Python is NACKed (`"operator only"`). Encode in the gateway validation.
7. **Failure matrix** (each row gets defined behavior + a B4 drill): Python
   crash mid-command · process frozen (stream continues? no — pc_hb stops
   toggling) · TCP drop · malformed JSON · out-of-range values · command flood
   (>5 Hz ⇒ NACK rate-limit) · source flip mid-stream · stale telemetry on the
   Python side (Python must stop commanding per ICD staleness rule).

**Definition of done (B1):** v0.2 section merged into `docs/icd.md` after joint
review; the source-select UX decision recorded.

---

## B2 — Python command side

*Owner: Claude. No LabVIEW dependency (built against the sim).*

1. `supervisory/monarch/commander.py` — `MonarchCommander`:
   - holds the current `ControlSettings` intent (initialized from telemetry);
   - `tick()`: toggle `pc_hb`, serialize via `control_settings_to_labview()`,
     emit the `set_control_settings` request; respect staleness (no telemetry
     3 s ⇒ stop sending, re-init from telemetry on recovery);
   - tracks ACK/NACK, surfaces NACK reasons, alarms on effect-mismatch
     (commanded vs next `limited_settings`, beyond what the A1 limiter
     predicts).
2. Extend `simserver_monarch.py`: accept `set_control_settings`, validate like
   the gateway will (incl. source-select + e-stop rules), run the **A1-ported
   limiter** against it, reflect results in telemetry, implement a
   `PCnotResponding`-equivalent (stop toggling pc_hb ⇒ sim drops to SAFE).
3. Tests: full loop against the sim — command → ack → telemetry effect;
   every failure-matrix row simulated (kill commander, freeze pc_hb, garbage,
   flood, source=UI NACK, e-stop precedence).

**Definition of done (B2):** all failure-matrix rows pass against the sim.

---

## B3 — LabVIEW gateway write path

*Owner: you, with node-level guidance. Prereq: B0 outcome + B1 frozen.*

In `APC_PC_PythonGateway.vi` (structure mirrors the proven read side):
1. In the session loop's command branch (where `"type":"command"` is matched
   today): parse `name`; for `set_control_settings`, extract the `settings`
   object string.
2. Validate: `Unflatten From JSON` into an `APC_ControlSettings.ctl` constant
   type. Unflatten error ⇒ NACK `"parse"`. Then range/sanity checks (limits
   from an INI or constants — keep the list small; the StateMachine limiter is
   still the real clamp downstream). Source ≠ PYTHON ⇒ NACK `"source is UI"`.
   `clear_emergency_stop` TRUE from Python ⇒ NACK `"operator only"`.
3. On pass: write the cluster to the `PC_ControlSettings` shared variable
   (the same one the UI writes) and ACK with the command id (dynamic id now —
   `Format Into String` on the parsed id, replacing the hello-VI's hardcoded
   ack).
4. Source-select: a `CommandSource` control on the gateway/HMI panel gates the
   write; echo its value into the telemetry envelope (`"command_source":"%s"`).
5. The UI must stop writing `PC_ControlSettings` while source=PYTHON —
   implement in the UI write path (case structure on the same source variable).
   This is the one change outside the gateway; keep it minimal and obvious.

**Definition of done (B3):** with source=UI, Python commands are NACKed and
nothing changes; with source=PYTHON, a command round-trips to a telemetry
effect on the real system.

---

## B4 — Bench failure drills (the authority gate)

*Owner: joint. Scripted, repeated, logged. Rig unpowered / pre-commissioning.*

| # | Drill | Expected outcome |
|---|---|---|
| 1 | Kill Python mid-command (`taskkill`) | pc_hb freezes → `PCnotResponding` trips within N s → B0 response (state→SAFE clamp) → LabVIEW keeps running; Python restart re-inits from telemetry, no glitch |
| 2 | Freeze Python (suspend process) | same as 1 (stream stops) |
| 3 | Pull network / kill TCP | gateway session ends cleanly (error-66 path), listener re-accepts; same watchdog response |
| 4 | Garbage bytes / malformed JSON ×20 | NACK or discard each; session survives; no state change |
| 5 | Out-of-range command | NACK with reason; no write |
| 6 | Command flood (50 Hz) | rate-limit NACKs; gateway loop timing unaffected (telemetry still 1 Hz) |
| 7 | Source flip UI→PYTHON→UI mid-stream | bumpless both ways; frames show `command_source` flipping; no setpoint jump |
| 8 | E-stop from UI while source=PYTHON | state → SAFE regardless; Python clear attempt NACKed; operator clear works |
| 9 | Python-side telemetry staleness (block inbound only) | Python stops commanding within 3 s (its own rule) |

Each drill: run 3×, record the `monarch.jsonl` + gateway log, tick the row.

**Phase exit gate:** all 9 drills pass 3/3; B0 statement holds under drills
1–3; ICD v0.2 published; only then may Phase C grant authority.
