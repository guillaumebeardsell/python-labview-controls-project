"""Python port of APC_9056_StateMachine.vi (the 2026 version).

Faithful transcription of the VI's decision logic, verified against the
per-frame block-diagram export (original-labview-codebase/APC_9056_StateMachine/,
2026-07-06 re-export) and the architecture overview. Pure decisions only — no
I/O, no clocks — per the repo design rule, so it is exhaustively unit-testable
and replayable against recorded telemetry (tools/shadow_compare.py).

Semantics, as read from the wiring:

* State arbitration = MIN over candidate limits (the VI builds an array, sorts
  it, and takes element 0):
    - requested mode                       (PC_ControlSettings.Requested mode)
    - warnings limit                       (STATE LIMITATION FROM WARNINGS)
    - e-stop        -> -1 when EMERGENCY STOP else 3
    - force motoring ->  1 when Force motoring  else 3
    - force idling  ->  2 when Force idling     else 3
    - current + 1   (the "state can only be increased by 1" rule; decreases
      are immediate)
* ForceState TRUE overrides the result with ManualState ABSOLUTELY (wired
  straight to the SYSTEM STATE indicator — bypasses the MIN and the +1 rule).
* Limiting: each controller's commanded level is min(requested, max-for-state)
  per the MAX LEVEL OF CONTROL table; booleans (vents, IGN/DI, feed valves)
  are the same min on their 0/1 encoding. DisregardWarnings TRUE bypasses the
  whole limiting loop (misleading name — it disables the per-state caps, not
  just the warnings clamp). All other ControlSettings fields pass through
  unchanged.
* PostMortemSave fires on a forced (downward) transition, gated by the
  per-state "forced transition condition" cases — which are all constant TRUE
  in the current VI (no plant-feedback guards exist).

# ASSUMPTION markers flag the two details not pixel-traceable in the export;
see docs/phases/phase-a-shadow-brain.md A1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .control_settings import ControlSettings, SystemState

# States, in table-column order.
_STATE_COLUMNS = [-1, 0, 1, 2, 3]  # SAFE, STAND_BY, MOTORING, IDLING, FIRING

# MAX LEVEL OF CONTROL — per-controller cap per state (columns follow
# _STATE_COLUMNS). Transcribed from the VI's table (identical in both VI
# versions). NG feed's FIRING cell really is 6 in the VI (suspected typo for 2,
# see the phase-A notes) — ported as-is for fidelity.
MAX_LEVEL_OF_CONTROL: dict[str, tuple[int, int, int, int, int]] = {
    "ng_feed":    (0, 0, 0, 0, 6),
    "ar_feed":    (0, 0, 2, 2, 2),
    "o2_feed":    (0, 0, 2, 2, 2),
    "cool_temp":  (1, 2, 2, 2, 2),
    "exh_temp":   (1, 3, 3, 3, 3),
    "oil_temp":   (1, 3, 3, 3, 3),
    "int_vent":   (0, 1, 1, 1, 1),  # vents: 1 = closed, 0 = open (open = safe)
    "cross_vent": (0, 1, 1, 1, 1),
    "exh_vent":   (0, 1, 1, 1, 1),
    "dyno":       (0, 0, 2, 2, 2),
    "ign":        (0, 0, 0, 1, 1),
    "di":         (0, 0, 0, 1, 1),
    "mtr":        (0, 0, 2, 2, 2),
}

NO_LIMIT = 3  # a limitation source that is inactive contributes 3 (FIRING)


def _column_index(state: int) -> int | None:
    """Table column for a state; None when out of range. LabVIEW's Index Array
    returns the type default (0) for out-of-range indices, i.e. an unknown
    state degrades to all-zero caps (everything safe)."""
    try:
        return _STATE_COLUMNS.index(state)
    except ValueError:
        return None


def _cap(name: str, requested_level: int, col: int | None) -> int:
    limit = 0 if col is None else MAX_LEVEL_OF_CONTROL[name][col]
    return min(int(requested_level), limit)


@dataclass(frozen=True)
class StateDecisionInputs:
    """The StateMachine VI's inputs for one tick."""

    current_state: int  # CURRENT SYSTEM STATE (feedback of last output)
    settings: ControlSettings  # PC_ControlSettings (requested)
    warnings_limit: int = NO_LIMIT  # STATE LIMITATION FROM WARNINGS
    force_state: bool = False  # ForceState
    manual_state: int = 0  # ManualState (used only when force_state)
    disregard_warnings: bool = False  # DisregardWarnings (limiter bypass)


@dataclass(frozen=True)
class StateDecision:
    """The VI's outputs for one tick."""

    system_state: int  # SYSTEM STATE (int: ManualState may be any I8)
    limited_settings: ControlSettings  # Limited_ControlSettings
    limits: dict[str, int] = field(default_factory=dict)  # per-source, for reporting
    post_mortem: bool = False  # PostMortemSave shared-variable write


def transition_condition(state: int) -> bool:
    """The per-state 'forced transition condition' cases — all constant TRUE in
    the current VI (no plant-feedback guards are implemented). Kept as a hook so
    real guards land in one place if they're ever added."""
    return True


def source_limits(inputs: StateDecisionInputs) -> dict[str, int]:
    """Each limitation source's contribution (the VI's build-array elements)."""
    s = inputs.settings
    return {
        "requested": int(s.requested_mode),
        "warnings": int(inputs.warnings_limit),
        "estop": -1 if s.emergency_stop else NO_LIMIT,
        "force_motoring": 1 if s.force_motoring else NO_LIMIT,
        "force_idling": 2 if s.force_idling else NO_LIMIT,
        "step_up": inputs.current_state + 1,
    }


def decide_state(inputs: StateDecisionInputs) -> int:
    """SYSTEM STATE for this tick (see module docstring for the rules)."""
    if inputs.force_state:
        return int(inputs.manual_state)
    return min(source_limits(inputs).values())


def limit_settings(
    settings: ControlSettings, state: int, disregard_warnings: bool = False
) -> ControlSettings:
    """Limited_ControlSettings: the requested settings clamped to the
    MAX LEVEL OF CONTROL table for `state`. Only the mode/enable/vent/valve
    fields are clamped; everything else passes through unchanged."""
    limited = settings.model_copy(deep=True)
    if disregard_warnings:
        return limited  # limiter bypass — caps not applied

    col = _column_index(state)
    p = limited.pid_control_references
    q = settings.pid_control_references

    p.ng.mode = _cap("ng_feed", q.ng.mode, col)
    p.ar.mode = _cap("ar_feed", q.ar.mode, col)
    p.o2.mode = _cap("o2_feed", q.o2.mode, col)
    p.tcoolant.mode = _cap("cool_temp", q.tcoolant.mode, col)
    p.texh.mode = _cap("exh_temp", q.texh.mode, col)
    p.toil.mode = _cap("oil_temp", q.toil.mode, col)
    p.intake_vent = bool(_cap("int_vent", int(q.intake_vent), col))
    p.cross_vent = bool(_cap("cross_vent", int(q.cross_vent), col))
    p.exhaust_vent = bool(_cap("exh_vent", int(q.exhaust_vent), col))
    p.dyno.mode = _cap("dyno", q.dyno.mode, col)
    p.membrane.mode = _cap("mtr", q.membrane.mode, col)
    limited.ign_enable = bool(_cap("ign", int(settings.ign_enable), col))
    limited.di_enable = bool(_cap("di", int(settings.di_enable), col))
    # ASSUMPTION: the feed-valve booleans clamp with their feed rows (the VI's
    # limiting array has 16 elements incl. the NG/Ar/O2 valves; exact rows for
    # the valve entries not pixel-verified). Safe direction is identical:
    # closed (False) outside run states.
    p.ng_valve = bool(_cap("ng_feed", int(q.ng_valve), col))
    p.ar_valve = bool(_cap("ar_feed", int(q.ar_valve), col))
    p.o2_valve = bool(_cap("o2_feed", int(q.o2_valve), col))
    return limited


def decide(inputs: StateDecisionInputs) -> StateDecision:
    """One full tick of the StateMachine VI."""
    limits = source_limits(inputs)
    new_state = decide_state(inputs)
    # ASSUMPTION: '>' operand order — post-mortem on a forced DOWNWARD
    # transition (new below current), gated by the per-state condition.
    post_mortem = (new_state < inputs.current_state) and transition_condition(
        inputs.current_state
    )
    limited = limit_settings(inputs.settings, new_state, inputs.disregard_warnings)
    return StateDecision(
        system_state=new_state,
        limited_settings=limited,
        limits=limits,
        post_mortem=post_mortem,
    )


def max_levels_for_state(state: int) -> dict[str, int]:
    """The 'maximum controller mode' row the VI publishes for `state`."""
    col = _column_index(state)
    return {
        name: (0 if col is None else row[col])
        for name, row in MAX_LEVEL_OF_CONTROL.items()
    }
