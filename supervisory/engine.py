"""Supervisory engine: the tick loop, the plant view, and the StateMachine base.

The design rule that keeps everything testable: state machines are pure
decisions. Each tick they receive a PlantView (telemetry as LabVIEW reports
it, staleness, acks) and return CommandRequests. They never touch sockets,
clocks, or globals. The Supervisor owns all side effects — draining the link,
sending commands, emitting the heartbeat — so a machine can be unit-tested or
replayed against recorded telemetry with no infrastructure at all.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .link import PlantLink
from .messages import Command, CommandAck, Heartbeat, ParamValue
from .recorder import NullRecorder, Recorder

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandRequest:
    """A machine's request. The engine assigns the wire id and sends it."""

    name: str
    params: dict[str, ParamValue] = field(default_factory=dict)


@dataclass(frozen=True)
class PlantView:
    """What state machines see each tick."""

    telemetry: object | None  # latest telemetry-typed message; None before the first frame
    stale: bool  # True when telemetry is missing or old — engine drops commands
    connected: bool  # TCP link status
    acks: tuple[CommandAck, ...]  # acks received since the previous tick
    now: float  # monotonic time of this tick, for machine-internal timing


class StateMachine:
    """Base class for supervisory state machines.

    Subclasses implement step() as a pure decision: read the view and your own
    internal state, return the commands you want sent. When view.stale is True
    the engine discards returned commands — use staleness to drive your own
    hold/abort transitions instead of assuming commands went out.
    """

    name: str = "machine"

    def step(self, view: PlantView) -> list[CommandRequest]:
        raise NotImplementedError


class Supervisor:
    """Owns the tick loop (ICD sections 4-5): drains the link, maintains the
    plant view, steps every machine, sends their commands, emits the heartbeat.

    tick() takes `now` (monotonic seconds) as a parameter so tests can drive
    time explicitly; run() is the thin wall-clock wrapper around it.
    """

    def __init__(
        self,
        link: PlantLink,
        machines: list[StateMachine],
        period_s: float = 1.0,
        telemetry_timeout_s: float = 3.0,
        recorder: Recorder | NullRecorder | None = None,
    ) -> None:
        self._link = link
        self._machines = list(machines)
        self._period_s = period_s
        self._telemetry_timeout_s = telemetry_timeout_s
        self._recorder = recorder if recorder is not None else NullRecorder()
        self._next_cmd_id = 1
        self._next_hb_seq = 1
        self._latest: Telemetry | None = None
        self._latest_at: float | None = None  # monotonic time of last telemetry
        self._pending: dict[int, Command] = {}
        self._was_stale = True

    def tick(self, now: float) -> PlantView:
        acks: list[CommandAck] = []
        for msg in self._link.poll():
            self._recorder.record("rx", msg)
            # duck-typed so richer payloads (e.g. MonarchTelemetry via a custom
            # link parser) count as telemetry without subclassing messages.Telemetry
            if getattr(msg, "type", None) == "telemetry":
                self._latest = msg
                self._latest_at = now
            elif isinstance(msg, CommandAck):
                cmd = self._pending.pop(msg.id, None)
                if cmd is None:
                    log.warning("ack for unknown command id %d (ICD section 5)", msg.id)
                elif not msg.accepted:
                    log.warning("command %d %r rejected by gateway: %s", msg.id, cmd.name, msg.reason)
                acks.append(msg)
            else:
                log.warning("unexpected %s message from gateway, discarded", msg.type)

        stale = (
            self._latest_at is None
            or (now - self._latest_at) > self._telemetry_timeout_s
        )
        if stale and not self._was_stale:
            log.warning(
                "plant view stale, abandoning %d pending command(s)", len(self._pending)
            )
            self._pending.clear()
        self._was_stale = stale

        view = PlantView(
            telemetry=self._latest,
            stale=stale,
            connected=self._link.connected,
            acks=tuple(acks),
            now=now,
        )

        for machine in self._machines:
            try:
                requests = machine.step(view)
            except Exception:
                log.exception("state machine %r crashed in step(), continuing", machine.name)
                continue
            for req in requests:
                if stale:
                    log.warning(
                        "dropping command %r from %r: plant view is stale", req.name, machine.name
                    )
                    continue
                cmd = Command(id=self._next_cmd_id, name=req.name, params=req.params)
                self._next_cmd_id += 1
                if self._link.send(cmd):
                    self._pending[cmd.id] = cmd
                    self._recorder.record("tx", cmd)

        if self._link.connected:
            hb = Heartbeat(seq=self._next_hb_seq, ts=time.time())
            self._next_hb_seq += 1
            if self._link.send(hb):
                self._recorder.record("tx", hb)

        return view

    def run(self) -> None:
        """Blocking wall-clock loop at period_s. Ctrl-C to stop."""
        log.info("supervisor running, period %.2fs", self._period_s)
        next_tick = time.monotonic()
        try:
            while True:
                self.tick(time.monotonic())
                next_tick += self._period_s
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.monotonic()  # fell behind; don't burst to catch up
        except KeyboardInterrupt:
            log.info("supervisor stopped")
