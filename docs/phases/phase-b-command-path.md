# Phase B — Command Path + Watchdog Proof (detailed instructions)

> **Status (2026-07-07):** **B0 BUILT + WIRED + LIVE-VERIFIED** — the refreshed
> WatchDog is wired (`PCnotResponding`/`9049notResponding` → Select (−1:3) → Min
> into the SM warnings input); a real PC drop drove `SYSTEM STATE → SAFE` with
> step-by-1 recovery, shadow compare 100% (`docs/migration-seam.md`). Threshold
> being finalized at **250 counts (5 s)** — note the sizing trap: the count is
> ~20 ms control-loop ticks and must be several `PC_HB` (~1 Hz) periods, so 50
> counts (1 s) false-trips; 250 = 5 s is correct. **B1 FROZEN** — ICD v0.2 §7:
> 5 s threshold; UI toggles `PC_HB` too; `UI_HeartBeat` follow-on. Only soft B1
> item left: the `CommandSource` HMI switch. **B2 BUILT + VERIFIED** —
> `commander.py`, the commandable sim gateway running the A1 StateMachine, 13
> failure-matrix tests green, end-to-end TCP run. Next real build: **B3 gateway
> write path** → B4 bench drills (re-run the loss-of-PC drill at 250 counts).

**Objective:** a hardened Python→LabVIEW command channel whose failure modes are
all proven safe on the bench. This phase *builds* authority plumbing; it grants
none until its exit gate passes.

**Authority level:** none until B4 drills pass. Everything is testable against
the sim and with `source-select = UI` (Python's writes ignored) before that.

**Entry criteria:** telemetry pipeline live (done). A1 is *not* a prerequisite
for B1/B2 (they can run in parallel); B4 wants A2's shadow compare available as
a divergence alarm.

**LabVIEW changes in this phase:** B0 (wire the WatchDog + SAFE clamp in
`APC_9056_TS_loop.vi`) and B3 (gateway command branch, `CommandSource`
shared variable, UI single-writer gate). B1/B2/B4 need no LabVIEW edits
(B4 *exercises* the B0/B3 work).

---

## B0 — Close the loss-of-PC question (FIRST — it shapes B3)

*Owner: you (LabVIEW), with my analysis on the export.*

1. ~~Fix the typedef-update error~~ **done (2026-07-06).**
2. ~~Export `APC_9056_TS_loop.vi`~~ **done (2026-07-06).**
3. ~~Trace what consumes the WatchDog outputs~~ **done — OUTCOME: Case 2, worse
   than expected.** The WatchDog subVI sits on the TS_loop diagram **completely
   unwired** — no inputs, no outputs. It runs (reads heartbeats via shared
   variables internally) but `PCnotResponding` is consumed by nothing.

**Remaining B0 work — LabVIEW changes required (node-by-node, in
`APC_9056_TS_loop.vi` at the StateMachine call site):**

1. **Wire the WatchDog call.** *(Updated 2026-07-07: the VI internals were
   refreshed — four proper stall counters + a new `Iteration Time [ms]`
   indicator — and the UI now toggles `PC_HB` (B3.c step 4 done), so only the
   call-site wiring remains.)*
   - *Inputs:* the four `*watchdogThreshold` terminals. The threshold counts
     **iterations** of the ~50 Hz control loop, so use the new indicator:
     `5000 / Iteration Time [ms]` → `To I32` → the threshold inputs (≈ **250**
     at ~20 ms) — the 5 s intent stays explicit on the diagram and survives
     loop-rate changes. Wire all four channels (defaults are 0 = trip on the
     first unchanged sample).
   - *Output:* `PCnotResponding` (Boolean). No source gate needed — the UI
     toggle is live, so the clamp arms in both modes per ICD §7.5.
2. **Build the clamp:** `PCnotResponding` → **`Select`** (TRUE → I8 constant
   `−1`, FALSE → I8 constant `3`) → one input of a **`Min`** (Comparison →
   Max & Min, use the min output).
3. **Splice into the warnings input:** delete the segment of the wire feeding
   the StateMachine's `STATE LIMITATION FROM WARNINGS` terminal (from the DIAG
   VI — or the front-panel control if that input turns out to be unwired, per
   `docs/shadow-findings.md`); wire that source into the `Min`'s other input,
   and the `Min` output into the StateMachine terminal. Net effect: warnings
   path unchanged in normal operation; a PC stall clamps the state to SAFE via
   the exact mechanism every other limit uses.
4. **DECIDED (2026-07-07, ICD §7.5): the UI toggles `PC_HB` too**, so the
   clamp is armed in **both** modes — no source gating. Threshold: 5 s
   (= ceil(5 s / TS-loop period) iterations). Implementation of the UI toggle
   is in B3.c step 4; **sequencing note:** if B0's clamp wiring lands before
   the UI toggle does, gate the Select on `CommandSource = PYTHON` temporarily
   and remove the gate in the same change-set as B3.c (otherwise a frozen
   `PC_HB` under source=UI would trip immediately).
5. **Recommended while in the diagram** (from `docs/shadow-findings.md`): the
   WarningIntegration VI's `9049 not responding` / `9056 FPGA not responding`
   booleans are indicator-only. Two more `Select`(−1:3) → include in the same
   `Min` (Min accepts only 2 inputs — chain two Mins, or Build Array → Array
   Max & Min). That closes the same detection-without-response gap for the
   engine controller.
6. Deploy and verify. Note (verified in `MONARCH.lvproj`): the project has
   **no RT-EXE build specifications** — the cRIO code runs deployed-from-project
   (Run on the RT main from the Project Explorer), so "redeploy" here means
   re-run/re-deploy from the project, not rebuilding an executable. Bench check:
   stop toggling `PC_HB` (or kill Python once B2's commander is driving) ⇒
   telemetry shows `warnings_limit = −1` and `system_state → −1` within ~5 s.

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
*Status: **FROZEN 2026-07-07** (docs/icd.md §7). Decisions: 5 s threshold;
option (a) — UI toggles `PC_HB` (clamp ungated once B3.c lands);
`UI_HeartBeat` follow-on specified. Remaining soft default: the
`CommandSource` switch lives on the HMI System screen unless the team
objects during B3.*

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
*Status: DONE (2026-07-06) — `supervisory/monarch/commander.py` +
`simserver_monarch.py` rebuilt around `MonarchGatewaySim` (runs the real
A1-ported `state_machine.decide`, ICD v0.2 validation, pc_hb stall→SAFE);
`tests/test_monarch_commander.py` covers drills 1/2/4/5/6/7/8/9; TCP
end-to-end verified.*

---

## B3 — LabVIEW gateway write path

*Owner: you, with node-level guidance. Prereq: B0 outcome + B1 frozen.*

**LabVIEW changes required — three VIs.** The gateway gets the write path; the
UI gets the single-writer gate; the shared-vars library gets one variable.

*B3.a — `APC_PC_PythonGateway.vi`: the command branch, node by node.*
1. **Route by name.** Inside the existing `"type":"command"` match (the ack
   branch from the hello build): add a second `Match Pattern` on the line for
   `"name":"set_control_settings"` → Case structure. (The old hardcoded-ack
   reply is replaced by this branch.)
2. **Parse id + settings with `Unflatten From JSON` + its `path` input** (no
   string surgery):
   - id: `Unflatten From JSON` — *JSON string* = the received line, *path* =
     string array `["id"]`, *type* = I32 constant.
   - settings: second `Unflatten From JSON` — *path* = `["params","settings"]`,
     *type* = an `APC_ControlSettings.ctl` constant (drag the typedef onto the
     diagram). This inverts the telemetry flatten exactly — no key mapping.
   - Either node's error out ⇒ NACK reason `"parse"` (clear the error after).
3. **Validation chain** (a ladder of Case structures, first failure wins;
   each failure produces a reason string, no write):
   - `CommandSource` ≠ PYTHON ⇒ `"source is UI"`.
   - Unbundle `CLEAR EMERGENCY STOP` = TRUE ⇒ `"operator only"`.
   - Range checks: unbundle `Speed ref` → `In Range and Coerce`-style
     comparison against constants (start with just speed; the StateMachine
     limiter remains the real clamp) ⇒ `"range: Speed ref"`.
   - Optional rate limit: count commands in the last second (Tick Count shift
     register); >5 ⇒ `"rate"`.
4. **Accept path:** write the unflattened cluster to the **`PC_ControlSettings`
   shared variable** (the same variable the UI writes; drag from the library,
   Access Mode → Write). Nothing else — the 9056 consumes it exactly as it
   consumes UI writes.
5. **Dynamic ACK/NACK** (replaces the hardcoded ack constant):
   `Format Into String`, format
   `{"type":"command_ack","id":%d,"accepted":%s,"reason":"%s"}\r\n`
   ('\' Codes Display), args: parsed id (I32), accepted boolean → Select
   `true`/`false` (%s), reason string (empty when accepted). → the existing
   `TCP Write` on the connection ID.
6. **Echo the source in telemetry:** extend the telemetry format string with
   `,"command_source":"%s"` (note the quotes — it's a JSON string) and wire
   `CommandSource` → Select (`UI`/`PYTHON` string constants). Python already
   decodes this field.

*B3.b — `CommandSource` itself.*
- Create it as a **shared variable** (`APC_SharedVars.lvlib`, type: Boolean or
  a UI|PYTHON enum typedef, network-published) so the gateway, the UI, and the
  9056 (if B0 option (a) is chosen) all read one value. Deploy.
- **[DECISION — B1 review]:** where the operator flips it — the UI System
  screen (recommended: it's an operating-mode control, and the HMI is where
  e-stop lives) vs. the gateway front panel (simpler, but hidden). Either way
  it is operator-owned: nothing in the command path may write it.

*B3.c — `APC_PC_UI_Main.vi` (and any other UI writer): the single-writer gate.*
1. Find **every** write node targeting the `PC_ControlSettings` shared
   variable (Project Explorer → right-click the variable → *Find → Search
   Scope: project*, or Edit → Find on the UI diagrams). A binary scan of the
   raw codebase narrows the hunt: on the PC side, only **`APC_PC_UI_Main.vi`**
   (and the gateway, read-only) reference the variable at all —
   `APC_PC_UI_System.vi`/`_Errors.vi` don't — so expect the writer(s) there.
   If there are several writes, they all get the same gate.
   - **Build-spec caveat (verified in `MONARCH.lvproj`):** `APC_PC_UI_Main.vi`
     is the source of the **`APC_Monarch` EXE** build spec. If the control room
     runs the built executable rather than the VI in the dev environment, the
     gate change requires **rebuilding and redeploying `APC_Monarch`** — decide
     which mode operations uses and keep it consistent through Phase B/C.
2. Wrap each write in a Case structure on `CommandSource` — **a redirect, not
   a suppression (ICD §7.7)**: **UI case** = existing write to
   `PC_ControlSettings`, untouched; **PYTHON case** = the same cluster value
   writes to the new **`PC_OperatorRequests`** shared variable instead (create
   it in `APC_SharedVars.lvlib` under the 9049 target, bound to
   `APC_ControlSettings.ctl`, exactly like `PC_ControlSettings`). The
   operator's inputs keep flowing in both modes; Python consumes them from
   telemetry and decides. Keep the case visually obvious.
   - Gateway side: forward it — add `,"operator_requests":%s` to the telemetry
     envelope with a `Flatten To JSON` of the `PC_OperatorRequests` read (same
     pattern as `limited_settings`). Python already decodes and mirrors it
     (`supervisory/monarch/operator_mirror.py`).
3. While source=PYTHON the UI keeps *displaying* everything (reads are
   untouched); only its write is suspended. On flip-back to UI the panel's
   current control values win again — brief the operators that controls should
   match telemetry before handing back (the C3 handover procedure makes this
   explicit).
4. **UI heartbeat toggle** ✅ **done (2026-07-07)** — implemented in
   **`APC_PC_UI_System.vi`** (verified in the per-frame export): feedback node
   → NOT → `PC_HB` in the PID-references bundle, once per System-loop
   iteration, relayed via the `PC_GlobalVariables_PIDsyst2main` global through
   `UI_Main` into the `PC_ControlSettings` shared variable. Placement bonus:
   the flag only reaches the 9056 changing if the System loop, the global
   relay, AND `UI_Main`'s write loop are all alive — it supervises the whole
   UI application. Residual check: confirm `UI_Main` forwards the cluster
   continuously (watch `settings…pc_hb` alternate in `monarch_listen`
   frames); if it's on-change-only, the toggle stalls between operator
   actions and will false-trip. Consequence: the B0 clamp can be armed
   **ungated** (no interim source=PYTHON gate needed).
5. **Follow-on, response TBD (ICD §7.5): `UI_HeartBeat`** — add a standalone
   network shared variable (house pattern, like `9049_HeartBeat`) toggled by
   the UI main loop regardless of source; watch it as a fifth WatchDog channel
   so a dead UI is detectable **while Python holds authority** (the case
   `PC_HB` can't cover). Phase-in: lamp + Python-side reaction first; the
   LabVIEW clamp value is a commissioning decision (conservative default:
   SAFE).

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
