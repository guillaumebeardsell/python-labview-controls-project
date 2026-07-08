"""Operator-request mirroring (ICD §7.8) — the UI stays the operator's input
surface while Python holds authority.

While source=PYTHON, the UI's inputs are redirected to `PC_OperatorRequests`
and arrive in telemetry as `operator_requests`. This machine mirrors them into
the commander's intent so operators keep working the familiar screens, with
Python (sequences, schedules, policies) deciding in the middle.

The mirroring POLICY (deliberate, reviewed):

  * SAFETY INPUTS mirror ALWAYS, sequence or not, instantly:
      - emergency_stop  — set-only (True mirrors; False does NOT clear —
        the latch clears via the operator's direct channel, never through
        Python, per §7.4)
      - force_idling, force_motoring — the operator's overrides by design
  * NO SEQUENCE ACTIVE: full transparency — the whole request cluster mirrors
    (except pc_hb/mtr_hb, which the commander owns, and clear_emergency_stop,
    which Python never sends). Python-in-command then behaves exactly like
    UI-in-command until automation adds value on top.
  * SEQUENCE ACTIVE (RUNNING/HOLDING): the sequence owns the intent; only the
    safety inputs mirror. An operator who wants to redirect mid-sequence
    aborts the sequence first (which lands on its declared safe change).

Run it in the Supervisor BEFORE the SequenceExecutor and MonarchCommander:
[mirror, executor, commander] — so requests land, then sequences adjust, then
the commander emits.
"""

from __future__ import annotations

import logging

from ..engine import CommandRequest, PlantView, StateMachine
from ..sequencing import Status
from .commander import MonarchCommander
from .control_settings import ControlSettings
from .sequences import SequenceExecutor
from .telemetry import MonarchTelemetry

log = logging.getLogger(__name__)


def _get_path(obj, path: str):
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _set_path(obj, path: str, value) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)


class OperatorRequestMirror(StateMachine):
    name = "operator_mirror"

    def __init__(self, commander: MonarchCommander,
                 executor: SequenceExecutor | None = None,
                 safety_only: bool = False) -> None:
        self.commander = commander
        self.executor = executor
        # safety_only: mirror ONLY the safety inputs (e-stop set, force
        # idling/motoring), never the full cluster. This is the floor no
        # configuration may go below: drill B4-8 caught a mirror-less
        # supervisor ignoring the panel e-stop for 4 s while dutifully
        # feeding the watchdog (2026-07-08). "--safety-only-mirror" means
        # this mode, never absent.
        self.safety_only = safety_only
        # claims: dotted intent paths OWNED BY PYTHON — excluded from the
        # full mirror so the panel's (stale) value can't stomp a computed
        # one. This is how "Python does some of the work" coexists with the
        # panel: a scheduler/PID machine claims the fields it writes, and
        # the team retires the matching panel control in the same breath
        # (ICD 7.7 ownership evolution). Safety inputs can never be claimed.
        self.claims: set[str] = set()
        self.mirrored_count = 0

    # ---- field ownership -----------------------------------------------
    _UNCLAIMABLE = ("emergency_stop", "clear_emergency_stop",
                    "force_idling", "force_motoring")

    def claim(self, *paths: str) -> None:
        """Mark intent fields as Python-owned (dotted paths, e.g.
        'pid_control_references.tcoolant.ec_tt_001_ref')."""
        for path in paths:
            if path.split(".")[-1] in self._UNCLAIMABLE:
                raise ValueError(f"safety input {path!r} cannot be claimed")
            self.claims.add(path)

    def release(self, *paths: str) -> None:
        """Return fields to panel ownership."""
        for path in paths:
            self.claims.discard(path)

    def _sequence_active(self) -> bool:
        return (self.executor is not None
                and self.executor.status in (Status.RUNNING, Status.HOLDING))

    def step(self, view: PlantView) -> list[CommandRequest]:
        tm = view.telemetry
        if (view.stale or not isinstance(tm, MonarchTelemetry)
                or tm.operator_requests is None
                or not self.commander.commanding):
            return []
        req = tm.operator_requests

        if self._sequence_active() or self.safety_only:
            def safety_only(intent: ControlSettings) -> None:
                if req.emergency_stop:
                    intent.emergency_stop = True  # set-only
                intent.force_idling = req.force_idling
                intent.force_motoring = req.force_motoring
            self.commander.modify(safety_only)
        else:
            def full_mirror(intent: ControlSettings) -> None:
                estop_latched = intent.emergency_stop
                fresh = req.model_copy(deep=True)
                # fields the mirror never touches:
                fresh.clear_emergency_stop = False  # operator-direct channel only
                fresh.pid_control_references.pc_hb = intent.pid_control_references.pc_hb
                fresh.pid_control_references.mtr_hb = intent.pid_control_references.mtr_hb
                # e-stop is set-only through the mirror
                fresh.emergency_stop = estop_latched or req.emergency_stop
                # Python-owned fields keep their computed values
                for path in self.claims:
                    _set_path(fresh, path, _get_path(intent, path))
                intent.__dict__.update(fresh.__dict__)
            self.commander.modify(full_mirror)
        self.mirrored_count += 1
        return []  # the commander emits the actual command
