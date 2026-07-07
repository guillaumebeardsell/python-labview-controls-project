"""Setpoint scheduling (Phase E3) — operating-point tables as data.

A Schedule maps an operating point (system state + speed band) to a set of
intent changes (loop modes + references). The Scheduler applies the matching
row's changes through the commander — but only when the operating point
CHANGES, and never over a manual override: once the operator touches a field
the scheduler manages, the scheduler stops re-asserting it until the next
operating-point change (manual wins; the scheduler never fights the operator).

Rows are reviewed data (`ScheduleRow` tuples); values come from the team
during commissioning. Row lookup: first row whose state matches and whose
speed band contains speed_ref — order the table accordingly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

Change = Callable[[Any], None]


@dataclass(frozen=True)
class ScheduleRow:
    name: str
    state: int  # system state this row applies to
    speed_min: float = float("-inf")
    speed_max: float = float("inf")
    changes: tuple[Change, ...] = ()  # applied on entry to this operating point


@dataclass
class Scheduler:
    rows: tuple[ScheduleRow, ...] = ()
    _active_row: str | None = None
    _suspended: bool = False  # manual override in effect for this op-point
    applied_log: list[str] = field(default_factory=list)

    def match(self, state: int, speed_ref: float) -> ScheduleRow | None:
        for row in self.rows:
            if row.state == state and row.speed_min <= speed_ref <= row.speed_max:
                return row
        return None

    def manual_override(self) -> None:
        """Call when the operator manually changes a scheduler-managed field:
        the scheduler yields until the next operating-point change."""
        if not self._suspended:
            log.info("scheduler suspended by manual override (until next op-point)")
        self._suspended = True

    def step(self, state: int, speed_ref: float) -> list[Change]:
        """Returns the changes to apply this tick (empty in steady state)."""
        row = self.match(state, speed_ref)
        name = row.name if row else None
        if name == self._active_row:
            return []  # same operating point: never re-assert (manual wins)
        # operating point changed: re-arm and apply the new row (if any)
        self._active_row = name
        self._suspended = False
        if row is None:
            return []
        self.applied_log.append(row.name)
        log.info("schedule row applied: %s", row.name)
        return list(row.changes)
