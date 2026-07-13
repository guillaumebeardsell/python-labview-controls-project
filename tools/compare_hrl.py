"""Score the desktop SIL-0 harness (LabVIEW `APC_HRL` on synthetic traces)
against the generator's ground truth.

    python tools/compare_hrl.py <traces_dir>/truth.json <labview_metrics.csv>

The LabVIEW harness (globals-free, on `My Computer`) reads the
`cycle_NNNN_phased.csv` files from `tools/gen_cas_traces.py`, runs each
cylinder through `APC_HRL`, and writes ONE CSV row per (cycle, cylinder):

    cycle,cylinder,imep_g,imep_n,pmax,pmax_atdc,ca50

(header row optional; extra columns ignored). This tool joins that against
`truth.json` and reports per-metric agreement, so you can (a) confirm the HRL
math matches the spec and (b) see where the LabVIEW volume/pegging quirks
(the author's "FIX STROKE CALC" etc.) bite. Exit code 1 if any metric exceeds
tolerance — usable as a regression gate.

Absolute magnitudes only line up if the harness's engine geometry
(bore/stroke/rod/CR) matches the `--bore/--stroke/...` used to generate the
traces; otherwise expect a consistent IMEP scale factor (still a useful check
— the *shape* and CA50 should match regardless).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# metric -> (truth.json key, absolute tolerance, unit)
METRICS = {
    "imep_g": ("imep_g_bar", 0.15, "bar"),
    "imep_n": ("imep_n_bar", 0.15, "bar"),
    "pmax": ("pmax_bar", 1.0, "bar"),
    "pmax_atdc": ("pmax_atdc", 1.0, "CAD"),
    "ca50": ("ca50_atdc", 1.5, "CADATDC"),  # fired cylinders only
}


def load_labview(path: Path) -> dict[tuple[int, int], dict]:
    """Read the harness CSV -> {(cycle, cyl): {metric: value}}.

    Accepts either column layout after cycle,cylinder:
      7 cols: cycle,cylinder,imep_g,imep_n,pmax,pmax_atdc,ca50
      6 cols: cycle,cylinder,imep_g,imep_n,pmax,ca50   (no Pmax-angle field)
    """
    out: dict[tuple[int, int], dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    start = 1 if rows and not _is_num(rows[0][0]) else 0  # skip a header row
    data = [r for r in rows[start:] if len(r) >= 2 and _is_num(r[0])]
    ncols = max((len(r) for r in data), default=0)
    order = (
        ("imep_g", "imep_n", "pmax", "pmax_atdc", "ca50") if ncols >= 7
        else ("imep_g", "imep_n", "pmax", "ca50")
    )
    for r in data:
        cycle, cyl = int(float(r[0])), int(float(r[1]))
        vals = {name: float(r[idx]) for idx, name in enumerate(order, start=2)
                if idx < len(r) and _is_num(r[idx])}
        out[(cycle, cyl)] = vals
    return out


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare LabVIEW APC_HRL output vs synthetic-trace ground truth")
    ap.add_argument("truth_json", help="truth.json from gen_cas_traces.py")
    ap.add_argument("labview_csv", help="harness CSV: cycle,cylinder,imep_g,imep_n,pmax,pmax_atdc,ca50")
    ap.add_argument("--imep-tol", type=float, default=None, help="override IMEP tolerance [bar]")
    args = ap.parse_args()

    truth = json.loads(Path(args.truth_json).read_text(encoding="utf-8"))["cycles"]
    lv = load_labview(Path(args.labview_csv))
    tol = dict(METRICS)
    if args.imep_tol is not None:
        tol["imep_g"] = (tol["imep_g"][0], args.imep_tol, "bar")
        tol["imep_n"] = (tol["imep_n"][0], args.imep_tol, "bar")

    checked = 0
    fails: list[str] = []
    missing: list[str] = []
    worst: dict[str, float] = {m: 0.0 for m in tol}

    for cyc_s, rec in truth.items():
        cyc = int(cyc_s)
        for cyl_s, t in rec["cylinders"].items():
            cyl = int(cyl_s)
            got = lv.get((cyc, cyl))
            if got is None:
                missing.append(f"cycle {cyc} cyl {cyl}")
                continue
            for m, (tkey, mtol, unit) in tol.items():
                if tkey not in t or m not in got:
                    continue  # e.g. ca50 only on fired cylinders
                diff = abs(got[m] - t[tkey])
                worst[m] = max(worst[m], diff)
                checked += 1
                if diff > mtol:
                    fails.append(
                        f"cycle {cyc:>3} cyl {cyl}: {m:9} LabVIEW={got[m]:+8.3f} "
                        f"truth={t[tkey]:+8.3f}  |Δ|={diff:.3f} {unit} (tol {mtol})"
                    )

    print(f"=== APC_HRL vs truth: {args.labview_csv} ===")
    print(f"comparisons: {checked}   ({len(truth)} cycles)")
    if missing:
        print(f"\nMISSING in LabVIEW output ({len(missing)}):")
        for m in missing[:20]:
            print("  " + m)
    print("\nworst |Δ| per metric:")
    for m, (_, mtol, unit) in tol.items():
        flag = "  <-- OVER TOL" if worst[m] > mtol else ""
        print(f"  {m:9} {worst[m]:.3f} {unit:9} (tol {mtol}){flag}")
    if fails:
        print(f"\nFAILURES ({len(fails)}):")
        for f in fails[:40]:
            print("  " + f)
        if len(fails) > 40:
            print(f"  … and {len(fails) - 40} more")
        return 1
    if missing:
        print("\nAGREE within tolerance for all present rows, but some rows missing.")
        return 1
    print("\nALL metrics within tolerance ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
