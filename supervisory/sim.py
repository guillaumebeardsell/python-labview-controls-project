"""Simulated LabVIEW gateway for tests and Python-side development.

SimPlant models the gateway's ICD behavior — command validation against mode
and interlocks, heartbeat watchdog with safe hold, telemetry frames — plus a
toy first-order thermal plant so sequences have something to act on.

SimPlantLink adapts it to the PlantLink protocol so the engine runs against
it with no sockets. Tests drive time explicitly: link.advance(dt) produces a
telemetry frame, then Supervisor.tick(now) consumes it.
"""

from __future__ import annotations

from .messages import Command, CommandAck, Heartbeat, Message, Telemetry


class SimPlant:
    """Toy plant behind gateway-style validation.

    Modes: IDLE <-> RUNNING, plus SAFE_HOLD (entered on watchdog lapse or
    interlock trip; leaving it requires an explicit reset, matching the ICD
    rule that a new connection alone never clears a safe hold).

    Commands: start, stop, set_setpoint {value}, reset.
    """

    HEARTBEAT_TIMEOUT_S = 5.0
    SETPOINT_MIN_C = 0.0
    SETPOINT_MAX_C = 200.0
    AMBIENT_C = 25.0

    def __init__(self, *, start_time: float = 0.0) -> None:
        self.mode = "IDLE"
        self.temp_c = self.AMBIENT_C
        self.setpoint_c = self.AMBIENT_C
        self.interlock_ok = True
        self._seq = 0
        self._time = start_time
        self._last_heartbeat = start_time

    def handle_command(self, cmd: Command) -> CommandAck:
        def nack(reason: str) -> CommandAck:
            return CommandAck(id=cmd.id, accepted=False, reason=reason)

        if self.mode == "SAFE_HOLD" and cmd.name != "reset":
            return nack("in SAFE_HOLD, reset required")
        if cmd.name == "start":
            if not self.interlock_ok:
                return nack("interlock not OK")
            if self.mode != "IDLE":
                return nack(f"cannot start from {self.mode}")
            self.mode = "RUNNING"
        elif cmd.name == "stop":
            if self.mode == "RUNNING":
                self.mode = "IDLE"
        elif cmd.name == "set_setpoint":
            value = cmd.params.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return nack("missing or non-numeric 'value'")
            if not self.SETPOINT_MIN_C <= value <= self.SETPOINT_MAX_C:
                return nack(
                    f"setpoint {value} outside [{self.SETPOINT_MIN_C}, {self.SETPOINT_MAX_C}]"
                )
            self.setpoint_c = float(value)
        elif cmd.name == "reset":
            if self.mode == "SAFE_HOLD":
                if not self.interlock_ok:
                    return nack("interlock not OK")
                self.mode = "IDLE"
                self._last_heartbeat = self._time  # give the watchdog a fresh window
        else:
            return nack(f"unknown command {cmd.name!r}")
        return CommandAck(id=cmd.id, accepted=True)

    def heartbeat(self) -> None:
        self._last_heartbeat = self._time

    def tick(self, dt: float = 1.0) -> Telemetry:
        """Advance the plant dt seconds and return the telemetry frame."""
        self._time += dt
        if self.mode != "SAFE_HOLD":
            if self._time - self._last_heartbeat > self.HEARTBEAT_TIMEOUT_S:
                self.mode = "SAFE_HOLD"
            elif self.mode == "RUNNING" and not self.interlock_ok:
                self.mode = "SAFE_HOLD"
        target = self.setpoint_c if self.mode == "RUNNING" else self.AMBIENT_C
        tau = 30.0 if self.mode == "RUNNING" else 120.0
        self.temp_c += (target - self.temp_c) * min(1.0, dt / tau)
        self._seq += 1
        return Telemetry(
            seq=self._seq,
            ts=self._time,
            mode=self.mode,
            channels={"temp_c": round(self.temp_c, 3), "setpoint_c": self.setpoint_c},
            flags={"interlock_ok": self.interlock_ok},
        )


class SimPlantLink:
    """PlantLink implementation wrapping SimPlant, for socket-free tests.

    Commands are validated and acked synchronously on send(); the ack shows up
    on the next poll(), like a fast gateway would behave. Everything the
    engine sent is kept in `sent` for assertions.
    """

    def __init__(self, plant: SimPlant | None = None) -> None:
        self.plant = plant if plant is not None else SimPlant()
        self.connected = True
        self.sent: list[Message] = []
        self._inbox: list[Message] = []

    def advance(self, dt: float = 1.0) -> None:
        """Advance plant time and queue the resulting telemetry frame."""
        self._inbox.append(self.plant.tick(dt))

    def poll(self) -> list[Message]:
        out, self._inbox = self._inbox, []
        return out

    def send(self, msg: Message) -> bool:
        if not self.connected:
            return False
        self.sent.append(msg)
        if isinstance(msg, Command):
            self._inbox.append(self.plant.handle_command(msg))
        elif isinstance(msg, Heartbeat):
            self.plant.heartbeat()
        return True

    def close(self) -> None:
        self.connected = False
