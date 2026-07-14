# trace-sets/ — synthetic CAS trace sets (SIL scratch)

Home for every synthetic pressure-trace set used by the SIL work (`motored_set/`,
`fired_set/`, `flat_set/`, `sil0_traces/`, …). Everything in here except this README is
**gitignored** — the sets are regenerable:

```
python tools/gen_cas_traces.py trace-sets/motored_set --cycles 30 --mode motored \
  --bore 0.112 --stroke 0.149 --conrod 0.217 --cr 12.8 --pin-offset=-0.00099
```

Each set contains `cycle_NNNN.csv` (9×7200 raw), `cycle_NNNN_phased.csv` (6×7200 —
feed `APC_HRL` / the `APC_SIL0_HRL_Desktop.vi` harness directly), `truth.json`
(ground-truth metrics), and — after a harness run — `labview_metrics.csv`.

Workflow: `docs/sil0-scope-of-work.md`. Scoring/tuning:
`tools/compare_hrl.py`, `tools/tune_thresholds.py`.
