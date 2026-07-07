"""Generic sequencing framework (Phase D1) — automated operating procedures.

A Sequence is DATA: an ordered list of steps, each mapping one row of the
procedure-spec template (docs/phases/phase-d-sequencing.md): an action (an
intent change), a confirmation (a telemetry predicate), and a timeout. The
SequenceRunner executes it as a PURE decision process — time and telemetry are
passed in, changes are handed back — so sequences unit-test and replay exactly
like every other machine in this repo. The runner knows nothing about MONARCH;
the MONARCH adapter lives in supervisory/monarch/sequences.py.

Safety semantics (fixed, not configurable):
  * Every confirmation comes from telemetry, never from "command sent".
  * A step with a confirmation MUST declare a timeout; expiry aborts.
  * Invariants are evaluated every tick with fresh telemetry; a violation
    aborts immediately, mid-step.
  * Stale telemetry aborts (after `max_stale_ticks`, default 0 extra grace —
    the transport already tolerates 3 s before declaring staleness).
  * An abort is always reachable (checked every tick), always terminal, and
    lands by emitting the sequence's declared `abort_change` exactly once.
  * Operator holds block until confirmed; operator abort works in any state.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence as Seq

log = logging.getLogger(__name__)

# A change mutates the commander's intent object (e.g. a ControlSettings).
Change = Callable[[Any], None]
# A condition reads the latest telemetry frame.
Condition = Callable[[Any], bool]


# --------------------------------------------------------------------- steps


@dataclass(frozen=True)
class Action:
    """One procedure row: apply `change` (optional), then wait for `confirm`
    (optional) within `timeout_s`. No confirm = advance on the next tick."""

    label: str
    change: Change | None = None
    confirm: Condition | None = None
    timeout_s: float | None = None

    def __post_init__(self):
        if self.confirm is not None and self.timeout_s is None:
            raise ValueError(
                f"step {self.label!r}: a confirmation requires a timeout "
                "(unbounded waits are not allowed in sequences)"
            )


@dataclass(frozen=True)
class Hold:
    """Operator hold: block until confirm_hold() (or abort on optional timeout)."""

    label: str
    message: str
    timeout_s: float | None = None


@dataclass(frozen=True)
class Branch:
    """Evaluate `condition` on entry (fresh telemetry) and splice in one arm."""

    label: str
    condition: Condition
    then: tuple = ()
    otherwise: tuple = ()


Step = Action | Hold | Branch


@dataclass(frozen=True)
class Invariant:
    """Must hold on every fresh-telemetry tick while the sequence runs."""

    name: str
    ok: Condition


@dataclass(frozen=True)
class Sequence:
    """A procedure. `abort_change` is the declared safe landing (applied once
    on any abort); `invariants` hold for the whole sequence."""

    name: str
    steps: tuple
    abort_change: Change | None = None
    invariants: tuple = ()
    description: str = ""


class Status(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    HOLDING = "holding"
    DONE = "done"
    ABORTED = "aborted"


# -------------------------------------------------------------------- runner


@dataclass
class TickResult:
    """What the caller must enact this tick."""

    changes: list[Change] = field(default_factory=list)
    status: Status = Status.IDLE
    active_label: str | None = None
    abort_reason: str | None = None


class SequenceRunner:
    """Pure executor: feed it (now, telemetry, stale) each tick; apply the
    returned changes to the command intent. One runner runs one sequence."""

    def __init__(
        self,
        sequence: Sequence,
        *,
        extra_invariants: Seq[Invariant] = (),
        max_stale_ticks: int = 0,
    ) -> None:
        self.sequence = sequence
        self._invariants = tuple(sequence.invariants) + tuple(extra_invariants)
        self._max_stale_ticks = max_stale_ticks
        self._steps: list[Step] = list(sequence.steps)
        self._idx = 0
        self._entered_at: float | None = None
        self._change_applied = False
        self._stale_ticks = 0
        self._hold_confirmed = False
        self._abort_pending: str | None = None
        self.status = Status.IDLE
        self.abort_reason: str | None = None

    # ---- operator surface -------------------------------------------------
    def start(self) -> None:
        if self.status is not Status.IDLE:
            raise RuntimeError(f"cannot start from {self.status}")
        self.status = Status.RUNNING if self._steps else Status.DONE

    def confirm_hold(self) -> None:
        self._hold_confirmed = True

    def abort(self, reason: str = "operator") -> None:
        """Request an abort; it lands on the next tick (or immediately if
        called between ticks — the landing change is emitted by tick())."""
        if self.status in (Status.RUNNING, Status.HOLDING):
            self._abort_pending = reason

    # ---- introspection -----------------------------------------------------
    @property
    def active_step(self) -> Step | None:
        if self.status in (Status.RUNNING, Status.HOLDING) and self._idx < len(self._steps):
            return self._steps[self._idx]
        return None

    @property
    def progress(self) -> tuple[int, int]:
        return (self._idx, len(self._steps))

    # ---- core ---------------------------------------------------------------
    def tick(self, now: float, telemetry: Any | None, stale: bool) -> TickResult:
        res = TickResult(status=self.status)
        if self.status not in (Status.RUNNING, Status.HOLDING):
            return res

        step = self._steps[self._idx] if self._idx < len(self._steps) else None
        res.active_label = getattr(step, "label", None)

        # operator abort first — always reachable
        if self._abort_pending is not None:
            return self._land_abort(res, self._abort_pending)

        # staleness: telemetry is unusable; hold position or abort
        if stale or telemetry is None:
            self._stale_ticks += 1
            if self._stale_ticks > self._max_stale_ticks:
                return self._land_abort(res, "stale telemetry")
            return res
        self._stale_ticks = 0

        # invariants: every tick, fresh telemetry, mid-step
        for inv in self._invariants:
            try:
                ok = inv.ok(telemetry)
            except Exception:
                log.exception("invariant %r raised; treating as violated", inv.name)
                ok = False
            if not ok:
                return self._land_abort(res, f"invariant:{inv.name}")

        if step is None:  # ran past the end
            self.status = res.status = Status.DONE
            return res

        if self._entered_at is None:
            self._entered_at = now

        if isinstance(step, Branch):
            try:
                arm = step.then if step.condition(telemetry) else step.otherwise
            except Exception:
                log.exception("branch %r condition raised; aborting", step.label)
                return self._land_abort(res, f"branch:{step.label}")
            self._steps[self._idx + 1 : self._idx + 1] = list(arm)
            self._advance(res)
            return res

        if isinstance(step, Hold):
            self.status = res.status = Status.HOLDING
            if self._hold_confirmed:
                self._hold_confirmed = False
                self.status = Status.RUNNING
                self._advance(res)
                return res
            if step.timeout_s is not None and now - self._entered_at > step.timeout_s:
                return self._land_abort(res, f"hold timeout:{step.label}")
            return res

        # Action
        if step.change is not None and not self._change_applied:
            res.changes.append(step.change)
            self._change_applied = True
            if step.confirm is None:
                # change emitted; advance on the NEXT tick so one change lands
                # per tick (pacing) and telemetry can reflect it
                return res
        if step.confirm is None:
            self._advance(res)
            return res
        try:
            confirmed = step.confirm(telemetry)
        except Exception:
            log.exception("confirm of %r raised; aborting", step.label)
            return self._land_abort(res, f"confirm error:{step.label}")
        if confirmed:
            self._advance(res)
            return res
        if now - self._entered_at > step.timeout_s:
            return self._land_abort(res, f"timeout:{step.label}")
        return res

    # ---- helpers -------------------------------------------------------------
    def _advance(self, res: TickResult) -> None:
        self._idx += 1
        self._entered_at = None
        self._change_applied = False
        if self._idx >= len(self._steps):
            self.status = Status.DONE
        res.status = self.status
        res.active_label = getattr(self.active_step, "label", res.active_label)

    def _land_abort(self, res: TickResult, reason: str) -> TickResult:
        log.warning("sequence %r ABORT: %s", self.sequence.name, reason)
        self.status = Status.ABORTED
        self.abort_reason = reason
        self._abort_pending = None
        res.status = Status.ABORTED
        res.abort_reason = reason
        if self.sequence.abort_change is not None:
            res.changes.append(self.sequence.abort_change)
        return res
