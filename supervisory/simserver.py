"""Runnable fake LabVIEW gateway: SimPlant behind a real TCP server.

Lets you exercise the full stack — TcpPlantLink, framing, reconnects, the
heartbeat watchdog — before the LabVIEW side exists:

    python -m supervisory.simserver                # 127.0.0.1:5020, 1 Hz
    python -m supervisory.simserver --speedup 10   # plant time runs 10x

Unlike the real gateway the plant only advances while a client is connected,
which is fine for its purpose (driving the Python side).
"""

from __future__ import annotations

import argparse
import logging
import socket
import time

from pydantic import ValidationError

from .messages import Command, Heartbeat, dump, parse
from .sim import SimPlant

log = logging.getLogger("simserver")


def serve(host: str = "127.0.0.1", port: int = 5020, period_s: float = 1.0, speedup: float = 1.0) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(1)
        log.info("fake gateway listening on %s:%d (period %.2fs, speedup %gx)", host, port, period_s, speedup)
        while True:
            conn, addr = listener.accept()
            log.info("supervisor connected from %s:%d", *addr)
            plant = SimPlant(start_time=time.time())
            if speedup != 1.0:
                # keep the watchdog's wall-clock semantics under time compression
                plant.HEARTBEAT_TIMEOUT_S = SimPlant.HEARTBEAT_TIMEOUT_S * speedup
            with conn:
                try:
                    serve_client(conn, plant, period_s, speedup)
                except (ConnectionError, OSError):
                    pass
            log.info("supervisor disconnected")


def serve_client(conn: socket.socket, plant: SimPlant, period_s: float, speedup: float = 1.0) -> None:
    """Session loop for one connection: telemetry out every period_s, commands
    and heartbeats handled as they arrive. Mirrors the gateway loop structure
    suggested in docs/labview-notes.md."""
    buf = b""
    next_frame = time.monotonic()
    while True:
        remaining = next_frame - time.monotonic()
        if remaining <= 0:
            frame = plant.tick(period_s * speedup)
            _send(conn, frame)
            next_frame += period_s
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
                msg = parse(raw)
            except ValidationError:
                log.warning("discarding malformed line: %.200s", raw)
                continue
            if isinstance(msg, Command):
                ack = plant.handle_command(msg)
                log.info(
                    "command %d %s -> %s",
                    msg.id,
                    msg.name,
                    "ACK" if ack.accepted else f"NACK ({ack.reason})",
                )
                _send(conn, ack)
            elif isinstance(msg, Heartbeat):
                plant.heartbeat()
            else:
                log.warning("unexpected %s message from supervisor, discarded", msg.type)


def _send(conn: socket.socket, msg) -> None:
    conn.sendall((dump(msg) + "\r\n").encode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Fake LabVIEW gateway (SimPlant over TCP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--period", type=float, default=1.0, help="telemetry period, seconds")
    ap.add_argument("--speedup", type=float, default=1.0, help="plant time compression factor")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serve(args.host, args.port, args.period, args.speedup)


if __name__ == "__main__":
    main()
