"""Connectivity smoke test between Python and a gateway.

Point it at the LabVIEW hello VI (build instructions in docs/hello-vi.md) or
at the fake gateway (python -m supervisory.simserver). It connects, prints
everything received, sends a heartbeat every second and a "ping" command
every 5 seconds, and prints a PASS/FAIL summary on Ctrl-C.

    python examples/hello_link.py                              # gateway on this machine
    python examples/hello_link.py --host host.docker.internal  # gateway on the Windows
                                                               # host, script in a container

Note: the simserver NACKs "ping" (unknown command) — that still counts as
PASS, because a NACK proves the full round trip: command out, validation,
ack back.
"""

import argparse
import logging
import time

from supervisory import Command, CommandAck, Heartbeat, TcpPlantLink, Telemetry


def main():
    ap = argparse.ArgumentParser(description="LabVIEW <-> Python connectivity smoke test")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("hello")

    link = TcpPlantLink(host=args.host, port=args.port)
    counts = {"telemetry": 0, "command_ack": 0, "other": 0}
    hb_seq = 0
    last_ping = None
    started = time.monotonic()
    try:
        while True:
            for msg in link.poll():
                if isinstance(msg, Telemetry):
                    counts["telemetry"] += 1
                    log.info(
                        "telemetry seq=%d mode=%s channels=%s flags=%s",
                        msg.seq, msg.mode, msg.channels, msg.flags,
                    )
                elif isinstance(msg, CommandAck):
                    counts["command_ack"] += 1
                    log.info("ack id=%d accepted=%s reason=%r", msg.id, msg.accepted, msg.reason)
                else:
                    counts["other"] += 1
                    log.info("received %s: %s", msg.type, msg)
            if link.connected:
                hb_seq += 1
                link.send(Heartbeat(seq=hb_seq, ts=time.time()))
                now = time.monotonic()
                if last_ping is None or now - last_ping >= 5.0:
                    last_ping = now
                    # fixed id=1 so the hello VI can reply with one hardcoded ack line
                    if link.send(Command(id=1, name="ping", params={})):
                        log.info("sent ping (command id=1)")
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
        print(f"\n--- summary after {time.monotonic() - started:.0f}s ---")
        for kind, n in counts.items():
            print(f"  {kind:12s} {n}")
        ok = counts["telemetry"] > 0 and counts["command_ack"] > 0
        print("RESULT:", "PASS — two-way communication confirmed" if ok
              else "FAIL — no round trip, see counts above")


if __name__ == "__main__":
    main()
