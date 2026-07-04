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

## LabVIEW gateway — send the real envelope, node by node

You're editing the working hello VI. You replace **only** the telemetry
`Format Into String` and add three inputs to it — the 1 Hz timer, `seq` shift
register, `TCP Write`, framing, the ack reply, and the reconnect handling all
stay exactly as they are. This exact envelope was verified to decode on the
Python side (`monarch_parser`), so if the flatten matches (it did — Stage-1 diff
→ AGREE) there's nothing new to validate.

### Part A — prove the envelope with a constant (do this first)

**Step 1 — a ControlSettings value to flatten.** In the Project Explorer open
`controls`, and **drag `APC_ControlSettings.ctl` onto the block diagram** — it
drops as a constant of that type. Right-click it → *View Cluster Size* isn't
needed; just set a couple of visible fields (e.g. `Speed ref`, `Requested mode`,
`Spark advance`) to non-default values so you can see them change in Python.

**Step 2 — `Flatten To JSON`.** Drop it (Programming → Cluster, Class & Variant
→ JSON), wire the constant from Step 1 into its **value** input. Leave the other
inputs default. Its output string is your `settingsJSON`. (This is the identical
flatten you captured for the contract diff — no new work.)

**Step 3 — system state.** For the test, a **numeric constant**, representation
**I32**, value `3` (FIRING) — or a front-panel control so you can change it
live. This becomes the real `CURRENT SYSTEM STATE` in Part B.

**Step 4 — timestamp (`ts`).** Simplest for now: a **DBL constant `0`**. For a
real Unix timestamp: `Get Date/Time In Seconds` (Programming → Timing) →
**To Double Precision Float** → **subtract `2082844800`** → wire that.
- Why subtract: LabVIEW timestamps count seconds from **1904**-01-01; the wire
  format (and Python) use the **Unix** epoch (1970-01-01). The offset is
  2 082 844 800 s. Skip it and Python still records fine — `ts` is informational,
  the staleness watchdog uses arrival time — but the number won't read as a real
  date.

**Step 5 — build the envelope with `Format Into String`.** Replace your current
telemetry format-string constant with this one, in **`'\' Codes Display`** so the
trailing `\r\n` is a real CR+LF:

```
{"type":"telemetry","seq":%d,"ts":%.3f,"system_state":%d,"settings":%s}\r\n
```

Grow the node to **four arguments** and wire them **in this order**:

| # | Format | Wire | Type |
|---|---|---|---|
| 1 | `%d` | `seq` (your existing telemetry counter) | I32 |
| 2 | `%.3f` | `ts` (Step 4) | DBL |
| 3 | `%d` | `system_state` (Step 3) | I32 / I8 |
| 4 | `%s` | `settingsJSON` (Step 2) | String |

Key point: `settingsJSON` enters as a **`%s` argument**, so `Format Into String`
inserts it **verbatim** — its braces, quotes, and any `%` inside are *not*
re-interpreted, and the nested object lands correctly. (Never build the settings
by string concatenation; always via `Flatten To JSON`, so it stays locked to the
typedef.)

**Step 6 — send.** Wire the `Format Into String` output into the **same
telemetry `TCP Write`** you already have (on the connection ID). That's the whole
change. Keep the 1 Hz gate and the `seq` increment as-is.

**Test A.** Run the VI, then in the venv: `python examples\monarch_listen.py`.
You should see `seq` incrementing, `state` = your constant, and the fields you
set on the constant (e.g. `speed_ref`) — with `unmapped=[]`. If `unmapped` is
non-empty, the cluster's field labels drifted; capture one flattened line and run
`python tools\compare_flatten.py <that file>` to see which.

### Part B — switch to live data

Two wire swaps, nothing else:

1. **Step 1's constant → the live `PC_ControlSettings`** value.
2. **Step 3's constant → the real `CURRENT SYSTEM STATE`** (I8) from the
   StateMachine.

Both come from wherever the running application already publishes them — the same
queue / FGV / shared variable / notifier the UI reads. The gateway loop taps a
**read-only copy**; it must never modify them. Now Python records real runs and
`monarch.jsonl` becomes a genuine corpus — **that completes Stage 1.**

### Notes

- **Payload size:** the full cluster is ~64 fields ≈ a 1.6 KB line at 1 Hz —
  trivial; one `TCP Write` sends it.
- **Keep it in lockstep:** if anyone edits `APC_ControlSettings.ctl`, re-run the
  flatten diff (`docs/monarch-flatten-diff.md`) so the Python model and the
  gateway agree again.
- **Fast check without Python:** `telnet 127.0.0.1 5020` should show a long
  `{"type":"telemetry",…,"settings":{…}}` line once per second.

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
