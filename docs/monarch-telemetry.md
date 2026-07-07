# MONARCH Telemetry — the read-only pipeline

> **Status: LIVE (2026-07-06).** The gateway (`APC_PC_PythonGateway.vi` in the
> MONARCH project) streams the real, live `PC_ControlSettings` + system state at
> 1 Hz; Python decodes and records it (`monarch.jsonl`) with zero unmapped
> fields. **Remaining on this pipeline:** pre-wire the shadow-mode extras
> (§ below) — that's Phase A2 of `docs/migration-plan.md`, where overall project
> status lives.

The pipeline streams the real engine state to Python once per second, decoded
into the confirmed `ControlSettings` contract (docs/monarch-control-settings.md).
Python only **observes** — no commands, no authority — so it was the safe first
step of the migration. This is what `examples/monarch_listen.py` does.

*(Naming note: earlier work called this "Stage 1" and the shadow-mode envelope
fields "Stage-2 fields". The phased plan supersedes that numbering: this
pipeline = done; the extras below = Phase A2.)*

## Wire format

One JSON object per line (the ICD framing, LF/CRLF terminated):

```json
{"type":"telemetry","seq":42,"ts":1783041300.5,"system_state":3,
 "warnings_limit":3,"manual_state":0,"force_state":false,
 "settings":{ …raw Flatten To JSON of PC_ControlSettings… },
 "limited_settings":{ …raw Flatten To JSON of Limited_ControlSettings… }}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | `"telemetry"` | — |
| `seq` | int | Per-connection frame counter |
| `ts` | float | LabVIEW wall-clock time (seconds since epoch) |
| `system_state` | int | The 9056 StateMachine's `SYSTEM STATE` output (this-tick decision, tapped *before* the feedback node): −1 SAFE, 0 STAND_BY, 1 MOTORING, 2 IDLING, 3 FIRING |
| `settings` | object | **Raw** `Flatten To JSON` of `PC_ControlSettings` (the request) |
| `warnings_limit` | int | Shadow extra (A2.1): `STATE LIMITATION FROM WARNINGS` feeding the SM (−1…3) |
| `manual_state` | int | Shadow extra (A2.1): `ManualState_SM` |
| `force_state` | bool | Shadow extra (A2.1): `ForceState_SM` (lowercase `true`/`false` via a Select — a bare boolean formats as `TRUE`/`FALSE` and breaks JSON) |
| `limited_settings` | object | Shadow extra (A2.1): **raw** `Flatten To JSON` of `Limited_ControlSettings` (the SM's clamped output) |

**Envelope history:** the read-only pipeline (Part A/B) shipped `system_state` +
`settings` only. Phase A2.1 added the four **shadow extras** above (grew
`Format Into String` from 3 → 8 args) and **re-tapped `system_state`** from the
old 9049-side `9049_Global_SYSTEMSTATE` echo (which froze when the 9049 loops
weren't running) to the 9056 StateMachine's own `SYSTEM STATE` output — so state,
warnings, and `limited_settings` are all the same source and same tick. The
node-by-node A2.1 wiring recipe (incl. the exact target string) lives in
`docs/phases/phase-a-shadow-brain.md`.

**Cadence note:** the gateway samples at 1 Hz, but the 9056 SM/limiter loop it
reads runs at ~50 Hz (DAQ-paced) — so each frame is a 1 Hz *sample* of a converged
state, not the loop rate. See the shadow-compare convergence caveat in
`docs/shadow-findings.md`.

The key idea: **`settings` is LabVIEW's raw flatten** — original field labels,
PID references nested under `"PID control references"`, quirks and all. Python
maps it to the typed model with `control_settings_from_labview()`
(`supervisory/monarch/labview_mapping.py`), so **the gateway VI does no
key-renaming** — it just flattens the cluster and drops it in. Unknown labels
are surfaced (`MonarchTelemetry.unmapped`), never fatal.

## LabVIEW gateway — send the real envelope, node by node

> **Built and verified.** Part A (constant) passed 2026-07-05; Part B (live
> data) passed 2026-07-06 — live value changes and real state tracked, 0
> unmapped. **A2.1 extended the envelope to the 8-field shadow form** (see the
> field table above) and re-tapped `system_state` to the 9056 StateMachine's
> `SYSTEM STATE` output; live shadow compare then agreed 100% across all five
> states (`docs/shadow-findings.md`). The 9056 StateMachine writes `SYSTEM STATE`
> via a network-published shared variable; the PC gateway reads it. This section
> is the *original* 4-field build history — for the shadow-extras additions
> follow `docs/phases/phase-a-shadow-brain.md` A2.1.

This is the build history of the gateway (the hello VI became
`APC_PC_PythonGateway.vi`). You replace **only** the telemetry
`Format Into String` and add three inputs to it — the 1 Hz timer, `seq` shift
register, `TCP Write`, framing, the ack reply, and the reconnect handling all
stay exactly as they are. This exact envelope was verified to decode on the
Python side (`monarch_parser`), so if the flatten matches (it did — the contract
diff → AGREE) there's nothing new to validate.

### Where this VI lives

The gateway is **`APC_PC_PythonGateway.vi`, in the MONARCH project** — it needs
the `APC_ControlSettings.ctl` typedef and the live `PC_ControlSettings` +
`CURRENT SYSTEM STATE`, all of which live in MONARCH. It grew directly out of the
connectivity-test hello VI: the working VI was renamed to `APC_PC_PythonGateway.vi`
(File → Save As → *Rename*, from inside LabVIEW, so the project reference updates).
The connectivity-experiment walkthrough is preserved in `docs/hello-vi.md`; there
is no separate live "hello-vi.vi" to maintain.

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
`monarch.jsonl` becomes a genuine corpus — the read-only pipeline is complete.

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
# against the real gateway (on the control-room PC): just run the observer
python examples/monarch_listen.py

# offline / no LabVIEW: substitute the sim gateway in terminal 1
python -m supervisory.monarch.simserver_monarch --speedup 5
```

`monarch_listen.py` connects (reusing `TcpPlantLink` with `monarch_parser`),
decodes each frame to `MonarchTelemetry` (typed `system_state` + `settings:
ControlSettings`), logs a one-line status, and records every frame to
`monarch.jsonl`. It sends a 1 Hz heartbeat so a watchdog-guarded gateway stays
live, but issues no commands.

The `monarch.jsonl` recordings are the replay corpus for the shadow-compare
harness (Phase A2): the ported state logic is re-run against recorded telemetry
and its decisions diffed against LabVIEW's offline.

## Shadow-mode extras — the fuller envelope (Phase A2 gateway task — NEXT)

The read-only pipeline needs only `system_state` + `settings`. Shadow mode
(Phase A) also needs the rest of the StateMachine's I/O that lives **outside**
the ControlSettings cluster — each a sibling top-level field, same pattern as
`system_state`:

```json
{"type":"telemetry","seq":42,"ts":1783041300.500,
 "system_state":2,
 "warnings_limit":2,"manual_state":-128,"force_state":false,
 "settings":{ …Flatten To JSON of PC_ControlSettings… },
 "limited_settings":{ …Flatten To JSON of Limited_ControlSettings… }}
```

| Field | Type | LabVIEW source | Role |
|---|---|---|---|
| `system_state` | int | `CURRENT SYSTEM STATE` (I8) | StateMachine **output** — the decided state (already wired and live) |
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
them** (`MonarchTelemetry`) — they're optional, so today's gateway is
unaffected, and the moment you wire one it's decoded, logged, and recorded. No
Python change needed when you pre-wire. Note the inputs (`warnings_limit`,
`manual_state`, `force_state`) live on cRIO-9056 at the StateMachine call site —
like `system_state`, they'll need publishing to the PC (same shared-variable
pattern) if they aren't already.

Rendering `force_state` as a boolean in `Format Into String`: use a Select
(`True`→`true` string, `False`→`false` string) into a `%s`, since `%d` would
give `1`/`0` — the model accepts JSON `true`/`false`.

## Status (this pipeline)

- [x] `ControlSettings` contract confirmed against a live capture (diff → AGREE)
- [x] Raw-flatten → typed model decoder (`control_settings_from_labview`), tested
      against the real capture
- [x] Telemetry envelope + parser (`MonarchTelemetry`, `monarch_parser`)
- [x] Read-only observer + JSONL recorder; sim gateway for offline testing
- [x] Gateway Part A — envelope from a constant, verified on the real VI (2026-07-05)
- [x] Gateway Part B — **live** `PC_ControlSettings` + real `CURRENT SYSTEM STATE`
      (via new shared variable), verified live-value tracking (2026-07-06)
- [x] Shadow-mode extras Python-ready (optional fields; decode+record when pre-wired)
- [ ] **Pre-wire the shadow-mode extras in the gateway** (`warnings_limit`,
      `manual_state`, `force_state`, `limited_settings`) — Phase A2

For overall project status and what comes after this pipeline, see
`docs/migration-plan.md`.
