# Interface Control Document — Python Supervisor ⇄ LabVIEW Gateway

**Version 0.1 (draft)** — 2026-07-02

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
| Encoding | UTF-8 JSON, one object per message |
| Framing | Each message is terminated by LF (`\n`). A CR before the LF is permitted and ignored. Python transmits CRLF (`\r\n`) so the LabVIEW side can use TCP Read in CRLF mode. |

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

- **v0.2 (planned, Phase B1 of `docs/migration-plan.md`):** the MONARCH command path —
  an atomic `set_control_settings` command carrying a complete `PC_ControlSettings`
  (LabVIEW-label serialization), `pc_hb` toggling for the 9056 watchdog, and the
  single-writer source-select rules. This document stays at v0.1 until that lands.
- The per-system command list (names, parameters, validation rules) is maintained in a
  separate document as systems are ported.
- Protocol versioning/negotiation: deferred. The unknown-field and unknown-type rules
  in §3 provide forward compatibility in the meantime.
- Event/alarm push messages (LabVIEW → Python outside the 1 Hz telemetry): deferred
  until a ported system needs sub-second event latency.
