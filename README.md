# Python Supervisory Layer for the LabVIEW Controls Stack

The Python supervisory layer for **MONARCH** (a Noble Thermodynamics Argon
Power Cycle research engine controlled by LabVIEW on two NI cRIOs + a Windows
PC). Supervisory state machines and decision logic migrate here; **LabVIEW
permanently owns hardware access, hard safety interlocks, command validation,
and safe fallback**. Every command Python sends is a request the LabVIEW
gateway may reject, and the system is designed to be safe when the Python
process is absent, crashed, or wrong.

```
┌────────────────────┐   TCP, localhost    ┌────────────────────┐        ┌──────────────┐
│  Python supervisor │ ◄─── telemetry ──── │  LabVIEW gateway   │ ◄────► │ cRIO RT/FPGA │
│  (this repo)       │ ──── commands ────► │  (Win, LV2020SP1)  │        │ (I/O, loops, │
│                    │ ──── heartbeat ───► │                    │        │  interlocks) │
└────────────────────┘ ◄──── acks ──────── └────────────────────┘        └──────────────┘
```

## Layout

Two layers, deliberately decoupled — `supervisory/` is generic and knows nothing
about MONARCH; `supervisory/monarch/` holds the project-specific payloads.

| Path | Contents |
|---|---|
| `supervisory/messages.py` | Pydantic models for the ICD message types |
| `supervisory/link.py` | `PlantLink` protocol + `TcpPlantLink` (auto-reconnect; pluggable `parser=`) |
| `supervisory/engine.py` | `Supervisor` tick loop, `PlantView`, `StateMachine` base class |
| `supervisory/sim.py` / `simserver.py` | Socket-free fake gateway for unit tests / the same behind real TCP |
| `supervisory/recorder.py` | JSONL traffic recorder for offline replay |
| `supervisory/monarch/control_settings.py` | The `ControlSettings` cluster + `SystemState` enum (confirmed vs live capture) |
| `supervisory/monarch/labview_mapping.py` | LabVIEW flatten-label ↔ model bridge; both-way converters; contract diff |
| `supervisory/monarch/telemetry.py` | `MonarchTelemetry` envelope + `monarch_parser` |
| `supervisory/monarch/simserver_monarch.py` | Fake MONARCH gateway streaming real-shaped telemetry |
| `examples/hello_link.py` | Connectivity smoke test (PASS/FAIL) |
| `examples/monarch_listen.py` | Read-only MONARCH observer → records `monarch.jsonl` |
| `examples/demo.py` | End-to-end demo state machine (`HeatSoak`) — the porting pattern |
| `tools/compare_flatten.py` | Diff a LabVIEW `Flatten To JSON` capture against the contract |
| `tests/` | pytest suite (no hardware, no LabVIEW, no sockets except one smoke test) |
| `original-labview-codebase/` | Exports of the MONARCH LabVIEW project (reference only) |

## Docs

| Doc | What it is |
|---|---|
| [docs/migration-plan.md](docs/migration-plan.md) | **Phased execution plan A–E + current project status (authoritative)** |
| [docs/phases/](docs/phases/) | Detailed step-by-step instructions, one file per phase (A–E) |
| [docs/migration-seam.md](docs/migration-seam.md) | FLOOR/MIDDLE/BRAIN boundary analysis + port backlog |
| [docs/icd.md](docs/icd.md) | Wire protocol v0.1 + failure/reconnect semantics |
| [docs/monarch-control-settings.md](docs/monarch-control-settings.md) | The `ControlSettings` data contract (confirmed) |
| [docs/monarch-telemetry.md](docs/monarch-telemetry.md) | Telemetry envelope (live) + gateway build recipe |
| [docs/monarch-flatten-diff.md](docs/monarch-flatten-diff.md) | Contract-verification workflow (run on typedef changes) |
| [docs/hello-vi.md](docs/hello-vi.md), [docs/labview-notes.md](docs/labview-notes.md) | LabVIEW gateway build guides (the completed connectivity experiment) |

## Quickstart

```bash
pip install -e ".[dev]"                      # package (editable) + pytest
pytest                                       # full suite, sub-second

# generic end-to-end demo, two terminals:
python -m supervisory.simserver --speedup 10
python examples/demo.py

# MONARCH telemetry offline (no LabVIEW), two terminals:
python -m supervisory.monarch.simserver_monarch --speedup 5
python examples/monarch_listen.py            # records monarch.jsonl
```

On the control-room PC, `examples/monarch_listen.py` alone connects to the real
gateway. Kill either simserver mid-run to see staleness handling; restart it to
see reconnect and recovery.

## Design rules

1. **State machines are pure decisions.** Each tick a machine receives a
   `PlantView` (latest telemetry, staleness, acks) and returns
   `CommandRequest`s. No sockets, clocks, or globals inside machines — that
   is what makes them unit-testable and replayable against recorded traffic.
2. **Telemetry is the only truth.** An ACK means a command passed LabVIEW's
   validation, nothing more; effects are confirmed by watching telemetry.
   After a reconnect, Python rebuilds its world from telemetry, never from
   memory.
3. **Stale means stop.** No telemetry for 3 s ⇒ the engine stops sending
   commands and machines transition to their own hold states. Symmetrically,
   LabVIEW safe-holds 5 s after Python's heartbeat stops.
4. **The link is swappable.** The engine only knows `PlantLink`; tests use
   `SimPlantLink` (no sockets), production uses `TcpPlantLink`. At 1 Hz the
   implementation is plain threads + a queue — no asyncio needed.

## Status

Current status lives in **[docs/migration-plan.md](docs/migration-plan.md)** (kept
authoritative there, not here). Snapshot: transport + data contract validated against
the real LabVIEW system; the read-only telemetry pipeline is **live** and recording;
next is Phase A — the `APC_9056_StateMachine` port with a shadow-compare harness.
