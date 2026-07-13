"""Recommend 9049 cylinder-pressure warning thresholds from a SIL run's metrics.

    python tools/tune_thresholds.py motored_set/labview_metrics.csv --mode motored
    python tools/tune_thresholds.py fired_set/labview_metrics.csv   --mode fired

Purpose (see docs/9049-openloop-audit.md F3): the 9049's `Pcyl_Diag` compares
each combustion metric against a Warning and an Error limit from the
`9049_WarningLevels` FGV; `CombCluster2Array` OR-reduces the **Error** flags,
**latches** them (feedback nodes, cleared only by `APC_SLAVE_ClearWarnings`),
and drives `9049_Global_CylPressError` — which gates spark & DI. So one spurious
Error sample latches a fire-veto until an operator clears it. Those limits have
**never been set for this engine**, and several checks **false-trip** on a
motored engine (CA50 is noise, `Expected IMEP` is an unwired 0 → the misfire
check trips on anything). This tool reads the metrics the SIL harness computed
(`APC_SIL0_HRL_Desktop` → `labview_metrics.csv`) and emits a **recommended
Warning/Error set** with margin, plus the **disarm list** for checks that can't
be meaningfully armed in this mode. Feed the result into the 9049 warning XML
(via the `_UI_Errors` CYLINDER screen) *before* the run.

The confirmed `9049_WarningLevels` fields (each has a `…Warning` and `…Error`
variant; verified from `APC_9049_LoadWarningConfig.vi` / `APC_Pcyl_Diag.vi`):
  metric flag        →  threshold field       (compared value)
  maximum pressure   →  MaxPCylMax            (Pmax)
  cyclic variability →  MaxIMEPstd            (running IMEPn std)
  misfire cyl-to-cyl →  MaxDevFromAvg         (|IMEPg − cylinder-mean|)
  misfire self reg   →  MaxDevFromSelfAvg     (|IMEPn − own running mean|)
  misfire from IMEP  →  MaxDevFromExpectedIMEP(|IMEPn − Expected IMEP|)
  knock              →  MAPOmax               (MAPO — NOT in the metrics CSV)
  late combustion    →  CA50max               (CA50)
plus `samples for running IMEP std` (I32) — the std window length (default 20).

`MAPOmax` (knock) and `MaxIMEPstd` auto-tune **only if** the harness CSV carries
`mapo` / `imepstd` columns (header-named — the loader matches columns by name).
Without them: `MaxIMEPstd` falls back to a value computed from the IMEPn spread,
and `MAPOmax` is DISARM for motoring (no combustion ⇒ no knock) / hand-set for
firing. Add both to the `APC_SIL0_HRL_Desktop` Build-Array (they're already in
`CombustionAnalysisCluster`) to close that out.

Input CSV columns (from the SIL harness): cycle,cylinder,imep_g,imep_n,pmax,ca50
(6-col) — the same file `tools/compare_hrl.py` scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
from pathlib import Path

# header aliases → canonical field (normalized: lowercased, non-alphanumerics stripped)
_ALIASES = {
    "cycle": {"cycle"},
    "cyl": {"cylinder", "cyl"},
    "imep_g": {"imepg", "imepgbar"},
    "imep_n": {"imepn", "imepnbar"},
    "pmax": {"pmax", "pmaxbar"},
    "pmax_atdc": {"pmaxatdc"},
    "ca50": {"ca50", "ca50atdc", "ca50cadatdc"},
    "mapo": {"mapo", "mapobarcad"},          # knock metric — present only if the harness emits it
    "imepstd": {"imepstd", "imepstdbar"},    # analytics running std — else computed from imep_n
}
_FIELDS = ("cycle", "cyl", "imep_g", "imep_n", "pmax", "pmax_atdc", "ca50", "mapo", "imepstd")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _header_map(header: list[str]) -> dict[str, int] | None:
    """Map a header row → {canonical_field: column_index}, or None if it names nothing we know."""
    idx: dict[str, int] = {}
    for i, cell in enumerate(header):
        n = _norm(cell)
        for field, names in _ALIASES.items():
            if n in names and field not in idx:
                idx[field] = i
    return idx or None


def load(path: Path) -> list[dict]:
    """Read the harness metrics CSV → list of per-(cycle,cyl) dicts.

    Header-aware: if the first row names columns, fields are matched by name (so
    the harness can add `mapo`/`imepstd`/`pmax_atdc` in any order). Otherwise the
    positional fallback is `cycle,cyl,imep_g,imep_n,pmax[,pmax_atdc],ca50`.
    Every row carries all `_FIELDS`; absent optional metrics are None.
    """
    raw = list(csv.reader(path.open(encoding="utf-8-sig")))
    hmap = _header_map(raw[0]) if raw and raw[0] and not _num(raw[0][0]) else None
    rows: list[dict] = []
    for r in raw:
        if not r or not _num(r[0]):
            continue  # skip header / blank lines
        rec: dict = {f: None for f in _FIELDS}
        if hmap is not None:
            for field, i in hmap.items():
                if i < len(r) and _num(r[i]):
                    rec[field] = float(r[i])
        else:  # positional
            rec["imep_g"], rec["imep_n"], rec["pmax"] = float(r[2]), float(r[3]), float(r[4])
            ca50_i = 6 if len(r) >= 7 else 5  # 7-col layout inserts pmax_atdc before ca50
            rec["cycle"], rec["cyl"] = float(r[0]), float(r[1])
            if len(r) > ca50_i and _num(r[ca50_i]):
                rec["ca50"] = float(r[ca50_i])
        rec["cycle"], rec["cyl"] = int(rec["cycle"] or 0), int(rec["cyl"] or 0)
        rows.append(rec)
    return rows


def _num(s: str) -> bool:
    try:
        float(s); return True
    except (ValueError, TypeError):
        return False


def cyl_to_cyl_spread(rows: list[dict]) -> float:
    """Max within-cycle IMEPg spread (max-min across the 6 cylinders)."""
    by_cycle: dict[int, list[float]] = {}
    for r in rows:
        by_cycle.setdefault(r["cycle"], []).append(r["imep_g"])
    return max((max(v) - min(v) for v in by_cycle.values() if len(v) > 1), default=0.0)


def running_imep_std(rows: list[dict]) -> float:
    """Worst per-cylinder IMEPn std across cycles (the cyclic-variability metric)."""
    by_cyl: dict[int, list[float]] = {}
    for r in rows:
        by_cyl.setdefault(r["cyl"], []).append(r["imep_n"])
    return max((st.pstdev(v) for v in by_cyl.values() if len(v) > 1), default=0.0)


def self_avg_dev(rows: list[dict]) -> float:
    """Worst deviation of any cycle's IMEPn from that cylinder's own mean.

    This is the `misfire self reg` metric (`MaxDevFromSelfAvg`), distinct from
    the cyl-to-cyl spread (`MaxDevFromAvg`): here each cylinder is judged
    against its OWN running average, not the fleet average."""
    by_cyl: dict[int, list[float]] = {}
    for r in rows:
        by_cyl.setdefault(r["cyl"], []).append(r["imep_n"])
    worst = 0.0
    for v in by_cyl.values():
        if len(v) > 1:
            m = st.mean(v)
            worst = max(worst, max(abs(x - m) for x in v))
    return worst


def main() -> int:
    ap = argparse.ArgumentParser(description="Recommend 9049 CylPress warning thresholds from SIL metrics")
    ap.add_argument("metrics_csv", help="labview_metrics.csv from the SIL harness")
    ap.add_argument("--mode", choices=["motored", "fired"], required=True)
    ap.add_argument("--pmax-hard-limit", type=float, default=None,
                    help="engine's physical max cylinder pressure [bar] — the safety ceiling; "
                         "the recommended error limit is min(observed*margin, this)")
    ap.add_argument("--pmax-margin", type=float, default=1.30, help="error-limit margin over observed peak")
    ap.add_argument("--std-margin", type=float, default=5.0, help="margin over observed IMEP std")
    ap.add_argument("--imep-std-samples", type=int, default=20,
                    help="`samples for running IMEP std` window length (I32) to write into the XML")
    ap.add_argument("--json", action="store_true", help="also print a JSON block of the numbers")
    args = ap.parse_args()

    rows = load(Path(args.metrics_csv))
    if not rows:
        raise SystemExit("no numeric rows found in the metrics CSV")
    pmax = [r["pmax"] for r in rows]
    imn = [r["imep_n"] for r in rows]
    obs_pmax, obs_spread = max(pmax), cyl_to_cyl_spread(rows)
    obs_selfdev = self_avg_dev(rows)
    # prefer the analytics IMEPstd column when the harness emits it; else compute from IMEPn
    imepstd_col = [r["imepstd"] for r in rows if r["imepstd"] is not None]
    obs_std = max(imepstd_col) if imepstd_col else running_imep_std(rows)
    std_src = "analytics IMEPstd column" if imepstd_col else "computed from IMEPn spread"
    mapo_col = [r["mapo"] for r in rows if r["mapo"] is not None]
    warn_margin = args.pmax_margin - 0.10

    # --- build the recommendation ---
    DISARM = 1e6  # sentinel "off" — a limit no real signal reaches
    rec: dict[str, dict] = {}

    def add(field, warn, err, unit, why):
        rec[field] = dict(warn=warn, err=err, unit=unit, why=why)

    pmax_err = obs_pmax * args.pmax_margin
    if args.pmax_hard_limit is not None:
        pmax_err = min(pmax_err, args.pmax_hard_limit)
    add("MaxPCylMax", round(obs_pmax * warn_margin, 1), round(pmax_err, 1), "bar",
        f"observed peak {obs_pmax:.1f} → +{int((args.pmax_margin-1)*100)}% (never let a real reading reach it, "
        f"but hardware safety ceiling wins if lower)")

    add("MaxIMEPstd", round(max(obs_std * (args.std_margin - 1), 0.2), 3),
        round(max(obs_std * args.std_margin, 0.3), 3), "bar",
        f"observed cyclic IMEPn std {obs_std:.3f} → ×{args.std_margin:g} (floor 0.3); "
        "prevents first-acquisition zero-padded-cycle latch")
    add("MaxDevFromAvg", round(max(obs_spread * 3, 0.5), 3), round(max(obs_spread * 4, 0.8), 3), "bar",
        f"observed cyl-to-cyl IMEPg spread {obs_spread:.3f} → generous (identical synthetic cyls ⇒ ~0)")
    add("MaxDevFromSelfAvg", round(max(obs_selfdev * 3, 0.5), 3), round(max(obs_selfdev * 4, 0.8), 3), "bar",
        f"observed self-avg IMEPn dev {obs_selfdev:.3f} → generous (per-cyl cyclic misfire catch)")

    if args.mode == "motored":
        add("MaxDevFromExpectedIMEP", DISARM, DISARM, "bar",
            "DISARM — motored IMEP≈-1 and Expected-IMEP is the unwired-0 trap (F3); "
            "re-arm only when Expected IMEP is actually driven")
        add("CA50max", DISARM, DISARM, "CADATDC",
            "DISARM — no combustion, CA50 is noise (MFB of pure motoring)")
        add("MAPOmax", DISARM, DISARM, "bar/CAD",
            "DISARM — motoring cannot knock (no combustion)"
            + (f"; observed MAPO≤{max(mapo_col):.3f}" if mapo_col else "; MAPO not in CSV anyway"))
    else:  # fired
        ca50 = [r["ca50"] for r in rows if r["ca50"] is not None]
        if ca50:
            add("CA50max", round(max(ca50) + 5, 1), round(max(ca50) + 10, 1), "CADATDC",
                f"observed fired CA50 up to {max(ca50):.1f} → +5/+10° (late-combustion catch)")
        add("MaxDevFromExpectedIMEP", round(st.mean(imn) * 0.4, 2), round(st.mean(imn) * 0.6, 2), "bar",
            f"fired IMEPn mean {st.mean(imn):.1f} → 40%/60% deviation = misfire; "
            "REQUIRES Expected IMEP wired/commanded to the true value first")
        if mapo_col:  # harness now emits MAPO → tune knock from observed clean-combustion amplitude
            obs_mapo = max(mapo_col)
            add("MAPOmax", round(max(obs_mapo * 2, 0.5), 3), round(max(obs_mapo * 3, 1.0), 3), "bar/CAD",
                f"observed clean-combustion MAPO≤{obs_mapo:.3f} → ×2/×3 (floor 0.5/1.0) as a STARTING "
                "point; refine from knock-onset sweep data before relying on it")

    # --- report ---
    print(f"=== 9049 CylPress warning-limit recommendation ({args.mode}) ===")
    print(f"source: {args.metrics_csv}   ({len(rows)} cyl-cycles)")
    print(f"observed: Pmax≤{obs_pmax:.1f} bar | IMEPn mean {st.mean(imn):+.2f}, cyclic std {obs_std:.3f} "
          f"({std_src}) | cyl-to-cyl spread {obs_spread:.3f} | self-avg dev {obs_selfdev:.3f} bar\n")
    print("each field maps to `<field>Warning` and `<field>Error` in 9049_WarningLevels:")
    print(f"{'field':24} {'Warning':>10} {'Error':>10}  unit")
    print("-" * 70)
    for f, d in rec.items():
        w = "—" if d["warn"] is None else ("DISARM" if d["warn"] >= DISARM else f"{d['warn']:g}")
        e = "—" if d["err"] is None else ("DISARM" if d["err"] >= DISARM else f"{d['err']:g}")
        print(f"{f:24} {w:>10} {e:>10}  {d['unit']}")
    print(f"{'samples for running IMEP std':24} {'—':>10} {args.imep_std_samples:>10d}  count (I32 window)")
    print("\nrationale:")
    for f, d in rec.items():
        print(f"  {f}: {d['why']}")
    if args.mode == "fired" and not mapo_col:
        print("\nNOTE: MAPOmax (knock) NOT auto-tuned — no MAPO column in the metrics CSV. It MUST be")
        print("      hand-set from knock-sensor/MAPO data before firing, or add a MAPO harness column.")
    elif args.mode == "motored":
        print("\nNOTE: this is the MOTORING set. Generate a separate --mode fired set and re-run for the")
        print("      firing limits before light-off; keep two saved warning-XML profiles.")

    if args.json:
        print("\n" + json.dumps({"mode": args.mode, "observed": {"pmax": obs_pmax, "imep_std": obs_std,
              "cyl_spread": obs_spread}, "limits": rec}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
