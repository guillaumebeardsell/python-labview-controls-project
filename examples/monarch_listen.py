"""Stage-1 read-only observer: ingest and record real MONARCH telemetry.

Connects to the gateway, decodes each 1 Hz telemetry frame into a fully-typed
ControlSettings + system state, records every frame to a JSONL file, and prints
a live one-line status. It has NO authority — it only observes — so it's the
safe first step of moving supervision to Python.

    # terminal 1 (until the LabVIEW gateway sends real telemetry):
    python -m supervisory.monarch.simserver_monarch --speedup 5
    # terminal 2:
    python examples/monarch_listen.py

It sends a heartbeat each second so a watchdog-guarded gateway stays live, but
issues no commands. Ctrl-C prints a summary. Traffic is saved to monarch.jsonl.
"""

import logging
import time

from supervisory import Recorder, TcpPlantLink
from supervisory.messages import CommandAck, Heartbeat
from supervisory.monarch import MonarchTelemetry, monarch_parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("observe")

    link = TcpPlantLink(parser=monarch_parser)
    recorder = Recorder("monarch.jsonl")
    frames = 0
    hb = 0
    last_state = None
    started = time.monotonic()
    try:
        while True:
            for msg in link.poll():
                if isinstance(msg, MonarchTelemetry):
                    frames += 1
                    recorder.record("rx", msg)
                    cs = msg.settings
                    if msg.system_state != last_state:
                        log.info("system state -> %s", msg.system_state.name)
                        last_state = msg.system_state
                    extra = ""
                    if msg.warnings_limit is not None:
                        extra += f" warn_lim={msg.warnings_limit} force={msg.force_state}"
                    if msg.limited_settings is not None:
                        lim = msg.limited_settings
                        extra += (f" | limited: ign={lim.ign_enable} "
                                  f"ng_mode={lim.pid_control_references.ng.mode}")
                    log.info(
                        "seq=%d state=%s speed_ref=%.0f ign=%s ng_mode=%d spark=%.0f%s%s",
                        msg.seq, msg.system_state.name, cs.speed_ref, cs.ign_enable,
                        cs.pid_control_references.ng.mode, cs.spark_advance_cadbtdc, extra,
                        f" UNMAPPED={list(msg.unmapped)}" if msg.unmapped else "",
                    )
                elif isinstance(msg, CommandAck):
                    log.info("ack id=%d accepted=%s", msg.id, msg.accepted)
            if link.connected:
                hb += 1
                link.send(Heartbeat(seq=hb, ts=time.time()))
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
        recorder.close()
        print(f"\n--- observed {frames} telemetry frame(s) in {time.monotonic()-started:.0f}s ---")
        print("recording: monarch.jsonl")


if __name__ == "__main__":
    main()
