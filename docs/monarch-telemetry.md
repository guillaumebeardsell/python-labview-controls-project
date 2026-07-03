# MONARCH Telemetry — Stage 1 read-only pipeline

Stage 1 streams the real engine state to Python once per second, decoded into
the confirmed `ControlSettings` contract (docs/monarch-control-settings.md).
Python only **observes** — no commands, no authority — so it's the safe first
step of the migration. This is what `examples/monarch_listen.py` does.

## Wire format

One JSON object per line (the ICD framing, LF/CRLF terminated):

```json
{"type":"telemetry","seq":42,"ts":1783041300.5,"system_state":3,
 "settings":{ …LabVIEW Flatten To JSON of the ControlSettings cluster… }}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | `"telemetry"` | — |
| `seq` | int | Per-connection frame counter |
| `ts` | float | LabVIEW wall-clock time (seconds since epoch) |
| `system_state` | int | `CURRENT SYSTEM STATE`: −1 SAFE, 0 STAND_BY, 1 MOTORING, 2 IDLING, 3 FIRING |
| `settings` | object | **Raw** `Flatten To JSON` of the ControlSettings cluster |

The key idea: **`settings` is LabVIEW's raw flatten** — original field labels,
PID references nested under `"PID control references"`, quirks and all. Python
maps it to the typed model with `control_settings_from_labview()`
(`supervisory/monarch/labview_mapping.py`), so **the gateway VI does no
key-renaming** — it just flattens the cluster and drops it in. Unknown labels
are surfaced (`MonarchTelemetry.unmapped`), never fatal.

## LabVIEW side — extend the hello VI's telemetry write

You already send a toy telemetry line at 1 Hz. Swap that one `Format Into
String` for the real envelope; everything else (the 1 Hz timer, `TCP Write`,
framing) stays:

1. Wire the live **`APC_ControlSettings` cluster** (the `PC_ControlSettings`
   value) into **`Flatten To JSON`** → a JSON string, call it `settingsJSON`.
   - You already proved this exact flatten matches the Python contract (the
     Stage-1 diff → AGREE), so nothing new to validate.
2. Get the **current system state** as an integer (the `CURRENT SYSTEM STATE`
   I8 from the StateMachine).
3. Build the envelope with **`Format Into String`**, format string:

   ```
   {"type":"telemetry","seq":%d,"ts":%.3f,"system_state":%d,"settings":%s}
   ```

   arguments in order: `seq` (I32), `ts` (a timestamp — `Get Date/Time In
   Seconds` → to DBL, or `0` for now), `system_state` (I8), `settingsJSON`
   (string, the `%s`). Because `settingsJSON` is already valid JSON, dropping it
   in as `%s` nests it correctly.
4. Append `\r\n` and `TCP Write`, exactly as now.

That's the whole change. Keep the command-ack path as-is.

**Getting to *real* telemetry:** the hello VI can start by flattening a
ControlSettings **constant** to prove the pipeline. To stream live data, the
gateway loop needs read access to the running app's `PC_ControlSettings` (and
the system state) — via the same queue/FGV/shared-variable the UI already uses.
That integration (a gateway loop tapping the live cluster) is the point where
this stops being a toy and starts recording real runs.

## Python side — the observer

```bash
# terminal 1 — until the gateway sends real telemetry, use the sim:
python -m supervisory.monarch.simserver_monarch --speedup 5
# terminal 2:
python examples/monarch_listen.py
```

`monarch_listen.py` connects (reusing `TcpPlantLink` with `monarch_parser`),
decodes each frame to `MonarchTelemetry` (typed `system_state` + `settings:
ControlSettings`), logs a one-line status, and records every frame to
`monarch.jsonl`. It sends a 1 Hz heartbeat so a watchdog-guarded gateway stays
live, but issues no commands.

The `monarch.jsonl` recording is the corpus for Stage 2: the state logic will be
replayed against real recorded telemetry to check its decisions offline.

## Status

- [x] `ControlSettings` contract confirmed against a live capture
- [x] Raw-flatten → typed model decoder (`control_settings_from_labview`), tested
      against the real capture
- [x] Telemetry envelope + parser (`MonarchTelemetry`, `monarch_parser`)
- [x] Read-only observer + JSONL recorder; sim gateway for offline testing
- [ ] Gateway VI change to send the real envelope (recipe above)
- [ ] Point the gateway at the live cluster → record a real run (completes Stage 1)
