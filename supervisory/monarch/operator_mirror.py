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


class OperatorRequestMirror(StateMachine):
    name = "operator_mirror"

    def __init__(self, commander: MonarchCommander,
                 executor: SequenceExecutor | None = None) -> None:
        self.commander = commander
        self.executor = executor
        self.mirrored_count = 0

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

        if self._sequence_active():
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
                intent.__dict__.update(fresh.__dict__)
            self.commander.modify(full_mirror)
        self.mirrored_count += 1
        return []  # the commander emits the actual command
