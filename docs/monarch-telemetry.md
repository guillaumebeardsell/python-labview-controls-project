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

### Where this VI lives

The gateway belongs **in the MONARCH project**, not the standalone Hello-VI
folder — Part A needs the `APC_ControlSettings.ctl` typedef and Part B needs the
live `PC_ControlSettings` + `CURRENT SYSTEM STATE`, all of which live in MONARCH.
Save a copy of the working hello VI into `C:\LabVIEW PROJECT\MONARCH\` (e.g.
`APC_PC_PythonGateway.vi`), and **Add → File** it to the MONARCH project. Keep
the original `hello-vi.vi` as your throwaway connectivity tester.

Architectural guardrail: the gateway runs as its **own independent loop** reading
a *read-only copy* of the published settings — it never writes hardware and never
sits in the control/safety path. If it (or Python) hangs, the control loops are
untouched. Telemetry-out only.

### Part A — prove the envelope with a constant (do this first)

**Step 1 — a ControlSettings value to flatten.** With the VI in the MONARCH
project, open `controls` in the Project Explorer and **drag
`APC_ControlSettings.ctl` onto the block diagram** — it drops as a constant of
that type. Right-click it → *View Cluster Size* isn't
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

## Stage-2 preview — the fuller envelope (optional to pre-wire now)

Stage 1 needs only `system_state` + `settings`. Stage-2 shadow mode also needs
the rest of the StateMachine's I/O that lives **outside** the ControlSettings
cluster — each a sibling top-level field, same pattern as `system_state`:

```json
{"type":"telemetry","seq":42,"ts":1783041300.500,
 "system_state":2,
 "warnings_limit":2,"manual_state":-128,"force_state":false,
 "settings":{ …Flatten To JSON of PC_ControlSettings… },
 "limited_settings":{ …Flatten To JSON of Limited_ControlSettings… }}
```

| Field | Type | LabVIEW source | Role |
|---|---|---|---|
| `system_state` | int | `CURRENT SYSTEM STATE` (I8) | StateMachine **output** — the decided state (already wired in Stage 1) |
| `warnings_limit` | int | `STATE LIMITATION FROM WARNINGS` (I8) | input — max state warnings permit (same −1..3 encoding) |
| `manual_state` | int | `ManualState` (I8) | input — manual state override (send your "no override" sentinel as-is) |
| `force_state` | bool | `ForceState` | input — force-state override |
| `settings` | object | `Flatten To JSON` of `PC_ControlSettings` | input — what was requested |
| `limited_settings` | object | `Flatten To JSON` of `Limited_ControlSettings` | **output** — what the StateMachine allowed |

Why these exact fields: shadow mode has Python recompute the state and the
limiting from the **inputs** (`settings.requested_mode`, force idling/motoring &
e-stop inside `settings`, plus `warnings_limit` / `manual_state` / `force_state`)
and compare against LabVIEW's **outputs** (`system_state`, `limited_settings`).
That's the whole comparison, so this is the complete set.

To add each in the gateway: one more `Format Into String` argument (a `%d`, `%d`,
a boolean rendered as `true`/`false`, and a second `%s` for the
`Limited_ControlSettings` flatten). **The Python side already accepts all of
them** (`MonarchTelemetry`) — they're optional, so a Stage-1 gateway is
unaffected, and the moment you wire one it's decoded, logged, and recorded. No
Python change needed when you pre-wire.

Rendering `force_state` as a boolean in `Format Into String`: use a Select
(`True`→`true` string, `False`→`false` string) into a `%s`, since `%d` would
give `1`/`0` — the model accepts JSON `true`/`false`.

## Status

- [x] `ControlSettings` contract confirmed against a live capture
- [x] Raw-flatten → typed model decoder (`control_settings_from_labview`), tested
      against the real capture
- [x] Telemetry envelope + parser (`MonarchTelemetry`, `monarch_parser`)
- [x] Read-only observer + JSONL recorder; sim gateway for offline testing
- [x] Gateway Part A verified on the real VI (envelope decodes, 0 unmapped, state propagates)
- [x] Stage-2 envelope fields Python-ready (optional; decode+record when pre-wired)
- [ ] Point the gateway at the live cluster → record a real run (completes Stage 1)
- [ ] (Stage 2) pre-wire `warnings_limit` / `manual_state` / `force_state` / `limited_settings`
