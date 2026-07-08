"""Python-side command stream for MONARCH (Phase B2; ICD v0.2 draft).

MonarchCommander is a StateMachine for the generic Supervisor engine. Each
fresh tick it emits ONE atomic `set_control_settings` command carrying the
complete intent (whole-cluster, idempotent, 1 Hz), with `pc_hb` toggled every
send so the 9056 watchdog stall-counter supervises the Python stream itself.

Safety posture baked in:
  * It never invents state: the intent is seeded from telemetry (bumpless) and
    re-seeded after every staleness gap, per ICD reconnect semantics.
  * While `command_source` != "PYTHON" it emits nothing and keeps tracking
    telemetry, so the first frame after a source flip equals the plant's last
    known settings (bumpless handover).
  * It never sends `clear_emergency_stop` (operator-only; forced False).
  * On stale telemetry it emits nothing (the engine independently drops
    commands when stale — belt and braces).
"""

from __future__ import annotations

import logging
import math
from typing import Callable

from ..engine import CommandRequest, PlantView, StateMachine
from .control_settings import ControlSettings, SystemState
from .labview_mapping import control_settings_to_labview
from .telemetry import MonarchTelemetry

log = logging.getLogger(__name__)

COMMAND_NAME = "set_control_settings"


def _finite(obj, warned: set, path: str = ""):
    """Replace non-finite floats (NaN/±Inf) with 0.0, recursively.

    LabVIEW's Flatten To JSON happily EMITS the NaN literal (seen live from
    an unset UI setpoint), Python's json tolerantly parses it — but LabVIEW's
    Unflatten From JSON REJECTS it, so echoing a NaN back gets every command
    NACKed `parse` (bench, 2026-07-08). Strict JSON has no NaN; the wire
    contract requires finite numbers, so sanitize at the serialization edge
    and warn once per field.
    """
    if isinstance(obj, float) and not math.isfinite(obj):
        if path not in warned:
            warned.add(path)
            log.warning("non-finite value in intent at %s — sending 0.0 "
                        "(check the UI control feeding it)", path)
        return 0.0
    if isinstance(obj, dict):
        return {k: _finite(v, warned, f"{path}.{k}" if path else k)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_finite(v, warned, f"{path}[{i}]") for i, v in enumerate(obj)]
    return obj


class MonarchCommander(StateMachine):
    name = "monarch_commander"

    def __init__(self) -> None:
        self._intent: ControlSettings | None = None
        self._hb = False
        self._commanding = False  # True while we held authority last tick
        self.enabled = True  # False = track telemetry but never emit (observe-only)
        self.last_nack: tuple[int, str] | None = None
        self.sent_count = 0
        self._nan_warned: set[str] = set()

    # ---- operator/sequence surface -------------------------------------
    @property
    def intent(self) -> ControlSettings | None:
        """The full intent cluster (None until first seeded from telemetry)."""
        return self._intent

    @property
    def commanding(self) -> bool:
        return self._commanding

    def modify(self, fn: Callable[[ControlSettings], None]) -> None:
        """Mutate the intent, e.g. c.modify(lambda s: setattr(s, "speed_ref", 900.0))."""
        if self._intent is None:
            raise RuntimeError("no intent yet: waiting for first telemetry")
        fn(self._intent)

    def request_mode(self, mode: SystemState) -> None:
        self.modify(lambda s: setattr(s, "requested_mode", mode))

    # ---- engine hook -----------------------------------------------------
    def step(self, view: PlantView) -> list[CommandRequest]:
        for ack in view.acks:
            if not ack.accepted:
                self.last_nack = (ack.id, ack.reason)
                log.warning("command %d NACKed by gateway: %s", ack.id, ack.reason)

        tm = view.telemetry
        if view.stale or not isinstance(tm, MonarchTelemetry):
            # ICD staleness rule: stop commanding; force a bumpless re-seed later
            if self._commanding:
                log.warning("telemetry stale: command stream paused")
            self._commanding = False
            self._intent = None
            return []

        if tm.command_source != "PYTHON" or not self.enabled:
            # not our turn to write: keep tracking the plant for a bumpless handover
            self._intent = tm.settings.model_copy(deep=True)
            self._commanding = False
            return []

        if self._intent is None:
            self._intent = tm.settings.model_copy(deep=True)
            log.info("intent seeded from telemetry (seq=%d) — bumpless", tm.seq)
        if not self._commanding:
            log.info("command authority active (source=PYTHON)")
            self._commanding = True

        self._hb = not self._hb
        out = self._intent.model_copy(deep=True)
        out.pid_control_references.pc_hb = self._hb
        out.pid_control_references.mtr_hb = tm.settings.pid_control_references.mtr_hb
        out.clear_emergency_stop = False  # operator-only, never from Python
        self.sent_count += 1
        settings = _finite(control_settings_to_labview(out), self._nan_warned)
        return [CommandRequest(COMMAND_NAME, {"settings": settings})]
