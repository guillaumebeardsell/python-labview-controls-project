# Python Supervisory Layer for the LabVIEW Controls Stack

This repo holds the Python side of a split controls architecture: supervisory
state machines and decision logic live here; **LabVIEW permanently owns
hardware access, hard safety interlocks, command validation, and safe
fallback**. Every command Python sends is a request the LabVIEW gateway may
reject, and the system is designed to be safe when the Python process is
absent, crashed, or wrong.

```
┌────────────────────┐   TCP, localhost    ┌────────────────────┐        ┌──────────────┐
│  Python supervisor │ ◄─── telemetry ──── │  LabVIEW gateway   │ ◄────► │ cRIO RT/FPGA │
│  (this repo)       │ ──── commands ────► │  (Win, LV2020SP1)  │        │ (I/O, loops, │
│                    │ ──── heartbeat ───► │                    │        │  interlocks) │
└────────────────────┘ ◄──── acks ──────── └────────────────────┘        └──────────────┘
```

The wire contract is [docs/icd.md](docs/icd.md); LabVIEW-side implementation
guidance is [docs/labview-notes.md](docs/labview-notes.md).

## Layout

| Path | Contents |
|---|---|
| `supervisory/messages.py` | Pydantic models for the ICD message types |
| `supervisory/link.py` | `PlantLink` protocol + `TcpPlantLink` (real TCP client, auto-reconnect) |
| `supervisory/engine.py` | `Supervisor` tick loop, `PlantView`, `StateMachine` base class |
| `supervisory/sim.py` | `SimPlant`/`SimPlantLink` — socket-free fake gateway for unit tests |
| `supervisory/simserver.py` | The fake gateway behind real TCP: `python -m supervisory.simserver` |
| `supervisory/recorder.py` | JSONL traffic recorder for offline replay |
| `examples/demo.py` | End-to-end demo state machine (`HeatSoak`) — the porting pattern |
| `tests/` | pytest suite (runs with no hardware, no LabVIEW, no sockets except one smoke test) |

## Quickstart

```bash
pip install -e ".[dev]"                      # package (editable) + pytest
pytest                                       # full suite, sub-second

# end-to-end demo, two terminals:
python -m supervisory.simserver --speedup 10
python examples/demo.py
```

Kill the simserver mid-demo to see staleness handling; restart it to see
reconnect and recovery.

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

## Status / next steps

- [x] ICD v0.1, message models, TCP link, engine, sim, tests
- [ ] LabVIEW gateway implementation (see docs/labview-notes.md)
- [ ] Port the first real state machine; run it in shadow mode (Python
      decides, LabVIEW's existing logic stays in command) before giving it
      authority
- [ ] Per-system command list document as systems are ported
