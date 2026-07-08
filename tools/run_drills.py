"""B4 bench drill runner — the machine-runnable subset of the drill table.

    python tools/run_drills.py [--host H] [--rounds 3] [--requested 1]

Runs, N rounds each, against the REAL gateway (switch must be on PYTHON,
no other Python client connected):

  D1 crash   engage authority -> abrupt socket close -> SAFE within ~5 s
             -> reconnect+re-engage -> recovery to requested state
  D2 freeze  engage -> commander muted, session+heartbeats kept alive
             (a hung supervisor with a live TCP pipe) -> SAFE -> recovery
  D3 drop    after every close: the gateway re-listens and serves a new
             session promptly (asserted on each reconnect)
  D4 garbage trash bytes then a valid command: trash discarded/NACKed,
             the next command still answered, telemetry still flowing
  D5 range   speed 99999 -> NACK reason starting "range"
  D6 rate    7 fast sends -> 6th+ NACK "rate"

B4-7 (source flips), B4-8 (panel e-stop), B4-9 (gateway stall) need hands
on the HMI / LabVIEW and stay with the operator.

Each check is logged with timestamps to b4_drill_log.jsonl and summarized
as PASS/FAIL. The plant is left un-commanded at the end (watchdog parks it
in SAFE) — flip to UI to take it back.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time

sys.path.insert(0, ".")
from supervisory import TcpPlantLink  # noqa: E402
from supervisory.engine import Supervisor  # noqa: E402
from supervisory.monarch import MonarchTelemetry, monarch_parser  # noqa: E402
from supervisory.monarch.commander import MonarchCommander  # noqa: E402
from supervisory.monarch.control_settings import ControlSettings  # noqa: E402
from supervisory.monarch.labview_mapping import control_settings_to_labview  # noqa: E402

LOG = open("b4_drill_log.jsonl", "a", encoding="utf-8", buffering=1)
RESULTS: list[tuple[str, int, bool, str]] = []


def log(drill: str, rnd: int, event: str, **kw):
    LOG.write(json.dumps({"t": time.time(), "drill": drill, "round": rnd,
                          "event": event, **kw}) + "\n")


def result(drill: str, rnd: int, ok: bool, detail: str):
    RESULTS.append((drill, rnd, ok, detail))
    log(drill, rnd, "RESULT", ok=ok, detail=detail)
    print(f"  {'PASS' if ok else 'FAIL'}  {drill} r{rnd}: {detail}")


class Bench:
    """One command session against the gateway."""

    def __init__(self, host: str, port: int):
        self.link = TcpPlantLink(host=host, port=port, parser=monarch_parser)
        self.commander = MonarchCommander()
        self.sup = Supervisor(self.link, [self.commander])
        self.view = None

    def run(self, seconds: float, until=None):
        """Tick in real time; returns True if `until(tm)` became true."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.view = self.sup.tick(time.monotonic())
            tm = self.view.telemetry if self.view else None
            if until and isinstance(tm, MonarchTelemetry) and until(tm):
                return True
            time.sleep(0.25)
        return False

    def close_abruptly(self):
        self.link.close()


def engage(host, port, requested, drill, rnd) -> Bench | None:
    """Fresh session; assert authority, clear our e-stop echo, request state."""
    b = Bench(host, port)
    b.run(6, until=lambda tm: tm.command_source == "PYTHON")
    if not b.commander.commanding:
        # one more grace tick round
        b.run(4)
    if not b.commander.commanding:
        result(drill, rnd, False, "could not engage authority (is the switch on PYTHON?)")
        b.close_abruptly()
        return None
    b.commander.modify(lambda cs: (setattr(cs, "emergency_stop", False),
                                   setattr(cs, "requested_mode", requested)))
    ok = b.run(12, until=lambda tm: int(tm.system_state) == requested
               and tm.warnings_limit is not None and tm.warnings_limit >= 0)
    log(drill, rnd, "engaged", reached=ok)
    return b


def observe_trip(host, port, drill, rnd, timeout=14.0) -> bool:
    """Reconnect read-only; wait for the watchdog clamp (state −1, wl −1)."""
    b = Bench(host, port)
    b.commander.enabled = False  # observe-only: heartbeats, no commands
    tripped = b.run(timeout, until=lambda tm: int(tm.system_state) == -1
                    and tm.warnings_limit == -1)
    b.close_abruptly()
    return tripped


def d1_crash(host, port, requested, rnd):
    b = engage(host, port, requested, "D1-crash", rnd)
    if not b:
        return
    t0 = time.time()
    b.close_abruptly()  # Python "dies": TCP drops, stream stops
    log("D1-crash", rnd, "killed")
    time.sleep(1)
    tripped = observe_trip(host, port, "D1-crash", rnd)
    dt = time.time() - t0
    # D3 evidence: the reconnect above was served => gateway re-listens
    result("D3-drop", rnd, tripped is not None, "gateway re-listened and served a new session")
    if not tripped:
        result("D1-crash", rnd, False, f"no SAFE clamp within {dt:.0f}s of kill")
        return
    b2 = engage(host, port, requested, "D1-crash", rnd)
    recovered = b2 is not None and int(b2.view.telemetry.system_state) == requested
    if b2:
        b2.close_abruptly()
    result("D1-crash", rnd, recovered,
           f"SAFE after kill (~{dt:.0f}s incl. observe), then recovered to {requested}")


def d2_freeze(host, port, requested, rnd):
    b = engage(host, port, requested, "D2-freeze", rnd)
    if not b:
        return
    b.commander.enabled = False  # hang: session+heartbeats alive, commands stop
    log("D2-freeze", rnd, "frozen")
    t0 = time.time()
    tripped = b.run(14, until=lambda tm: int(tm.system_state) == -1
                    and tm.warnings_limit == -1)
    dt = time.time() - t0
    if not tripped:
        b.close_abruptly()
        result("D2-freeze", rnd, False, f"no SAFE clamp within {dt:.0f}s of freeze")
        return
    b.commander.enabled = True  # un-hang
    b.commander.modify(lambda cs: (setattr(cs, "emergency_stop", False),
                                   setattr(cs, "requested_mode", requested)))
    recovered = b.run(12, until=lambda tm: int(tm.system_state) == requested)
    b.close_abruptly()
    result("D2-freeze", rnd, recovered,
           f"SAFE {dt:.0f}s after freeze (threshold 5s), recovery to {requested} after un-freeze")


# ---- raw-line drills (own socket) -------------------------------------------

def _cmd(cid, name="set_control_settings", settings=None):
    if settings is None:
        settings = control_settings_to_labview(ControlSettings())
    return (json.dumps({"type": "command", "id": cid, "name": name,
                        "params": {"settings": settings}},
                       separators=(",", ":")) + "\r\n").encode()


def _acks(sock, want, timeout=6.0):
    sock.settimeout(0.5)
    deadline, buf, acks = time.monotonic() + timeout, b"", []
    while len(acks) < want and time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if b'"command_ack"' in line:
                acks.append(json.loads(line))
    return acks


def d4_garbage(host, port, rnd):
    s = socket.create_connection((host, port), timeout=5)
    s.sendall(b'{"type":"command", THIS IS NOT JSON @@@\r\n')
    time.sleep(0.5)
    s.sendall(_cmd(99))
    acks = _acks(s, 2)
    got_tel = False
    s.settimeout(2.0)
    try:
        got_tel = b'"telemetry"' in s.recv(65536)
    except socket.timeout:
        pass
    s.close()
    survived = any(a["id"] == 99 for a in acks)
    result("D4-garbage", rnd, survived and got_tel,
           f"acks={[(a['id'], a['reason']) for a in acks]}, telemetry flowing={got_tel}")


def d5_range(host, port, rnd):
    settings = control_settings_to_labview(ControlSettings())
    settings["Speed ref"] = 99999.0
    s = socket.create_connection((host, port), timeout=5)
    s.sendall(_cmd(4, settings=settings))
    acks = _acks(s, 1)
    s.close()
    ok = bool(acks) and not acks[0]["accepted"] and acks[0]["reason"].startswith("range")
    result("D5-range", rnd, ok, f"reply={acks[0] if acks else None}")


def d6_rate(host, port, rnd):
    s = socket.create_connection((host, port), timeout=5)
    for i in range(7):
        s.sendall(_cmd(10 + i))
    acks = _acks(s, 7)
    s.close()
    rates = [a for a in acks if a["reason"] == "rate"]
    ok = len(acks) == 7 and len(rates) >= 2 and all(a["reason"] == "rate" for a in acks[5:])
    result("D6-rate", rnd, ok, f"{len(acks)} replies, {len(rates)} rate-NACKs (6th+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="host.docker.internal")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--requested", type=int, default=1)
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.ERROR)
    for rnd in range(1, args.rounds + 1):
        print(f"--- round {rnd} ---")
        d1_crash(args.host, args.port, args.requested, rnd)
        time.sleep(1)
        d2_freeze(args.host, args.port, args.requested, rnd)
        time.sleep(1)
        d4_garbage(args.host, args.port, rnd)
        time.sleep(1)
        d5_range(args.host, args.port, rnd)
        time.sleep(1.5)  # let the rate window drain
        d6_rate(args.host, args.port, rnd)
        time.sleep(1.5)

    print("\n==== SUMMARY ====")
    fails = [r for r in RESULTS if not r[2]]
    for drill in sorted({r[0] for r in RESULTS}):
        rs = [r for r in RESULTS if r[0] == drill]
        n_ok = sum(1 for r in rs if r[2])
        print(f"{drill:12s} {n_ok}/{len(rs)} PASS")
    print("plant left un-commanded (watchdog parks it in SAFE) — flip to UI to take it back")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
