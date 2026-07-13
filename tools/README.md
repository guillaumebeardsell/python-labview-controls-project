# tools/ — operator & verification utilities

Standalone scripts (stdlib + this package only; no extra deps). Each has a
`--help` and a module docstring with usage. Grouped by what you're doing.

## SIL-0 — validate the 9049 combustion analytics off-hardware

A pipeline: **generate** synthetic pressure traces → run them through the
LabVIEW desktop harness (`APC_SIL0_HRL_Desktop.vi`, on My Computer) → **score**
the output → **tune** the warning limits. No engine, no cRIO.

```
gen_cas_traces.py ──► cycle_NNNN_phased.csv ──►  APC_SIL0_HRL_Desktop.vi  ──► labview_metrics.csv
        │                    + truth.json                                          │
        │                         └──────────────►  compare_hrl.py  ◄──────────────┤  (HRL math == truth?)
        └────────────────────────────────────────►  tune_thresholds.py  ◄──────────┘  (recommend 9049 limits)
```

| Tool | Does |
|---|---|
| `gen_cas_traces.py` | Generate synthetic CAS cylinder-pressure cycles with the real MONARCH geometry (`--bore/--stroke/--conrod/--cr/--pin-offset`), modes motored/fired/mixed, injectable misfire/knock. Emits raw `cycle_NNNN.csv` (9×7200), phased `cycle_NNNN_phased.csv` (6×7200, feed `APC_HRL` directly), and `truth.json`. |
| `compare_hrl.py` | Score the harness `labview_metrics.csv` vs `truth.json` (per-metric worst-Δ, pass/fail, exit 1 on tolerance breach). Confirms the ported HRL/IMEP/CA50 math. |
| `tune_thresholds.py` | Recommend the `9049_WarningLevels` limits (all 7 metrics × Warning/Error + the std window) from a motored/fired metrics CSV, with the motoring disarm list. Header-aware: auto-tunes knock (`MAPOmax`) and uses the real `IMEPstd` **when the harness CSV includes those columns**; else DISARMs/hand-sets them. `--pmax-hard-limit` clamps to the engine ceiling. |

See `docs/9049-openloop-audit.md` §7 (SIL plan, harness recipe) for the full
workflow and the confirmed field↔flag↔metric map.

## Command path — exercise & verify the Python⇄LabVIEW link

Needs a gateway (real `APC_PC_PythonGateway.vi`, or a fake:
`python -m supervisory.monarch.simserver_monarch`).

| Tool | Does |
|---|---|
| `send_command.py` | Send one raw command to the gateway and print the ACK/NACK — the B3.d/B4 by-hand command probe. |
| `run_drills.py` | B4 bench-drill runner — the machine-runnable subset of the drill table (crash/freeze/flood/source-flip…). Writes a drill log. |
| `shadow_compare.py` | Replay/watch MONARCH telemetry and diff LabVIEW's live decisions against the ported `StateMachine` (shadow-mode agreement). |
| `capture_line.py` | Capture one raw telemetry line from the gateway and diagnose it (framing/parse smoke test). |

Command-path as-built + evidence: `docs/command-path-asbuilt.md`; protocol: `docs/icd.md`.

## Data contract — keep the model and LabVIEW typedef in lockstep

| Tool | Does |
|---|---|
| `compare_flatten.py` | Diff a LabVIEW `Flatten To JSON` capture of `APC_ControlSettings` against the Python contract; guards typedef drift. |

Workflow: `docs/monarch-flatten-diff.md`; contract: `docs/monarch-control-settings.md`.
