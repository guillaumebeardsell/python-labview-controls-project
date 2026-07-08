# Interface Control Document — Python Supervisor ⇄ LabVIEW Gateway

**Version 0.2** — §§1–6 unchanged from v0.1 (2026-07-02); §7 (MONARCH command
path) **frozen 2026-07-07** after joint review.

## 1. Scope and roles

This document defines the link between the **Python supervisor** (state machines and
supervisory decision logic) and the **LabVIEW gateway** (the main LabVIEW 2020 SP1
application on the Windows host). It does not cover the existing LabVIEW ⇄ cRIO links
(Network Streams / shared variables / FPGA interface), which remain unchanged.

Python never talks to the cRIOs directly. All commands flow through the LabVIEW
gateway, which validates them against interlocks before acting or forwarding.

```
┌────────────────────┐   TCP, localhost    ┌────────────────────┐        ┌──────────────┐
│  Python supervisor │ ◄─── telemetry ──── │  LabVIEW gateway   │ ◄────► │ cRIO RT/FPGA │
│  (state machines,  │ ──── commands ────► │  (validation,      │        │ (I/O, loops, │
│   decision logic)  │ ──── heartbeat ───► │   safe fallback)   │        │  interlocks) │
└────────────────────┘ ◄──── acks ──────── └────────────────────┘        └──────────────┘
```

**Safety invariant:** the system must remain safe when the Python process is absent,
crashed, or misbehaving. LabVIEW treats every Python command as a *request* and is the
sole authority on whether it executes.

## 2. Transport

| Item | Value |
|---|---|
| Protocol | TCP |
| Server | LabVIEW gateway, listening on `127.0.0.1:5020` (configurable) |
| Client | Python supervisor; reconnects automatically with backoff |
| Concurrent clients | 1 (LabVIEW may refuse or drop additional connections) |
| Encoding | UTF-8 JSON, one object per message. **Numbers must be finite** — no `NaN`/`Infinity` literals: LabVIEW's Flatten can *emit* `NaN` (unwritten values) but its Unflatten *rejects* it (bench-verified 2026-07-08: an echoed NaN got every command NACKed `parse`). Python sanitizes non-finite floats to 0.0 at the send edge and warns; receivers should tolerate incoming NaN defensively. |
| Framing | Each message is terminated by LF (`\n`). A CR before the LF is permitted and ignored. Python transmits CRLF (`\r\n`) so the LabVIEW side can use TCP Read in CRLF mode. **Python→LabVIEW senders MUST terminate with `\r\n`** (a bare `\n` never completes a CRLF-mode read) **and MUST emit compact JSON** — no space after `:` — the gateway's command gate matches the literal `"type":"command"` (bench-verified 2026-07-08; pydantic serialization is compact by default, `json.dumps` defaults are NOT). |

## 3. Message envelope

Every message is a single JSON object with a `type` field selecting one of the message
types below. Receivers **ignore unknown fields** (forward compatibility) and **log and
discard messages with unknown `type`** rather than treating them as a fault.

## 4. Message types

### 4.1 `telemetry` — LabVIEW → Python, 1 Hz

The complete plant snapshot as LabVIEW sees it. This is Python's single source of truth;
Python must never infer plant state from its own command history. Telemetry also serves
as LabVIEW's heartbeat.

| Field | Type | Meaning |
|---|---|---|
| `type` | `"telemetry"` | — |
| `seq` | int | Strictly increasing within a connection |
| `ts` | float | LabVIEW wall-clock time, seconds since Unix epoch |
| `mode` | string | LabVIEW's own mode/state name (e.g. `"IDLE"`, `"RUNNING"`, `"SAFE_HOLD"`) |
| `channels` | object: string → number | Analog values by tag name |
| `flags` | object: string → bool | Interlock and status booleans by tag name |

```json
{"type": "telemetry", "seq": 42, "ts": 1783041300.5, "mode": "RUNNING",
 "channels": {"temp_c": 61.2, "setpoint_c": 80.0},
 "flags": {"interlock_ok": true, "door_closed": true}}
```

### 4.2 `command` — Python → LabVIEW

A request. LabVIEW validates it against interlocks and current mode, then ACKs or NACKs.

| Field | Type | Meaning |
|---|---|---|
| `type` | `"command"` | — |
| `id` | int | Strictly increasing; unique within a connection |
| `name` | string | Command name (per-system command list, defined separately) |
| `params` | object | Command parameters; values are number, bool, or string |

```json
{"type": "command", "id": 7, "name": "set_setpoint", "params": {"value": 80.0}}
```

### 4.3 `command_ack` — LabVIEW → Python

Validation result for one command, sent within **500 ms** of receipt.

| Field | Type | Meaning |
|---|---|---|
| `type` | `"command_ack"` | — |
| `id` | int | The `id` of the command being answered |
| `accepted` | bool | `true` = accepted for execution; `false` = rejected |
| `reason` | string | Human-readable reason when rejected; empty when accepted |

**An ACK is not confirmation of effect.** It means the command passed validation.
Python confirms the effect by observing subsequent telemetry.

### 4.4 `heartbeat` — Python → LabVIEW, 1 Hz

| Field | Type | Meaning |
|---|---|---|
| `type` | `"heartbeat"` | — |
| `seq` | int | Strictly increasing within a connection |
| `ts` | float | Python wall-clock time, seconds since Unix epoch |

## 5. Timing, watchdogs, and failure behavior

| Condition | Detector | Response |
|---|---|---|
| No Python heartbeat for **5 s** | LabVIEW | Enter safe hold (LabVIEW's existing safe fallback). Report `mode: "SAFE_HOLD"` in telemetry. |
| TCP connection drops | LabVIEW | Same as heartbeat loss: safe hold. Resume listening for a new connection. |
| No telemetry for **3 s** | Python | Mark plant view *stale*: stop sending commands, abandon pending acks, expose staleness to state machines so they can transition to their own hold states. |
| TCP connection drops | Python | Same as telemetry loss, plus reconnect with backoff (1 s → 5 s). |
| Malformed message received | Either side | Log and discard the message. Do not drop the connection. Repeated garbage (> 10 consecutive) may drop the connection. |
| Ack received for unknown command id | Python | Log and discard (can occur across a staleness episode). |

### Reconnect semantics

A new TCP connection is a **fresh session** on both sides:

- Counters (telemetry `seq`, command `id`, heartbeat `seq`) are not required to
  restart; neither side may assume counter continuity across connections.
- Python discards all pre-disconnect expectations and rebuilds its plant view from the
  first telemetry message. It must handle connecting to a plant that is mid-process.
- LabVIEW discards any queued state associated with the previous session.
- LabVIEW remains in safe hold (or whatever state its own logic dictates) until its own
  logic — not the mere presence of a new connection — determines otherwise.

## 6. Out of scope / future

- The MONARCH command path is specified in **§7** (frozen 2026-07-07).
- The per-system command list (names, parameters, validation rules) is maintained in a
  separate document as systems are ported.

---

# v0.2 — MONARCH command path (§7)

> **Status: FROZEN (joint review 2026-07-07).** The Python side and the sim
> gateway implement this (`supervisory/monarch/commander.py`,
> `supervisory/monarch/simserver_monarch.py`, `tests/test_monarch_commander.py`);
> the LabVIEW gateway write path (B3) builds against this section as written.
> Changing §7 now requires moving both sides in lockstep.

## 7.1 The command

One atomic command carries the complete desired `PC_ControlSettings`:

```json
{"type":"command","id":7,"name":"set_control_settings",
 "params":{"settings":{ …raw LabVIEW-label Flatten-To-JSON of PC_ControlSettings… }}}
```

`params.settings` uses the **real LabVIEW field labels** (the exact shape the
telemetry `settings` field uses), produced by `control_settings_to_labview()` — so
the gateway can `Unflatten From JSON` straight into the typedef with **no key
mapping**, mirroring the telemetry direction.

## 7.2 Stream semantics

- **Whole-cluster, idempotent, 1 Hz.** While in command, Python sends its complete
  intent every tick — not deltas, not on-change. A lost frame heals on the next tick,
  and the stream itself is the liveness signal.
- **`pc_hb` toggling:** Python flips `PID control references.PC_HB` on every send, so
  the existing `APC_9056_WatchDog` stall counter directly supervises the Python
  stream. `MTR HB` passes through unchanged from the last telemetry.
- **Bumpless by construction:** the intent is seeded from the last telemetry frame
  (and re-seeded after any staleness gap or while not in command), so Python's first
  commanded frame equals the plant's current settings.
- **Staleness:** no telemetry for 3 s ⇒ Python stops sending (existing §5 rule) and
  discards its intent; on recovery it re-seeds from telemetry.
- `clear_emergency_stop` is **always forced FALSE** by the Python sender (see 7.4).

## 7.3 Validation and ACK/NACK

An ACK means *validated and written to `PC_ControlSettings`* — never "took effect".
Effects are confirmed by watching `system_state` / `limited_settings` in telemetry.
Validation order and NACK reasons (machine-readable):

| Order | Check | NACK `reason` |
|---|---|---|
| 1 | command name known | `unknown command '<name>'` |
| 2 | rate ≤ 5 commands / rolling second | `rate` |
| 3 | source-select is PYTHON | `source is UI` |
| 4 | `settings` unflattens into the typedef | `parse` |
| 5 | range checks (initially: `Speed ref` within 0–3000) | `range: <field>` |
| 6 | `CLEAR EMERGENCY STOP` is FALSE | `operator only` |

Unknown labels inside `settings` are ignored (forward-compat, matching telemetry).

## 7.4 Single writer, source-select, e-stop precedence

- Exactly **one writer** of `PC_ControlSettings` at a time. A gateway-side
  `CommandSource` selector (`UI` | `PYTHON`), **default UI**, owned by the operator
  on the HMI — not settable via this protocol. Every telemetry frame echoes it as
  `"command_source"`.
- While source = UI, Python emits nothing (it tracks telemetry for bumpless
  handover); any command that does arrive is NACKed `source is UI`. The UI in turn
  must not write while source = PYTHON.
- **E-stop precedence:** e-stop TRUE from *any* source (UI panels or a Python
  command) latches. **Python can assert e-stop but can never clear it** — a command
  with `CLEAR EMERGENCY STOP` = TRUE is NACKed `operator only`.

## 7.5 Loss-of-supervisor response (ties to Phase B0)

The 9056 `WatchDog` stall-counts `PC_HB`; when Python freezes/dies, `PC_HB` stops
changing and `PCnotResponding` trips. The B0 LabVIEW work wires that flag into the
StateMachine's state limitation as a **−1 (SAFE) clamp**, gated on
source = PYTHON. The sim gateway implements exactly this behavior.

Note the toggle is a **relay across the whole PC-side chain**: Python flips the
field in its command → TCP → the gateway VI writes the `PC_ControlSettings`
shared variable → the 9056 reads it. A shared variable retains its last value,
so if *any* link dies or hangs — Python, the TCP session, the gateway VI, the
PC↔cRIO network, or the PC itself — the 9056 sees a frozen `PC_HB` and trips.
One flag therefore supervises the entire command path, not just the Python
process. (The same applies to `MTR_HB`, which the PC's Modbus code relays into
the cluster: that channel watches the membrane PLC *and* its PC-side relay.)

**Decisions (resolved at joint review, 2026-07-07):**

- **Watchdog threshold: 5 s.** `PCnotResponding` trips within 5 s of `PC_HB`
  freezing (threshold = ceil(5 s / TS-loop period) iterations).
- **`PC_HB` toggling: option (a)** — the **UI toggles `PC_HB`** while
  source = UI (from its main loop at ~1 Hz, **not** on-change — an on-change-only
  write would freeze the flag between operator interactions and false-trip);
  Python toggles it while source = PYTHON. Consequence: the SAFE clamp is armed
  in **both** modes, no source gating. *Interim:* until the UI toggle is
  implemented (B3.c), the clamp is gated on source = PYTHON — which is what the
  sim gateway currently models.
- **Follow-on (specified, response TBD during commissioning): `UI_HeartBeat`** —
  a standalone network shared variable (house pattern, like `9049_HeartBeat`),
  toggled by the UI's main loop regardless of source, watched as a fifth
  WatchDog channel. It covers the one case `PC_HB` cannot: the UI (the
  operator's monitoring surface and software e-stop) dying while **Python**
  holds authority. Response phase-in: alert + Python-side reaction (abort
  running sequences, cap state via a temporal rule) first; LabVIEW-side clamp
  value decided by the team (conservative default while the plant is unproven:
  SAFE). Deliberately NOT a second field in `PC_ControlSettings` — no typedef
  change, independent threshold/response.

## 7.6 Failure matrix (behavior ⇄ verification)

| Failure | Defined behavior | Verified by |
|---|---|---|
| Python crash / freeze | `PC_HB` stalls → `PCnotResponding` → SAFE clamp; recovery steps up by 1 | sim test; bench drill B4-1/2 |
| TCP drop | session ends, gateway re-listens; same watchdog backstop | `test_tcp_link.py`; drill B4-3 |
| Malformed JSON / garbage | NACK `parse` (or line discarded); state unchanged; session survives | sim test; drill B4-4 |
| Out-of-range value | NACK `range: <field>`; nothing written | sim test; drill B4-5 |
| Command flood | NACK `rate` beyond 5/s; telemetry cadence unaffected | sim test; drill B4-6 |
| Source flip mid-stream | bumpless both ways; `command_source` flips in telemetry | sim test; drill B4-7 |
| E-stop vs Python | latches from any source; Python clear NACKed `operator only` | sim tests; drill B4-8 |
| Stale telemetry (Python side) | Python stops commanding ≤ 3 s; re-seeds on recovery | sim test; drill B4-9 |

## 7.7 Operator requests — the UI stays the input surface (added 2026-07-07)

Clarified at review: while Python holds authority, the LabVIEW UI remains the
operator's surface **for inputs too** (mode changes, shutdown, speed, …), not
just monitoring. Those inputs flow to Python **as requests**; Python decides
and emits the actual command. The single-writer rule is preserved by a
separate request channel:

- **`PC_OperatorRequests`** — a new network shared variable, **same
  `APC_ControlSettings.ctl` typedef** (so the UI's controls are unchanged).
- **The B3.c gate is a redirect, not a suppression:** source = UI ⇒ the UI
  writes `PC_ControlSettings` directly, exactly as today (the fallback path
  never depends on Python or the gateway); source = PYTHON ⇒ the same values
  write to `PC_OperatorRequests` instead.
- The gateway forwards it in telemetry as **`operator_requests`** (raw
  flatten; optional field, additive like all envelope extensions).
- Python mirrors requests into its intent (`OperatorRequestMirror`, policy):
  * **Safety inputs mirror always and instantly** — `EMERGENCY STOP`
    (set-only: True mirrors, False never clears the latch), `Force idling`,
    `Force motoring`.
  * **No sequence active:** full transparency — the entire request cluster
    mirrors (minus `PC_HB`/`MTR HB`, which the commander owns, and
    `CLEAR EMERGENCY STOP`, which never flows through Python).
  * **Sequence active:** the sequence owns the intent; only the safety inputs
    mirror. Operators redirect by aborting the sequence first.
- E-stop and its CLEAR keep their existing operator-direct channels
  (`APC_MASTER_EmergencyStop` etc.) unchanged — the mirror is belt on top.
- **E-stop recovery under Python authority (as-built, bench-verified
  2026-07-08):** the panel e-stop mirrors set-only, so once tripped it
  **latches in Python's intent** and no clear path exists while
  source=PYTHON (the mirror strips CLEAR; the gateway NACKs it
  `operator only`). Recovery is *deliberately* a demotion: **flip
  CommandSource to UI → clear on the panel (direct write) → state
  recovers → re-grant PYTHON when ready** (the commander re-seeds
  bumplessly). An e-stop under Python authority thus always forces a
  human review before Python resumes — this is the intended authority
  model, and a required step in the C3 handover procedure.

Consequence: with no sequence running, Python-in-command is behaviorally
identical to UI-in-command from the operator's seat; automation adds value on
top without changing how the plant is driven by hand. This also strengthens
the case for the UI heartbeats in §7.5 — the UI is an active input surface in
PYTHON mode, so its liveness matters.

Permanence (clarified 2026-07-09): the HMI panels (`APC_PC_UI_Main`,
`_System`, `_Errors`) are **permanent** — the operator's console for the life
of the system. As Python absorbs decisions, individual *decision* inputs may
be retired from the panels (the phase-E retirement pass, team-gated); the
request-channel + mirror architecture is the steady state, not a transition.
Operational corollary: since the mirror asserts the panel's current values
the moment authority is granted, the operator performs a **panel lineup
check before every handover** (C3 step 0). The full mirror is the only
operational mode; safety-only is an engineering-bench configuration.
- Protocol versioning/negotiation: deferred. The unknown-field and unknown-type rules
  in §3 provide forward compatibility in the meantime.
- Event/alarm push messages (LabVIEW → Python outside the 1 Hz telemetry): deferred
  until a ported system needs sub-second event latency.
