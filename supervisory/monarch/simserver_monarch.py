"""Fake MONARCH gateway (Phase B2): commandable, running the real ported logic.

Three layers:
  * MonarchGatewaySim — socket-free core. Implements the ICD v0.2 (draft)
    command validation (source-select, e-stop precedence, rate limit,
    parse/range checks), the B0 loss-of-PC response (pc_hb stall → SAFE clamp
    via the warnings channel, gated on source=PYTHON), and runs the A1-ported
    StateMachine (`state_machine.decide`) each tick — so the sim's
    system_state / limited_settings behave like the 9056 should.
  * MonarchSimLink — PlantLink implementation wrapping the sim for socket-free
    engine tests (the MONARCH analog of sim.SimPlantLink).
  * serve()/serve_client() — the same sim behind real TCP:

        python -m supervisory.monarch.simserver_monarch                 # observer use (source=UI)
        python -m supervisory.monarch.simserver_monarch --source PYTHON # command-path testing

Telemetry envelope: the full shadow-mode shape (docs/monarch-telemetry.md)
plus `command_source`.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import time
from collections import deque

from pydantic import ValidationError

from ..messages import Command, CommandAck, Message, dump
from ..messages import parse as parse_generic
from .control_settings import ControlSettings, SystemState
from .labview_mapping import control_settings_from_labview, control_settings_to_labview
from .state_machine import NO_LIMIT, StateDecisionInputs, decide
from .telemetry import parse_monarch_telemetry

log = logging.getLogger("monarch-sim")

COMMAND_NAME = "set_control_settings"


class SimPlantModel:
    """Minimal plant dynamics (Phase D2): just enough response for sequences to
    confirm against — first-order lags, not physics. Driven by the LIMITED
    settings (what the plant would actually receive). Readings are published in
    the telemetry `plant` dict under P&ID-ish tag names.
    """

    AMBIENT_BAR = 1.0
    AMBIENT_C = 25.0
    AIR_O2_PCT = 21.0

    def __init__(self) -> None:
        self.wf_pressure_bar = self.AMBIENT_BAR
        self.coolant_c = self.AMBIENT_C
        self.oil_c = self.AMBIENT_C
        self.exh_c = self.AMBIENT_C
        self.o2_pct = self.AIR_O2_PCT

    @staticmethod
    def _lag(value: float, target: float, dt: float, tau: float) -> float:
        return value + (target - value) * min(1.0, dt / tau)

    def step(self, dt: float, limited) -> None:
        p = limited.pid_control_references
        vents_open = not (p.intake_vent or p.cross_vent or p.exhaust_vent)  # False = open
        ar_feeding = p.ar.mode > 0
        # working-fluid pressure: Ar feed pressurizes toward its ref (or a
        # nominal 5 bar if no ref set); open vents bleed toward ambient
        if ar_feeding and not vents_open:
            target = p.ar.wf_pt_004_ref if p.ar.wf_pt_004_ref > 0 else 5.0
            self.wf_pressure_bar = self._lag(self.wf_pressure_bar, target, dt, 8.0)
        elif vents_open:
            self.wf_pressure_bar = self._lag(self.wf_pressure_bar, self.AMBIENT_BAR, dt, 5.0)
        # O2 fraction: argon flow displaces air; open intake readmits it
        if ar_feeding:
            self.o2_pct = self._lag(self.o2_pct, 0.0, dt, 10.0)
        elif not p.intake_vent:  # intake open
            self.o2_pct = self._lag(self.o2_pct, self.AIR_O2_PCT, dt, 60.0)
        # thermal loops: mode>0 pulls toward the loop ref (sane default target
        # when the ref is 0), else drifts to ambient
        self.coolant_c = self._lag(
            self.coolant_c,
            (p.tcoolant.ec_tt_001_ref or 60.0) if p.tcoolant.mode > 0 else self.AMBIENT_C,
            dt, 8.0)
        self.oil_c = self._lag(
            self.oil_c,
            (p.toil.eo_tt_001_ref or 70.0) if p.toil.mode > 0 else self.AMBIENT_C,
            dt, 12.0)
        self.exh_c = self._lag(
            self.exh_c,
            (p.texh.wf_tt_004_ref or 80.0) if p.texh.mode > 0 else self.AMBIENT_C,
            dt, 10.0)

    def readings(self) -> dict[str, float]:
        return {
            "WF-PT-004_bar": round(self.wf_pressure_bar, 4),
            "WF-OA-001_O2pct": round(self.o2_pct, 3),
            "EC-TT-001_degC": round(self.coolant_c, 2),
            "EO-TT-001_degC": round(self.oil_c, 2),
            "WF-TT-004_degC": round(self.exh_c, 2),
        }


class MonarchGatewaySim:
    """Socket-free gateway + supervisory core for Phase-B testing.

    Time is explicit (sim-time seconds via tick(dt)) so tests are deterministic.
    The UI side is modeled by ui_write() / operator_*() methods.
    """

    RATE_LIMIT_PER_S = 5
    PC_HB_TIMEOUT_S = 5.0
    SPEED_REF_RANGE = (0.0, 3000.0)

    def __init__(self, *, source: str = "UI", start_time: float = 0.0) -> None:
        self.source = source  # "UI" | "PYTHON" — operator-owned selector
        self.requested = ControlSettings()  # PC_ControlSettings as last written
        self.current_state = int(SystemState.STAND_BY)
        self.estop_latched = False  # operator-clearable only
        # bench/override inputs (normally UI-side):
        self.force_state = False
        self.manual_state = 0
        self.warnings_limit = NO_LIMIT
        # loss-of-PC watchdog state (B0 response, gated on source=PYTHON):
        self.pc_not_responding = False
        self._last_pc_hb = self.requested.pid_control_references.pc_hb
        self._last_pc_hb_change = start_time
        self._time = start_time
        self._cmd_times: deque[float] = deque()
        self._seq = 0
        self.post_mortem_saves = 0
        self.accepted_count = 0
        self.plant = SimPlantModel()

    # ---- operator / UI side --------------------------------------------
    def set_source(self, source: str) -> None:
        self.source = source

    def ui_write(self, settings: ControlSettings) -> None:
        """The LabVIEW UI writing PC_ControlSettings (only sensible while source=UI)."""
        self.requested = settings.model_copy(deep=True)

    def operator_estop(self) -> None:
        self.estop_latched = True

    def operator_clear_estop(self) -> None:
        self.estop_latched = False

    # ---- command path (ICD v0.2 draft validation, in order) -------------
    def handle_command(self, cmd: Command) -> CommandAck:
        def nack(reason: str) -> CommandAck:
            log.info("command %d NACK: %s", cmd.id, reason)
            return CommandAck(id=cmd.id, accepted=False, reason=reason)

        if cmd.name != COMMAND_NAME:
            return nack(f"unknown command {cmd.name!r}")
        # rate limit (commands per rolling second of sim time)
        self._cmd_times.append(self._time)
        while self._cmd_times and self._cmd_times[0] < self._time - 1.0:
            self._cmd_times.popleft()
        if len(self._cmd_times) > self.RATE_LIMIT_PER_S:
            return nack("rate")
        if self.source != "PYTHON":
            return nack("source is UI")
        raw = cmd.params.get("settings")
        if not isinstance(raw, dict):
            return nack("parse")
        try:
            settings, _unmapped = control_settings_from_labview(raw)
        except (ValidationError, ValueError, TypeError):
            return nack("parse")
        lo, hi = self.SPEED_REF_RANGE
        if not lo <= settings.speed_ref <= hi:
            return nack(f"range: Speed ref {settings.speed_ref}")
        if settings.clear_emergency_stop:
            return nack("operator only")
        # accept
        hb = settings.pid_control_references.pc_hb
        if hb != self._last_pc_hb:
            self._last_pc_hb = hb
            self._last_pc_hb_change = self._time
        if settings.emergency_stop:
            self.estop_latched = True  # e-stop from any source latches
        self.requested = settings
        self.accepted_count += 1
        return CommandAck(id=cmd.id, accepted=True)

    # ---- supervisory tick ------------------------------------------------
    def tick(self, dt: float = 1.0) -> dict:
        """Advance sim time, run the (ported) StateMachine, return the envelope."""
        self._time += dt
        self.pc_not_responding = (
            self.source == "PYTHON"
            and (self._time - self._last_pc_hb_change) > self.PC_HB_TIMEOUT_S
        )
        effective_warnings = min(
            self.warnings_limit, -1 if self.pc_not_responding else NO_LIMIT
        )
        settings_in = self.requested.model_copy(deep=True)
        settings_in.emergency_stop = settings_in.emergency_stop or self.estop_latched
        d = decide(
            StateDecisionInputs(
                current_state=self.current_state,
                settings=settings_in,
                warnings_limit=effective_warnings,
                force_state=self.force_state,
                manual_state=self.manual_state,
            )
        )
        self.current_state = int(d.system_state)
        if d.post_mortem:
            self.post_mortem_saves += 1
        self.plant.step(dt, d.limited_settings)
        self._seq += 1
        return {
            "type": "telemetry",
            "seq": self._seq,
            "ts": self._time,
            "system_state": self.current_state,
            "warnings_limit": effective_warnings,
            "manual_state": self.manual_state,
            "force_state": self.force_state,
            "command_source": self.source,
            "settings": control_settings_to_labview(self.requested),
            "limited_settings": control_settings_to_labview(d.limited_settings),
            "plant": self.plant.readings(),
        }


class MonarchSimLink:
    """PlantLink over MonarchGatewaySim — socket-free, for engine-level tests.

    Tests drive time explicitly: advance(dt) produces a telemetry frame; the
    engine's tick() consumes it and may send commands, which are validated and
    acked synchronously (ack visible on the next poll)."""

    def __init__(self, sim: MonarchGatewaySim | None = None) -> None:
        self.sim = sim if sim is not None else MonarchGatewaySim(source="PYTHON")
        self.connected = True
        self.sent: list[Message] = []
        self._inbox: list[object] = []

    def advance(self, dt: float = 1.0) -> None:
        self._inbox.append(parse_monarch_telemetry(self.sim.tick(dt)))

    def poll(self) -> list[object]:
        out, self._inbox = self._inbox, []
        return out

    def send(self, msg: Message) -> bool:
        if not self.connected:
            return False
        self.sent.append(msg)
        if isinstance(msg, Command):
            self._inbox.append(self.sim.handle_command(msg))
        return True  # generic heartbeats are accepted and ignored

    def close(self) -> None:
        self.connected = False


# ---- the same sim behind real TCP -----------------------------------------

def serve_client(conn: socket.socket, sim: MonarchGatewaySim, period_s: float, speedup: float = 1.0) -> None:
    buf = b""
    next_frame = time.monotonic()
    while True:
        remaining = next_frame - time.monotonic()
        if remaining <= 0:
            frame = sim.tick(period_s * speedup)
            conn.sendall((json.dumps(frame) + "\r\n").encode("utf-8"))
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
                msg = parse_generic(raw)
            except ValidationError:
                log.warning("discarding malformed line: %.120s", raw)
                continue
            if isinstance(msg, Command):
                ack = sim.handle_command(msg)
                conn.sendall((dump(ack) + "\r\n").encode("utf-8"))
            # generic Heartbeat messages: liveness only, nothing to do


def serve(host: str = "127.0.0.1", port: int = 5020, period_s: float = 1.0,
          speedup: float = 1.0, source: str = "UI") -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(1)
        log.info("MONARCH sim gateway on %s:%d (period %.2fs, speedup %gx, source=%s)",
                 host, port, period_s, speedup, source)
        while True:
            conn, addr = listener.accept()
            log.info("client connected from %s:%d", *addr)
            sim = MonarchGatewaySim(source=source, start_time=0.0)
            with conn:
                try:
                    serve_client(conn, sim, period_s, speedup)
                except (ConnectionError, OSError):
                    pass
            log.info("client disconnected")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fake MONARCH gateway (real ported logic, commandable)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--speedup", type=float, default=1.0)
    ap.add_argument("--source", choices=["UI", "PYTHON"], default="UI",
                    help="who holds command authority (default UI = commands NACKed)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serve(args.host, args.port, args.period, args.speedup, args.source)


if __name__ == "__main__":
    main()
