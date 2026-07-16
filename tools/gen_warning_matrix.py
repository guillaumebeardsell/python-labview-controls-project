"""Generate the SIL-1 warning/error false-trip matrix: trace sets + drill XML +
expected-trip manifest.

    python tools/gen_warning_matrix.py
    python tools/gen_warning_matrix.py --xlsx "docs/cRIO9049 Warning Matrix.xlsx"

(default output dir: trace-sets/warning_matrix)

Purpose (docs/9049-openloop-audit.md §7 SIL-0 Step 5 / SIL-1): prove each of the
7 `Pcyl_Diag` warnings/errors trips, LATCHES (`CombCluster2Array` feedback nodes
→ `9049_Global_CylPressError`), and clears via CLEAR WARNINGS — by feeding
synthetic pressure trace sets through the CAS_loop sim-pressure branch while
`SimEnable` runs the virtual crankshaft (injection spec:
docs/sil1-scope-of-work.md).

What one run emits under <out_dir>/:
  <set>/cycle_NNNN.csv (+_phased.csv, truth.json)  - 7 sets via gen_cas_traces
  CylWarningLevels.drill.xml   - ALL fields armed (fired-profile values derived
      from baseline_fired truth) — copy to the cRIO for the drill, RESTORE the
      motoring XML after
  manifest.md / manifest.json  - per set: recipe + computed expected flags at
      Warning and Error level + pass criteria + the swap/restore procedure

Expected trips are COMPUTED from each set's truth.json against the drill
thresholds (Pmax/CA50/IMEP directly; running std + self-avg dev approximated
point-by-point over the XML window) — except `knock`, asserted from the
injection spec (MAPO is not in truth.json). Notes:
  - `misfire from IMEP` never trips on healthy firing: the check is ONE-SIDED
    low-side (IMEP <= Expected - threshold, finding F3d) and Expected IMEP is
    the unwired 0 as-built — the check is INERT (a protection gap, not a
    false-tripper) until Expected IMEP is wired from the commanded IMEP-REF.
  - truth metrics are noise-free; the floors in the std/dev thresholds provide
    the on-target margin.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

GEOMETRY = ["--bore", "0.112", "--stroke", "0.149", "--conrod", "0.217",
            "--cr", "12.8", "--pin-offset=-0.00099"]  # picture15 as-built
TEMPLATE_XML = Path("parameter-files/CylWarningLevels.xml")
KNOCK_AMP = 2.5  # bar, injected knock amplitude

# flag name (as in Pcyl_Diag/CombCluster2Array) -> XML field base
FLAG_FIELD = {
    "maximum pressure": "MaxPCylMax",
    "cyclic variability": "MaxIMEPstd",
    "misfire cyl-to-cyl": "MaxDevFromAvg",
    "misfire self reg": "MaxDevFromSelfAvg",
    "misfire from IMEP": "MaxDevFromExpectedIMEP",
    "knock": "MAPOmax",
    "late combustion": "CA50max",
}
UNITS = {"MaxPCylMax": "bar", "MaxIMEPstd": "bar", "MaxDevFromAvg": "bar",
         "MaxDevFromSelfAvg": "bar", "MaxDevFromExpectedIMEP": "bar",
         "MAPOmax": "bar/CAD", "CA50max": "CADATDC"}


@dataclass
class SetSpec:
    name: str
    extra: list[str]              # gen_cas_traces args beyond the common ones
    purpose: str
    primary: str | None           # flag that MUST reach ERROR (None = control)
    knock_cyls: dict[int, float] = field(default_factory=dict)  # cyl -> amp


SETS = [
    SetSpec("baseline_motored", ["--mode", "motored"],
            "clean control - NO trips expected (and CA50 must be finite, closing F3a)", None),
    SetSpec("baseline_fired", ["--mode", "fired", "--q-fired", "6000"],
            "clean firing - NO trips expected (misfire-from-IMEP is one-sided "
            "low-side vs Expected=0, i.e. INERT - finding F3d)", None),
    SetSpec("overpressure", ["--mode", "fired", "--q-fired", "12000"],
            "peak pressure beyond the drill error limit", "maximum pressure"),
    SetSpec("late_combustion",
            ["--mode", "fired", "--q-fired", "6000", "--soc", "15", "--burn-dur", "60"],
            "retarded burn - CA50 far beyond the armed limit", "late combustion"),
    SetSpec("knock",
            ["--mode", "fired", "--q-fired", "6000",
             f"--knock=2:8:{KNOCK_AMP}", f"--knock=5:14:{KNOCK_AMP}"],
            "knock oscillation on cyls 2 & 5", "knock", {2: KNOCK_AMP, 5: KNOCK_AMP}),
    SetSpec("misfire", ["--mode", "fired", "--q-fired", "6000", "--misfire", "3:10"],
            "cylinder 3 dead in cycle 10 - both misfire deviations", "misfire cyl-to-cyl"),
    SetSpec("variability", ["--mode", "fired", "--q-fired", "6000", "--q-jitter", "0.025"],
            "per-cycle q jitter - cyclic variability without a full misfire",
            "cyclic variability"),
]


# --- threshold derivation (drill profile, from baseline_fired truth) --------

def series(truth: dict, key: str) -> dict[int, list[float | None]]:
    """Per-cylinder metric series over cycles: {cyl: [v_cycle1, ...]} (None if absent)."""
    cycles = sorted(truth["cycles"], key=int)
    return {cyl: [truth["cycles"][c]["cylinders"][str(cyl)].get(key) for c in cycles]
            for cyl in range(1, 7)}


def drill_thresholds(fired_truth: dict) -> dict[str, tuple[float, float]]:
    """Field -> (warning, error), ALL armed, derived like tune_thresholds' fired
    mode from the clean baseline_fired truth (uncapped Pmax - hard-limit caveat)."""
    pmax = [v for vs in series(fired_truth, "pmax_bar").values() for v in vs if v is not None]
    ca50 = [v for vs in series(fired_truth, "ca50_atdc").values() for v in vs if v is not None]
    imn = [v for vs in series(fired_truth, "imep_n_bar").values() for v in vs if v is not None]
    peak, ca_max, imn_mean = max(pmax), max(ca50), st.mean(imn)
    return {
        "MaxPCylMax": (round(peak * 1.2, 1), round(peak * 1.3, 1)),
        "MaxIMEPstd": (0.2, 0.3),
        "MaxDevFromAvg": (0.5, 0.8),
        "MaxDevFromSelfAvg": (0.5, 0.8),
        "MaxDevFromExpectedIMEP": (round(imn_mean * 0.4, 2), round(imn_mean * 0.6, 2)),
        "MAPOmax": (round(KNOCK_AMP * 0.3, 2), round(KNOCK_AMP * 0.5, 2)),
        "CA50max": (round(ca_max + 5, 1), round(ca_max + 10, 1)),
    }


# --- expected-trip computation ----------------------------------------------

def _running(vals: list[float], window: int):
    """Yield (point-by-point mean, pstdev) over the trailing `window` incl. current."""
    for i in range(len(vals)):
        w = vals[max(0, i + 1 - window):i + 1]
        yield st.mean(w), (st.pstdev(w) if len(w) > 1 else 0.0)


def expected_trips(truth: dict, thr: dict[str, tuple[float, float]], window: int,
                   knock_cyls: dict[int, float], motored: bool) -> dict[str, str]:
    """Flag -> 'ERROR' | 'WARNING' | 'clean' | 'observe' at the drill thresholds.

    ERROR/WARNING = the highest level any cylinder crosses in any cycle.
    'observe' = not computable from truth (motored CA50 noise; non-injected MAPO)
    - record the bench observation, no pass/fail assertion.
    """
    out: dict[str, str] = {}

    def level(worst: float, f: str) -> str:
        w, e = thr[f]
        return "ERROR" if worst > e else ("WARNING" if worst > w else "clean")

    pmax = series(truth, "pmax_bar")
    out["maximum pressure"] = level(max(v for vs in pmax.values() for v in vs), "MaxPCylMax")

    imn, img = series(truth, "imep_n_bar"), series(truth, "imep_g_bar")
    # The three misfire deviations are ONE-SIDED low-side checks as-built
    # (F3d, confirmed from the Pcyl_Diag print + drill 2026-07-15):
    # trip iff IMEP <= reference - threshold, i.e. (reference - IMEP) > thr.
    # misfire from IMEP: reference = Expected IMEP = 0 (unwired as-built) ->
    # effectively INERT for healthy data (only IMEP < -thr could trip).
    out["misfire from IMEP"] = level(max(0.0 - v for vs in imn.values() for v in vs),
                                     "MaxDevFromExpectedIMEP")
    # cyl-to-cyl: (across-cylinder mean - IMEPg_i) per cycle, low side only
    ncyc = len(img[1])
    worst = max(st.mean(img[k][i] for k in range(1, 7)) - img[c][i]
                for i in range(ncyc) for c in range(1, 7))
    out["misfire cyl-to-cyl"] = level(worst, "MaxDevFromAvg")
    # self reg (low side) + cyclic variability: point-by-point over the window
    worst_dev = worst_std = 0.0
    for c in range(1, 7):
        for i, (mean, std) in enumerate(_running(imn[c], window)):
            worst_dev = max(worst_dev, mean - imn[c][i])
            worst_std = max(worst_std, std)
    out["misfire self reg"] = level(worst_dev, "MaxDevFromSelfAvg")
    out["cyclic variability"] = level(worst_std, "MaxIMEPstd")

    # late combustion: fired CA50 from truth; motored CA50 is analytics noise
    ca50 = [v for vs in series(truth, "ca50_atdc").values() for v in vs if v is not None]
    out["late combustion"] = "observe" if (motored or not ca50) else level(max(ca50), "CA50max")

    # knock: MAPO not in truth - asserted from the injection spec
    if knock_cyls:
        out["knock"] = level(max(knock_cyls.values()), "MAPOmax")
    else:
        out["knock"] = "observe" if not motored else "clean"  # clean traces ~ no HF content
    return out


# --- drill XML ---------------------------------------------------------------

def render_drill_xml(template_text: str, thr: dict[str, tuple[float, float]],
                     window: int) -> str:
    """Substitute <Val>s in the LVData template (structure untouched)."""
    updates = {"samples for running IMEP std": str(window)}
    for f, (w, e) in thr.items():
        u = UNITS[f]
        updates[f"{f}Warning [{u}]"] = f"{w:.14f}"
        updates[f"{f}Error [{u}]"] = f"{e:.14f}"
    text = template_text
    for name, val in updates.items():
        pat = re.compile(r"(<Name>" + re.escape(name) + r"</Name>\s*<Val>)[^<]*(</Val>)")
        text, n = pat.subn(lambda m: m.group(1) + val + m.group(2), text)
        if n != 1:
            raise SystemExit(f"drill XML: element {name!r} matched {n} times (expected 1)")
    return text


# --- outputs -----------------------------------------------------------------

def write_manifest(out: Path, results: list[dict], thr: dict, window: int, cycles: int) -> None:
    md = [
        "# SIL-1 warning/error false-trip matrix",
        "",
        f"Generated by `tools/gen_warning_matrix.py` ({cycles} cycles/set, window {window}).",
        "Injection procedure: `docs/sil1-scope-of-work.md` (CAS_loop sim-pressure branch).",
        "",
        "## Drill profile (ALL fields armed — `CylWarningLevels.drill.xml`)",
        "",
        "| field | Warning | Error | unit |", "|---|---|---|---|",
        *[f"| {f} | {w:g} | {e:g} | {UNITS[f]} |" for f, (w, e) in thr.items()],
        "",
        "**Swap:** copy `CylWarningLevels.drill.xml` → cRIO "
        "`/home/lvuser/natinst/bin/CylWarningLevels.xml`, reload (restart the app "
        "or UI load), verify one value on the UI CYLINDER (Errors) Retrieve. "
        "**RESTORE the motoring XML after the drill** — the drill profile's "
        "`MaxPCylMax` is uncapped (×1.3, no hardware ceiling) and `MAPOmax`/"
        "`CA50max` are drill-sized, NOT run values.",
        "",
        "## Per-set drill",
        "",
        "For each set, in this order: copy **only the raw `cycle_NNNN.csv`** → "
        "`/home/lvuser/sim/<set>/` — NEVER the `*_phased.csv` (a `cycle_*.csv` "
        "List-Folder pattern matches both, interleaves them, and poisons every "
        "metric; the CAS sim branch must use pattern `cycle_????.csv`); "
        "point `Sim folder` at it (`SIM pressure?`=TRUE, `SimEnable`=TRUE); run ≥ "
        f"{window + 5} cycles; **CLEAR WARNINGS once after the first cycles settle** "
        "(the first acquired cycle is zero-padded garbage — F3); observe "
        "`WarningsAndErrors` + `9049_Global_CylPressError`; compare against the "
        "table; CLEAR WARNINGS → confirm the latch releases; next set.",
        "",
        "Legend: **ERROR** = flag latches + CylPressError TRUE · **WARNING** = "
        "advisory only, no latch · clean = must not trip · observe = not "
        "truth-computable (record what you see).",
        "",
    ]
    for r in results:
        md += [f"### {r['name']}", "",
               f"*{r['purpose']}*  ", f"recipe: `{r['recipe']}`", "",
               "| flag | expected |", "|---|---|",
               *[f"| {fl} | {lv} |" for fl, lv in r["expected"].items()], ""]
        if r["primary"]:
            md += [f"**Pass:** `{r['primary']}` reaches ERROR and latches; "
                   "CLEAR WARNINGS releases it.", ""]
        else:
            md += ["**Pass:** the six flags OTHER than late-combustion stay clean and "
                   "steady; CA50 baseline reads finite. Known as-built exception "
                   "(F3/F3a) until the Step-6c state gate is built: on motored data "
                   "the CA50 detector is noise-driven (finite ~+45 clamps + "
                   "intermittent non-finite that beats even 1e6) → late-combustion "
                   "latches randomly. Fix = gate late-combustion on SYSTEMSTATE ≥ 2 "
                   "in CombCluster2Array (sil1-scope-of-work.md Step 6c); after it, "
                   "motored late-combustion must stay green even armed. For spark/DI "
                   "GATE tests stream a fired set (stable CA50) so CylPressError "
                   "stays FALSE. NOTE: the Step-6c state gate (built 2026-07-14) "
                   "gates BOTH `late combustion` AND `misfire from IMEP` on "
                   "SYSTEMSTATE ≥ 2 — those two flags only trip with state held ≥ 2 "
                   "(request IDLING or ManualState=2); at STAND_BY expect them "
                   "clean in EVERY set, including the fired ones.", ""]
    (out / "manifest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(
        {"window": window, "cycles_per_set": cycles,
         "drill_thresholds": {f: {"warning": w, "error": e} for f, (w, e) in thr.items()},
         "sets": results}, indent=2) + "\n", encoding="utf-8")


def write_xlsx(path: Path, results: list[dict], thr: dict) -> None:
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        raise SystemExit(
            "--xlsx needs openpyxl: pip install openpyxl   (or pip install -e \".[dev]\")\n"
            "The trace sets, drill XML and manifest were still written — only the "
            "record sheet was skipped.")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "WarningMatrix"
    hdr = ["Set", "Flag", "Expected (drill XML)", "Observed W", "Observed E",
           "Latch cleared?", "Notes"]
    ws.append(hdr)
    for c in range(1, len(hdr) + 1):
        ws.cell(1, c).font = Font(bold=True)
    for r in results:
        for fl, lv in r["expected"].items():
            ws.append([r["name"], fl, lv, "", "", "", ""])
    ws.append([])
    ws.append(["Drill thresholds:", *(f"{f} {w:g}/{e:g} {UNITS[f]}"
                                      for f, (w, e) in thr.items())])
    for col, w in zip("ABCDEFG", (18, 20, 20, 12, 12, 14, 40)):
        ws.column_dimensions[col].width = w
    wb.save(path)


# --- main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the SIL-1 warning false-trip matrix")
    ap.add_argument("out_dir", nargs="?", default="trace-sets/warning_matrix")
    ap.add_argument("--cycles", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rpm", type=float, default=900.0)
    ap.add_argument("--xlsx", type=Path, default=None,
                    help="also write the bench record sheet (.xlsx)")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    common = ["--cycles", str(args.cycles), "--rpm", str(args.rpm),
              "--seed", str(args.seed), *GEOMETRY]
    truths: dict[str, dict] = {}
    for s in SETS:
        subprocess.run([sys.executable, "tools/gen_cas_traces.py", str(out / s.name),
                        *common, *s.extra], check=True, capture_output=True)
        truths[s.name] = json.loads((out / s.name / "truth.json").read_text())
        print(f"  set {s.name}: {args.cycles} cycles")

    thr = drill_thresholds(truths["baseline_fired"])
    template = TEMPLATE_XML.read_text(encoding="utf-8")
    window = int(re.search(r"<Name>samples for running IMEP std</Name>\s*<Val>(\d+)</Val>",
                           template).group(1))
    (out / "CylWarningLevels.drill.xml").write_text(
        render_drill_xml(template, thr, window), encoding="utf-8")

    results = []
    for s in SETS:
        exp = expected_trips(truths[s.name], thr, window, s.knock_cyls,
                             motored=(s.name == "baseline_motored"))
        if s.primary and exp[s.primary] != "ERROR":
            print(f"  !! {s.name}: primary flag {s.primary!r} computes {exp[s.primary]}, "
                  "not ERROR — resize the recipe", file=sys.stderr)
        results.append({"name": s.name, "purpose": s.purpose, "primary": s.primary,
                        "recipe": " ".join(["gen_cas_traces.py", s.name, *common, *s.extra]),
                        "expected": exp})

    write_manifest(out, results, thr, window, args.cycles)
    if args.xlsx:
        write_xlsx(args.xlsx, results, thr)
        print(f"record sheet: {args.xlsx}")
    print(f"wrote {len(SETS)} sets + CylWarningLevels.drill.xml + manifest.md/json to {out}/")
    print("drill profile is UNCAPPED (no --pmax-hard-limit) and drill-sized — "
          "restore the motoring XML after the drill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
