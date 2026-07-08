"""MONARCH operator CLI (Phase C1) — a deliberately small surface over
MonarchCommander + SequenceExecutor.

    python examples/monarch_operate.py [--host H] [--port P]

The engine ticks at 1 Hz on a background thread; this REPL mutates the
commander's intent. Nothing here bypasses the safety posture: commands only
flow while the gateway's CommandSource is PYTHON, telemetry staleness pauses
the stream (engine + commander both enforce it), and e-stop can be SET but
never CLEARED from here (operator/HMI only).

Commands:
  status                          one-line plant + link + sequence status
  mode safe|standby|motoring|idling|firing
  set <path> <value>              e.g. set speed_ref 900
                                  set pid_control_references.tcoolant.ec_tt_001_ref 60
  force idling|motoring on|off
  estop                           set emergency stop (CANNOT be cleared here)
  seq list | run <name> | status | abort | ok
  quit

Every operator action + outcome is appended to operate.jsonl.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time

from supervisory import Recorder, TcpPlantLink
from supervisory.engine import Supervisor
from supervisory.monarch import MonarchTelemetry, monarch_parser
from supervisory.monarch.commander import MonarchCommander
from supervisory.monarch.control_settings import SystemState
from supervisory.monarch.operator_mirror import OperatorRequestMirror
from supervisory.monarch.sequences import DRAFT_SEQUENCES, SequenceExecutor
from supervisory.sequencing import Status

MODES = {"safe": SystemState.SAFE, "standby": SystemState.STAND_BY,
         "motoring": SystemState.MOTORING, "idling": SystemState.IDLING,
         "firing": SystemState.FIRING}

log = logging.getLogger("operate")


class OpsLog:
    def __init__(self, path="operate.jsonl"):
        self._fh = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, action: str, outcome: str) -> None:
        self._fh.write(json.dumps({"t": time.time(), "action": action,
                                   "outcome": outcome}) + "\n")


class Session:
    def __init__(self, host: str, port: int, mirror: bool = True):
        self.link = TcpPlantLink(host=host, port=port, parser=monarch_parser)
        self.commander = MonarchCommander()
        self.executor = SequenceExecutor(self.commander)
        # ICD §7.7: the HMI stays the operator's input surface — panel
        # requests (PC_OperatorRequests) mirror into Python's intent. The
        # mirror is ALWAYS in the stack; --no-mirror only reduces it to
        # safety-only (e-stop set, force overrides) — the floor no config
        # may go below (drill B4-8 finding, 2026-07-08).
        self.mirror = OperatorRequestMirror(self.commander, self.executor,
                                            safety_only=not mirror)
        machines = [self.mirror, self.executor, self.commander]
        self.recorder = Recorder("operate_traffic.jsonl")
        self.sup = Supervisor(self.link, machines,
                              recorder=self.recorder)
        self.ops = OpsLog()
        self.last_view = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        next_tick = time.monotonic()
        while not self._stop.is_set():
            self.last_view = self.sup.tick(time.monotonic())
            next_tick += 1.0
            delay = next_tick - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                next_tick = time.monotonic()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=3)
        self.link.close()
        self.recorder.close()

    # ---- guarded actions ---------------------------------------------------
    def guard(self) -> str | None:
        view = self.last_view
        if view is None or view.stale:
            return "REFUSED: telemetry stale/absent"
        if not self.commander.commanding:
            tm = view.telemetry
            src = tm.command_source if isinstance(tm, MonarchTelemetry) else "?"
            return f"REFUSED: not commanding (command_source={src}); flip source on the HMI"
        return None

    def status_line(self) -> str:
        view = self.last_view
        if view is None:
            return "no ticks yet"
        tm = view.telemetry
        parts = [f"connected={view.connected}", f"stale={view.stale}",
                 f"commanding={self.commander.commanding}"]
        if isinstance(tm, MonarchTelemetry):
            parts += [f"state={int(tm.system_state)}",
                      f"source={tm.command_source}",
                      f"warn_lim={tm.warnings_limit}"]
            if tm.plant:
                parts.append("plant={" + ", ".join(
                    f"{k}={v}" for k, v in sorted(tm.plant.items())) + "}")
        if self.commander.last_nack:
            parts.append(f"last_nack={self.commander.last_nack}")
        r = self.executor.runner
        if r is not None:
            step = getattr(r.active_step, "label", None)
            parts.append(f"seq={r.sequence.name}:{r.status.value}"
                         + (f"@{step}" if step else "")
                         + (f" ({r.abort_reason})" if r.abort_reason else ""))
        return "  ".join(parts)


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def set_path(session: Session, path: str, raw: str) -> str:
    value = parse_value(raw)

    def change(settings):
        obj = settings
        parts = path.split(".")
        for part in parts[:-1]:
            obj = getattr(obj, part)
        if not hasattr(obj, parts[-1]):
            raise AttributeError(path)
        setattr(obj, parts[-1], value)

    session.commander.modify(change)
    return f"set {path} = {value!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description="MONARCH operator CLI (Phase C1)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--no-mirror", action="store_true",
                    help="reduce the ICD 7.7 mirror to SAFETY-ONLY (panel "
                         "e-stop and force overrides still flow — always); "
                         "mode/set from this CLI then own the rest of the "
                         "intent")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    s = Session(args.host, args.port, mirror=not args.no_mirror)
    print("MONARCH operator CLI — 'status' for state, 'quit' to exit.")
    print("NOTE: commands take effect only while the HMI CommandSource is PYTHON.")
    if s.mirror.safety_only:
        print("MIRROR: SAFETY-ONLY — panel e-stop and force overrides flow "
              "through Python; CLI mode/set own the rest of the intent.")
    else:
        print("MIRROR ON: HMI panel requests flow through Python (ICD 7.7). "
              "CLI mode/set are overridden by the panel within a tick unless "
              "a sequence is running; --no-mirror reduces to safety-only.")
    try:
        while True:
            try:
                line = input("monarch> ").strip()
            except EOFError:
                break
            if not line:
                continue
            words = line.split()
            cmd, rest = words[0].lower(), words[1:]
            outcome = "?"
            try:
                if cmd == "quit":
                    break
                elif cmd == "status":
                    outcome = s.status_line()
                elif cmd == "mode" and rest and rest[0] in MODES:
                    outcome = s.guard() or (
                        s.commander.request_mode(MODES[rest[0]])
                        or f"requested_mode={rest[0]}")
                elif cmd == "set" and len(rest) == 2:
                    outcome = s.guard() or set_path(s, rest[0], rest[1])
                elif cmd == "force" and len(rest) == 2 and rest[0] in ("idling", "motoring"):
                    flag = rest[1] == "on"
                    field = f"force_{rest[0]}"
                    outcome = s.guard() or (
                        s.commander.modify(lambda cs: setattr(cs, field, flag))
                        or f"{field}={flag}")
                elif cmd == "estop":
                    outcome = s.guard() or (
                        s.commander.modify(lambda cs: setattr(cs, "emergency_stop", True))
                        or "EMERGENCY STOP SET (clear from the HMI only)")
                elif cmd == "seq" and rest:
                    sub = rest[0]
                    if sub == "list":
                        outcome = ", ".join(sorted(DRAFT_SEQUENCES))
                    elif sub == "run" and len(rest) == 2 and rest[1] in DRAFT_SEQUENCES:
                        outcome = s.guard()
                        if outcome is None:
                            s.executor.load(DRAFT_SEQUENCES[rest[1]]())
                            s.executor.start()
                            outcome = f"sequence {rest[1]} started"
                    elif sub == "status":
                        r = s.executor.runner
                        outcome = ("no sequence" if r is None else
                                   f"{r.sequence.name}: {r.status.value} "
                                   f"step={getattr(r.active_step, 'label', None)} "
                                   f"progress={r.progress}"
                                   + (f" abort={r.abort_reason}" if r.abort_reason else ""))
                    elif sub == "abort":
                        s.executor.abort("operator")
                        outcome = "abort requested"
                    elif sub == "ok":
                        s.executor.confirm_hold()
                        outcome = "hold confirmed"
                    else:
                        outcome = "usage: seq list|run <name>|status|abort|ok"
                else:
                    outcome = ("commands: status | mode <m> | set <path> <v> | "
                               "force idling|motoring on|off | estop | seq … | quit")
            except Exception as e:  # noqa: BLE001 — operator surface, report and continue
                outcome = f"ERROR: {type(e).__name__}: {e}"
            print(outcome)
            s.ops.write(line, str(outcome))
    finally:
        s.close()
        print("closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
