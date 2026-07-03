"""Fake MONARCH gateway: streams real-shaped telemetry envelopes over TCP.

Lets the Stage-1 read-only observer (examples/monarch_listen.py) be exercised
end to end before the LabVIEW gateway sends real telemetry:

    python -m supervisory.monarch.simserver_monarch          # 127.0.0.1:5020, 1 Hz

It sends {"type":"telemetry","seq":N,"ts":T,"system_state":S,"settings":{...}}
where `settings` is a LabVIEW-style Flatten To JSON of a ControlSettings value
(nested "PID control references", real field labels). It walks the system state
STAND_BY -> MOTORING -> IDLING -> FIRING and nudges a couple of fields so the
recording isn't static, and acks any command it receives.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import time

from pydantic import ValidationError

from ..messages import Command, CommandAck, Heartbeat, dump
from ..messages import parse as parse_generic
from .control_settings import ControlSettings, SystemState
from .labview_mapping import control_settings_to_labview

log = logging.getLogger("monarch-sim")

_STATE_CYCLE = [SystemState.STAND_BY, SystemState.MOTORING, SystemState.IDLING, SystemState.FIRING]


def _frame(seq: int, state: SystemState) -> dict:
    cs = ControlSettings(
        requested_mode=state,
        speed_ref=900.0 + 100.0 * (seq % 5),
        ign_enable=state in (SystemState.IDLING, SystemState.FIRING),
        spark_advance_cadbtdc=float(20 + (seq % 10)),
    )
    cs.pid_control_references.ng.mode = 6 if state == SystemState.FIRING else 0
    return {
        "type": "telemetry",
        "seq": seq,
        "ts": time.time(),
        "system_state": int(state),
        "settings": control_settings_to_labview(cs),
    }


def serve_client(conn: socket.socket, period_s: float, speedup: float) -> None:
    buf = b""
    seq = 0
    next_frame = time.monotonic()
    while True:
        remaining = next_frame - time.monotonic()
        if remaining <= 0:
            seq += 1
            state = _STATE_CYCLE[(seq // 5) % len(_STATE_CYCLE)]
            conn.sendall((json.dumps(_frame(seq, state)) + "\r\n").encode("utf-8"))
            next_frame += period_s / speedup
            continue
        conn.settimeout(remaining)
        try:
            data = conn.recv(4096)
        except TimeoutError:
            continue
        if not data:
            raise ConnectionError("client closed")
        buf += data
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = parse_generic(raw)
            except ValidationError:
                continue
            if isinstance(msg, Command):
                ack = CommandAck(id=msg.id, accepted=True, reason="")
                log.info("command %d %s -> ACK", msg.id, msg.name)
                conn.sendall((dump(ack) + "\r\n").encode("utf-8"))
            elif isinstance(msg, Heartbeat):
                pass


def serve(host: str = "127.0.0.1", port: int = 5020, period_s: float = 1.0, speedup: float = 1.0) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(1)
        log.info("MONARCH sim gateway on %s:%d (period %.2fs, speedup %gx)", host, port, period_s, speedup)
        while True:
            conn, addr = listener.accept()
            log.info("observer connected from %s:%d", *addr)
            with conn:
                try:
                    serve_client(conn, period_s, speedup)
                except (ConnectionError, OSError):
                    pass
            log.info("observer disconnected")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fake MONARCH gateway (telemetry envelopes over TCP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--speedup", type=float, default=1.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serve(args.host, args.port, args.period, args.speedup)


if __name__ == "__main__":
    main()
