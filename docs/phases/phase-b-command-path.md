# Phase B — Command Path + Watchdog Proof (detailed instructions)

> **Status (2026-07-07):** **B0 BUILT + WIRED + LIVE-VERIFIED** — the refreshed
> WatchDog is wired (`PCnotResponding`/`9049notResponding` → Select (−1:3) → Min
> into the SM warnings input); a real PC drop drove `SYSTEM STATE → SAFE` with
> step-by-1 recovery, shadow compare 100% (`docs/migration-seam.md`). Threshold
> **set to 250 counts (5 s) and the loss-of-PC drill re-verified at it**: `pc_hb`
> freeze → `warnings_limit=−1` → `SYSTEM STATE→SAFE` in ~5 s, step-by-1 recovery,
> shadow compare **100%/100%** (`docs/shadow-findings.md`). Sizing trap noted: the
> count is ~20 ms control-loop ticks and must be several `PC_HB` (~1 Hz) periods,
> so 50 counts (1 s) false-trips; 250 = 5 s is correct. **B1 FROZEN** — ICD v0.2
> §7: 5 s threshold; UI toggles `PC_HB` too; `UI_HeartBeat` follow-on. Only soft
> B1 item left: the `CommandSource` HMI switch. **B2 BUILT + VERIFIED** —
> `commander.py`, the commandable sim gateway running the A1 StateMachine, 13
> failure-matrix tests green, end-to-end TCP run. Next real build: **B3 gateway
> write path** → B4 bench drills.

**Objective:** a hardened Python→LabVIEW command channel whose failure modes are
all proven safe on the bench. This phase *builds* authority plumbing; it grants
none until its exit gate passes.

**Authority level:** none until B4 drills pass. Everything is testable against
the sim and with `source-select = UI` (Python's writes ignored) before that.

**Entry criteria:** telemetry pipeline live (done). A1 is *not* a prerequisite
for B1/B2 (they can run in parallel); B4 wants A2's shadow compare available as
a divergence alarm.

**LabVIEW changes in this phase:** B0 (wire the WatchDog + SAFE clamp in
`APC_9056_TS_loop.vi` — ✅ done + live-verified) and B3 (two new shared
variables `PC_OperatorRequests` + `CommandSource_IsPython`, the gateway
command branch + envelope echo, the HMI source switch, and the UI
single-writer **redirect**). B1/B2/B4 need no LabVIEW edits (B4 *exercises*
the B0/B3 work).

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

*Owner: you, with node-level guidance. Prereq: B0 outcome (✅ done) + B1 frozen
(✅ 2026-07-07).*

**What exists before B3:** the gateway is read-only — it flattens
`PC_ControlSettings` + extras into the 1 Hz telemetry envelope, and its receive
path answers any `"type":"command"` line with a hardcoded ack constant (the
hello build). **What exists after B3:** validated Python commands write
`PC_ControlSettings`; the UI's writes redirect by source; telemetry carries
`command_source` and `operator_requests`. The finished data flow:

```
                       source = UI                 source = PYTHON
UI_Main write  ──────► PC_ControlSettings          PC_OperatorRequests
Python command ──────► NACK "source is UI"         validate → PC_ControlSettings
9056 consumes  ──────► PC_ControlSettings (unchanged either way)
```

Single-writer matrix — the invariant B3 must end with (exactly one writer per
variable per mode):

| Variable | Writer while source=UI | Writer while source=PYTHON | Readers |
|---|---|---|---|
| `PC_ControlSettings` | `UI_Main` (as today) | gateway (validated commands only) | 9056 SM, gateway telemetry |
| `PC_OperatorRequests` | `UI_Main` (every iteration, unconditional) | `UI_Main` (same — unconditional) | gateway telemetry → Python mirror |
| `CommandSource_IsPython` | operator's HMI switch — **only** | operator — **only** | gateway validation, `UI_Main` gate, telemetry echo |

Work in this order: **B3.0 → B3.a → B3.b → B3.c → B3.d** — variables first,
because every later step drags them onto a diagram.

### B3.0 — Create and deploy the two shared variables (~10 min)

1. Project Explorer → `cRIO-9049` target → `APC_SharedVars.lvlib` (the library
   lives under the 9049 target — same place the A2.1 variables went) →
   right-click → *New → Variable*:
   - **`PC_OperatorRequests`** — Variable Type *Network-Published*; Data Type
     *From Custom Control…* → `APC_ControlSettings.ctl`. Configure identically
     to `PC_ControlSettings` (no buffering, no RT FIFO).
   - **`CommandSource_IsPython`** — Network-Published, **Boolean**. Polarity:
     **FALSE = UI (the default), TRUE = PYTHON.** A Boolean beats a
     string/enum: the deploy-time default is automatically the safe mode (UI),
     nothing can be typo'd, and telemetry turns it into the ICD's
     `"UI"`/`"PYTHON"` string with one `Select`.
2. Right-click the library → *Deploy All*. Nothing on the cRIOs consumes
   either variable (the B0 clamp is ungated), so no cRIO redeploy — this is a
   variable-engine update only.
3. **The unwritten-variable NaN trap (you hit this at A2.1 with
   `Limited_ControlSettings`):** a freshly deployed cluster variable that has
   never been written can flatten with `NaN` in DBL fields — invalid JSON, and
   the Python observer discards every frame. (`PC_ControlSettings` never had
   this problem because `UI_Main`'s main loop writes it every iteration from
   startup; `Limited_ControlSettings` NaN'd because its writer — the 9056
   StateMachine — wasn't running yet.) The B3.c redirect design eliminates the
   trap by construction: `UI_Main` writes `PC_OperatorRequests`
   **unconditionally every loop iteration** (see B3.c step 2), so it is
   written milliseconds after the UI starts. Just do B3.c's write wiring
   before (or together with) B3.a step 6's envelope addition. If frames go
   malformed anyway, diagnose with `python tools/capture_line.py`.

### B3.a — `APC_PC_PythonGateway.vi`: the command branch, node by node

**Where you are.** In the session loop you built for hello-vi, the received
line (from `TCP Read`, CRLF mode) already passes the empty-line gate and the
`Match Pattern` `"type":"command"` → `≥ 0` → Case structure. **Everything
below goes inside that True case**, replacing the hardcoded ack string
constant. Delete the constant; keep the `TCP Write` — step 5 re-feeds it.
Keep the `Match Pattern` gate itself: it's a cheap pre-filter, and lines
without `"type":"command"` should keep being ignored exactly as today.

The finished branch, left to right:

```
                 ┌─ Unflatten(name)  ──────────────► bad-name?  ──┐
received line ───┼─ Unflatten(id)    ──► reply id                 │ Build Array (6 bools,
                 └─ Unflatten(params.settings, typedef) ─► parse? ┼ priority order)
                        │                          range?, clear? ┘   │
                        │                                    Search 1D Array for TRUE
                        │                                             │ index (−1 = pass)
                        ▼                                             ▼
                 [Case: accepted] ─► PC_ControlSettings write   accepted?, reason
                                                                      │
                 Format Into String {"type":"command_ack",…} ─► existing TCP Write
```

**Step 1 — parse three things from the line (three `Unflatten From JSON`
nodes).** Palette: *Programming → String → Flatten/Unflatten String →
Unflatten From JSON*. Drop three; wire the received line to each node's
*JSON string* input. On each, the *path* input selects which JSON element to
extract, and the *type/defaults* input sets the output type:

   1. **name** — right-click *path* → *Create → Constant*; it's a string
      array: type `name` into element 0. Right-click *type/defaults* →
      *Create → Constant* → leave it an **empty string**. The *value* output
      is the command-name string.
   2. **id** — same, *path* element 0 = `id`; *type/defaults* = an **I32**
      constant `0`. Build the **reply id** with a `Select` (Comparison
      palette): unbundle `status` from this node's *error out* →
      `Select`(TRUE → I32 constant `−1`, FALSE → the parsed id). So a line
      whose id can't be read is NACKed with id −1 per ICD §7.3, instead of
      killing anything.
   3. **settings** — *path* = a **2-element** string array: element 0
      `params`, element 1 `settings`. *type/defaults* = an
      **`APC_ControlSettings.ctl` constant**: open the `.ctl` from the
      Project Explorer and **drag the control from the typedef's window onto
      the gateway diagram** — it lands as a cluster constant. Right-click it
      and confirm *Auto-Update from Type Def.* is checked. **Do not edit any
      field labels** — several contain embedded line-feeds; the flatten keys
      must match character-for-character (this node exactly inverts the
      telemetry `Flatten To JSON`; no key renaming on the LabVIEW side,
      ever). Leave *enable strict validation?* unwired (default = tolerant:
      extra JSON fields must not error; B3.d step 2 tests this). Capture this
      node's error: unbundle `status` from *error out* → that Boolean is
      **`parse failed`**.

   **Error-wire hygiene:** chain the error wire through the three nodes in
   sequence, then through a **`Clear Errors`** (Dialog & User Interface
   palette) *after* the status Booleans have been unbundled. A garbage line
   must never leave an error on the session loop's wire — that's what keeps
   the session alive through drill B4-4.

**Step 2 — compute the six check Booleans** (each TRUE = that check fails).
The strings and the order are compared against the sim
(`simserver_monarch.py handle_command`) by the Python tests and the B4
drills, so both are load-bearing:

   | # | Boolean | Wiring | NACK reason (verbatim) |
   |---|---|---|---|
   | 1 | bad name | name → `Not Equal?` vs constant `set_control_settings` | `unknown command '<name>'` |
   | 2 | rate | recipe below → `Array Size` `>` 5 | `rate` |
   | 3 | source | `CommandSource_IsPython` SV read → `Not` | `source is UI` |
   | 4 | parse | `parse failed` from step 1.3 | `parse` |
   | 5 | range | Unbundle By Name `Speed ref` → (`<` 0) `Or` (`>` 3000). **Reject, don't coerce** — the StateMachine limiter stays the real clamp. (On a failed parse this evaluates the defaults cluster — harmless, parse outranks it.) | `range: Speed ref <value>` |
   | 6 | clear e-stop | Unbundle By Name `CLEAR EMERGENCY STOP` | `operator only` |

   **Rate recipe (same algorithm as the sim):** a U32-array shift register on
   the session loop, initialized with an **empty U32 array** constant. Per
   received command: `Tick Count (ms)` → `Build Array` (append to the
   register's array) → a small For loop auto-indexing over it with the
   **conditional terminal** (right-click the output tunnel → *Conditional*)
   keeping elements where `now − element ≤ 1000` → back into the shift
   register. `Array Size` of the result `>` 5 ⇒ rate-fail. (U32 rollover is
   ~49 days; worst case one harmless false NACK.)

**Step 3 — pick the first failure. No nested cases** — one array pass:
   - `Build Array` of the six Booleans **in exactly the table's order**
     (order = priority).
   - `Search 1D Array` (Array palette): *array* = the Boolean array,
     *element* = a TRUE constant. Its *index of element* output is the first
     failing check — or **−1, meaning all passed**.
   - **`accepted`** = index `Equal?` −1.
   - **`reason`**: `Build Array` of six strings in the same order — element 0
     from `Format Into String` `unknown command '%s'` ← name; element 4 from
     `Format Into String` `range: Speed ref %g` ← the unbundled `Speed ref`;
     elements 1/2/3/5 are the plain constants `rate`, `source is UI`,
     `parse`, `operator only`. → `Index Array` with the found index →
     `Select`(accepted → empty-string constant, else → the indexed reason).

**Step 4 — the gated write. One Case structure**, selector = `accepted`:
   - **True case:** the parsed cluster wire → a **`PC_ControlSettings`
     shared-variable write** (drag the variable from the Project Explorer
     into the case; right-click → *Access Mode → Write*). Write it
     **unmodified**: don't touch `PC_HB` (Python toggles it — the 9056
     watchdog must see *Python's* toggling; that's the point), don't re-clamp
     anything (the 9056 limiter does that).
   - **False case:** empty; wire the error line straight through.

**Step 5 — the reply** (feeds the `TCP Write` the old constant used):
`Format Into String`, format string with right-click → *'\' Codes Display*:

   ```
   {"type":"command_ack","id":%d,"accepted":%s,"reason":"%s"}\r\n
   ```

   Inputs, top to bottom: **reply id** (step 1.2), **accepted** →
   `Select`(string constants `true` / `false` — JSON booleans, lowercase, no
   quotes), **reason** (step 3; empty on accept — all reasons are fixed ASCII
   plus a number, nothing needs JSON escaping). Same `\r\n` terminator as the
   telemetry writer (the Python side accepts `\n` too).
**Step 6 — telemetry envelope additions** (in the telemetry loop's
`Format Into String`, same pattern as the `limited_settings` addition from
A2.1 — two more `%s` in the format string, two more inputs):
   - `,"command_source":"%s"` — **with quotes** (JSON string);
     `CommandSource_IsPython` → `Select`(string constants `PYTHON`/`UI`).
   - `,"operator_requests":%s` — **no quotes** (JSON object); a
     `PC_OperatorRequests` **read** → `Flatten To JSON` → the `%s`.
   Python already decodes both fields — no Python change needed.

**Step 7 —** B3.a is testable before touching the UI: do B3.d steps 1–3 now.

### B3.b — the `CommandSource` operator switch

- **Placement (soft default from the B1 review): the HMI System screen**
  (`APC_PC_UI_System.vi`) — it's an operating-mode control and belongs next to
  e-stop. A latching switch labeled *"Python in command"* writing
  `CommandSource_IsPython`, plus a **read-back LED** wired from a *read* of
  the same variable — the operator sees the effective value, not the switch
  position (this doubles as the C0 visibility item).
- **Operator-owned, absolutely:** nothing in the gateway, the command path, or
  Python ever writes this variable. The only writer is the operator's switch —
  deliberately, there isn't even an ICD command for it.
- Flip semantics need nothing extra here: the Python commander seeds its
  intent from telemetry before its first send (bumpless) and goes silent the
  moment the echo says `UI`. Drill B4-7 proves both directions.

### B3.c — `APC_PC_UI_Main.vi`: the single-writer redirect

1. **The write point (located, 2026-07-07, from the `UI_Main` per-frame
   export):** inside `UI_Main`'s **main While loop** there is one big
   `Bundle By Name` (≈20 fields: `EMERGENCY STOP` … `Requested mode`,
   `PID control references`) whose output feeds the **`PC_ControlSettings`
   shared-variable write node** (right of the bundle, near the
   `Listbox`/`PC_Global_ListboxVarBroadcast` nodes). It runs **every loop
   iteration** — which is why `pc_hb` alternates in telemetry, and why this
   variable never had the NaN problem. Sanity-check it's the only writer:
   Project Explorer → right-click the variable → *Find → Search Scope:
   project* (`UI_System`/`_Errors` don't reference it; they feed `UI_Main`
   through globals — the redirect goes at this final write, not at the
   globals).
   - **Build-spec caveat (verified in `MONARCH.lvproj`):** `APC_PC_UI_Main.vi`
     is the source of the **`APC_Monarch` EXE** build spec. If the control room
     runs the built executable rather than the VI in the dev environment, this
     change requires **rebuilding and redeploying `APC_Monarch`** — decide
     which mode operations uses and keep it consistent through Phase B/C.
2. **The redirect — fan the bundle to two nodes (ICD §7.7).** Take the
   `Bundle By Name` output wire and branch it:
   - **`PC_OperatorRequests` write — unconditional**, every iteration, next to
     the existing write (drag the B3.0 variable in, *Access Mode → Write*).
     Always-on: this kills the NaN trap by construction, matches the sim
     exactly (`ui_write()` updates `operator_requests` regardless of source),
     and gives Python a live view of the operator panel even in UI mode
     (harmless — the mirror only acts while commanding; it just makes
     handovers smoother).
   - **`PC_ControlSettings` write — inside a Case structure** on a
     `CommandSource_IsPython` read: **FALSE (UI) case** = the existing write
     node, moved inside, untouched — the fallback path stays direct and never
     depends on Python or the gateway; **TRUE (PYTHON) case** = empty (wire
     the error line through).
   Net effect: the operator's inputs flow in both modes; while Python
   commands they arrive in telemetry as `operator_requests` and
   `supervisory/monarch/operator_mirror.py` mirrors them into Python's intent
   (safety inputs always; everything else when no sequence is running). Keep
   it visually obvious — one case around one write node, nothing clever.
3. **Displays are untouched.** All UI *reads* stay as they are — while
   source=PYTHON the operator keeps seeing live values; only the write target
   changes. Handback note for C3: on flip-back to UI the panel's current
   control values win again, so controls should match telemetry before
   handing back (with the mirror active they normally will — Python has been
   following the operator's requests all along).
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

### B3.d — Verify as you build (each step has a ready-made Python check)

1. **After B3.0 + B3.a step 6 (envelope):** run `python examples/monarch_listen.py`
   — frames must keep decoding (no "malformed message"; if malformed, it's the
   NaN trap — B3.0 step 3), and each frame should now show
   `command_source="UI"`. `python tools/capture_line.py` pinpoints any framing
   or JSON problem to the character.
2. **NACK ladder, one reason at a time** (source still UI). Send one raw
   command and print the reply — from the control-room PC:

   ```
   python - <<"EOF"
   import socket, json
   s = socket.create_connection(("127.0.0.1", 5020), timeout=5)
   cmd = {"type": "command", "id": 1, "name": "set_control_settings",
          "params": {"settings": {}}}   # empty settings -> expect "parse"
   s.sendall((json.dumps(cmd) + "\n").encode())
   buf = b""
   while b"command_ack" not in buf:
       buf += s.recv(4096)
   print([l for l in buf.decode().splitlines() if "command_ack" in l][0])
   EOF
   ```

   Vary it to hit each rung: any other `name` ⇒ `unknown command '...'`;
   6 sends in one second ⇒ `rate`; a full valid settings dict (copy the
   `settings` object out of a telemetry line) ⇒ `source is UI`; garbage bytes
   ⇒ discarded/NACK **and the session must survive** (telemetry keeps
   flowing — that's drill B4-4's core).
3. **Flip to PYTHON (B3.b done):** telemetry echo flips to
   `command_source="PYTHON"` within a frame. Now the real client:
   `python examples/monarch_operate.py` → `status` shows `commanding=True` →
   `mode motoring` → watch `system_state` step up in telemetry. Repeat the
   step-2 rungs that should still NACK (`operator only`, `range: Speed ref`,
   `rate`).
4. **After B3.c (redirect):** with source=PYTHON, move a control on the HMI —
   `PC_ControlSettings` must NOT change directly (no bypass), but telemetry's
   `operator_requests` shows the new value and, with `monarch_operate`
   running, the mirror carries it into Python's next command — the value
   arrives in `PC_ControlSettings` *via Python*, one tick later. Flip back to
   UI: direct writes resume, Python goes silent (its sends NACK
   `source is UI`).
5. Then run the full **B4 drill table** — B4-1/2 are already banked from the
   B0 live verification.

**Definition of done (B3):** with source=UI, Python commands are NACKed and
nothing changes; with source=PYTHON, a command round-trips to a telemetry
effect on the real system; with the redirect in place, the single-writer
matrix at the top of this section is true — verified per B3.d.

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
