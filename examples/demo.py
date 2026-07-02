"""End-to-end demo against the fake gateway.

Terminal 1:  python -m supervisory.simserver --speedup 10
Terminal 2:  python examples/demo.py

The machine heats the toy plant to 80 C, soaks for 10 s, and stops. Kill the
simserver mid-run to watch staleness/HOLD handling; restart it to watch the
supervisor reconnect and recover. All traffic is recorded to traffic.jsonl.
"""

import logging

from supervisory import (
    CommandRequest,
    PlantView,
    Recorder,
    StateMachine,
    Supervisor,
    TcpPlantLink,
)

log = logging.getLogger("demo")


class HeatSoak(StateMachine):
    """WAIT_READY -> HEATING -> SOAK -> DONE, with HOLD on staleness or gateway safe-hold.

    This is the porting pattern for the LabVIEW state machines: explicit state
    names, decisions taken only from the PlantView, every effect returned as a
    CommandRequest.
    """

    name = "heat_soak"
    TARGET_C = 80.0
    SOAK_S = 10.0

    def __init__(self):
        self.state = "WAIT_READY"
        self._soak_until = None

    def _goto(self, state):
        if state != self.state:
            log.info("%s: %s -> %s", self.name, self.state, state)
            self.state = state

    def step(self, view: PlantView):
        tm = view.telemetry
        if view.stale or tm is None:
            if self.state not in ("HOLD", "DONE"):
                self._goto("HOLD")
            return []
        if tm.mode == "SAFE_HOLD":
            self._goto("HOLD")
            return []

        if self.state == "HOLD":
            # plant is back and healthy: restart the sequence conservatively
            if tm.mode == "IDLE" and tm.flags.get("interlock_ok"):
                self._goto("WAIT_READY")
            return []
        if self.state == "WAIT_READY":
            if tm.mode == "IDLE" and tm.flags.get("interlock_ok"):
                self._goto("HEATING")
                return [
                    CommandRequest("set_setpoint", {"value": self.TARGET_C}),
                    CommandRequest("start"),
                ]
            return []
        if self.state == "HEATING":
            if tm.channels.get("temp_c", 0.0) >= self.TARGET_C - 1.0:
                self._goto("SOAK")
                self._soak_until = view.now + self.SOAK_S
            return []
        if self.state == "SOAK":
            if view.now >= self._soak_until:
                self._goto("DONE")
                return [CommandRequest("stop")]
            return []
        return []  # DONE


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    link = TcpPlantLink()
    recorder = Recorder("traffic.jsonl")
    sup = Supervisor(link, [HeatSoak()], recorder=recorder)
    try:
        sup.run()
    finally:
        link.close()
        recorder.close()


if __name__ == "__main__":
    main()
