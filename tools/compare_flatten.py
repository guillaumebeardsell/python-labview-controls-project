"""Diff a LabVIEW `Flatten To JSON` capture of APC_ControlSettings against the
Python contract, and print an actionable report.

    python tools/compare_flatten.py path/to/control_settings_flatten.json

Exit code is 0 when the structures agree (ignoring value-level differences),
1 when there are mapping/type/length disagreements to resolve. Boolean values
and array lengths from the capture are always printed to help settle polarity
and array sizes. See docs/monarch-flatten-diff.md.
"""

import argparse
import json
import sys

from supervisory.monarch.labview_mapping import compare_flatten


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff LabVIEW ControlSettings JSON vs the Python contract")
    ap.add_argument("json_file", help="file containing the LabVIEW Flatten To JSON output")
    args = ap.parse_args()

    with open(args.json_file, encoding="utf-8-sig") as fh:
        lv = json.load(fh)

    rep = compare_flatten(lv)

    def section(title, rows, fmt):
        print(f"\n{title} ({len(rows)})")
        if not rows:
            print("  (none)")
        for r in rows:
            print("  " + fmt(r))

    print(f"=== ControlSettings contract diff: {args.json_file} ===")

    section(
        "LabVIEW fields not in the model (unmapped label or wrong label)",
        rep.unmapped,
        lambda r: f"{r[0]!r}  at {r[1]}  ({r[2]})",
    )
    section(
        "Model fields absent from the capture (missing, or LabVIEW label differs)",
        rep.missing,
        lambda r: r,
    )
    section(
        "Type mismatches (LabVIEW kind vs model kind)",
        rep.type_mismatch,
        lambda r: f"{r[0]!r} -> {r[1]}: LabVIEW={r[2]}, model={r[3]}",
    )
    section(
        "Array length mismatches",
        rep.array_mismatch,
        lambda r: f"{r[0]!r} -> {r[1]}: LabVIEW len={r[2]}, model len={r[3]}",
    )
    section(
        "Booleans observed (resolve polarity: note vents are meant 1=closed/0=open)",
        sorted(rep.booleans),
        lambda r: f"{r[0]!r} = {r[2]}  at {r[1]}",
    )
    section(
        "Arrays observed (confirm lengths)",
        sorted(rep.arrays),
        lambda r: f"{r[0]!r} len={r[2]}  at {r[1]}",
    )

    print("\n=== RESULT:", "AGREE (structure matches)" if rep.ok else "DISAGREE (see above)", "===")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
