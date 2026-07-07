"""Shadow-compare: replay/watch MONARCH telemetry and diff LabVIEW's decisions
against the Python StateMachine port (Phase A2 of docs/migration-plan.md).

    python tools/shadow_compare.py monarch.jsonl            # replay a recording
    python tools/shadow_compare.py --live [--host H] [--port P] [--seconds N]

Per frame: previous frame's system_state is CURRENT SYSTEM STATE; this frame's
settings (+ shadow extras when the gateway sends them) are the inputs; the port
predicts SYSTEM STATE (and Limited_ControlSettings when `limited_settings` is
in the telemetry) and diffs against LabVIEW's actuals.

A divergence is a FINDING, not automatically a Python bug — the LabVIEW logic
is unvalidated (pre-commissioning); disposition each one.

Coverage caveat: until the gateway pre-wires the shadow extras, warnings_limit
/ force_state / manual_state are unknown and assumed inactive (3 / False / 0).
LabVIEW transitions caused by those inputs will show as divergences flagged
"reduced-coverage".

Exit code 0 = full agreement, 1 = divergences, 2 = no comparable frames.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field

from supervisory.monarch import MonarchTelemetry
from supervisory.monarch.state_machine import StateDecisionInputs, decide

NO_LIMIT = 3


@dataclass
class Report:
    frames: int = 0
    compared: int = 0
    state_matches: int = 0
    state_divergences: list = field(default_factory=list)
    limited_compared: int = 0
    limited_matches: int = 0
    limited_divergences: list = field(default_factory=list)
    extras_seen: bool = False
    sessions: int = 0


# Heartbeat bits toggle between LabVIEW's two cluster reads (requested vs
# limited are flattened at slightly different instants), so they legitimately
# differ frame-to-frame; they are liveness bits, not limited fields.
IGNORED_LEAVES = {
    "pid_control_references.pc_hb",
    "pid_control_references.mtr_hb",
}


def _leaf_equal(a, b) -> bool:
    if a != b:
        # NaN != NaN by float semantics; treat both-NaN as equal
        if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
            return True
        return False
    return True


def leaf_diff(a: dict, b: dict, prefix=""):
    """Dotted-path diffs between two nested dicts (model_dump output)."""
    out = []
    for key in a:
        pa, pb = a[key], b.get(key)
        path = f"{prefix}{key}"
        if path in IGNORED_LEAVES:
            continue
        if isinstance(pa, dict) and isinstance(pb, dict):
            out += leaf_diff(pa, pb, path + ".")
        elif not _leaf_equal(pa, pb):
            out.append((path, pb, pa))  # (path, labview, python)
    return out


def compare_stream(frames, report: Report, max_divergence_prints=10):
    prev_state = None
    prev_seq = None
    for frame in frames:
        report.frames += 1
        if prev_seq is None or frame.seq <= prev_seq:
            report.sessions += 1
            prev_state = None  # new session: no CURRENT SYSTEM STATE yet
        prev_seq = frame.seq

        if frame.warnings_limit is not None:
            report.extras_seen = True

        if prev_state is not None:
            inputs = StateDecisionInputs(
                current_state=prev_state,
                settings=frame.settings,
                warnings_limit=(
                    frame.warnings_limit if frame.warnings_limit is not None else NO_LIMIT
                ),
                force_state=bool(frame.force_state) if frame.force_state is not None else False,
                manual_state=frame.manual_state if frame.manual_state is not None else 0,
            )
            decision = decide(inputs)
            report.compared += 1
            actual = int(frame.system_state)
            if decision.system_state == actual:
                report.state_matches += 1
            else:
                report.state_divergences.append({
                    "seq": frame.seq,
                    "current": prev_state,
                    "labview": actual,
                    "python": decision.system_state,
                    "limits": decision.limits,
                    "reduced_coverage": frame.warnings_limit is None,
                })

            if frame.limited_settings is not None:
                report.limited_compared += 1
                # Compare the limiter against LabVIEW's own decided state, to
                # isolate limiter fidelity from state fidelity.
                from supervisory.monarch.state_machine import limit_settings
                predicted = limit_settings(frame.settings, actual)
                diffs = leaf_diff(
                    predicted.model_dump(mode="json"),
                    frame.limited_settings.model_dump(mode="json"),
                )
                if not diffs:
                    report.limited_matches += 1
                else:
                    report.limited_divergences.append(
                        {"seq": frame.seq, "state": actual, "diffs": diffs[:8]}
                    )
        prev_state = int(frame.system_state)
    return report


def frames_from_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            msg = row.get("msg", row)
            if msg.get("type") == "telemetry" and "system_state" in msg:
                yield MonarchTelemetry.model_validate(msg)


def frames_live(host, port, seconds):
    from supervisory import TcpPlantLink
    from supervisory.monarch import monarch_parser

    link = TcpPlantLink(host=host, port=port, parser=monarch_parser)
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while deadline is None or time.monotonic() < deadline:
            for msg in link.poll():
                if isinstance(msg, MonarchTelemetry):
                    yield msg
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()


def print_report(rep: Report, source: str) -> int:
    print(f"=== shadow compare: {source} ===")
    print(f"frames: {rep.frames}  sessions: {rep.sessions}  compared: {rep.compared}")
    if not rep.extras_seen:
        print("NOTE: shadow extras absent (gateway not pre-wired) — warnings/"
              "force/manual assumed inactive; coverage reduced.")
    if rep.compared == 0:
        print("no comparable frames (need >=2 frames per session)")
        return 2

    pct = 100.0 * rep.state_matches / rep.compared
    print(f"\nSYSTEM STATE: {rep.state_matches}/{rep.compared} agree ({pct:.1f}%)")
    for d in rep.state_divergences[:10]:
        tag = " [reduced-coverage]" if d["reduced_coverage"] else ""
        print(f"  seq={d['seq']} current={d['current']} "
              f"labview={d['labview']} python={d['python']} "
              f"limits={d['limits']}{tag}")
    if len(rep.state_divergences) > 10:
        print(f"  ... and {len(rep.state_divergences) - 10} more")

    if rep.limited_compared:
        lpct = 100.0 * rep.limited_matches / rep.limited_compared
        print(f"Limited_ControlSettings: {rep.limited_matches}/{rep.limited_compared} "
              f"agree ({lpct:.1f}%)")
        for d in rep.limited_divergences[:5]:
            print(f"  seq={d['seq']} state={d['state']}:")
            for path, lv, py in d["diffs"]:
                print(f"    {path}: labview={lv} python={py}")
    else:
        print("Limited_ControlSettings: not in telemetry (pre-wire pending)")

    ok = not rep.state_divergences and not rep.limited_divergences
    print(f"\nRESULT: {'AGREE' if ok else 'DIVERGENCES — disposition each (LabVIEW is unvalidated)'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff LabVIEW state decisions vs the Python port")
    ap.add_argument("recording", nargs="?", help="monarch.jsonl to replay")
    ap.add_argument("--live", action="store_true", help="watch a live gateway instead")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--seconds", type=float, default=0, help="live watch duration (0 = until Ctrl-C)")
    args = ap.parse_args()

    if not args.live and not args.recording:
        ap.error("give a recording path or --live")

    rep = Report()
    if args.live:
        compare_stream(frames_live(args.host, args.port, args.seconds), rep)
        return print_report(rep, f"live {args.host}:{args.port}")
    compare_stream(frames_from_jsonl(args.recording), rep)
    return print_report(rep, args.recording)


if __name__ == "__main__":
    sys.exit(main())
