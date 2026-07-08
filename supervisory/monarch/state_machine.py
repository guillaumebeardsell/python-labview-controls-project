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
* PostMortemSave fires on a downward transition (CURRENT SYSTEM STATE > new
  state) AND NOT ForceState — i.e. a manually forced drop does NOT trigger the
  post-mortem save. (Pixel-verified 2026-07-07: `>` then `∧` with `¬ForceState`
  feeding the True case that writes the shared variable.)

The two former ASSUMPTION markers were resolved 2026-07-07 against the full-res
re-export (original-labview-codebase/APC_9056_StateMachine/, 23:43):
  1. The NG/Ar/O2 feed-valve booleans have their OWN rows (13-15) in the
     limiting array, (0,1,1,1,1) each — vent-style, forced closed only in
     SAFE — not their feed-controller rows as previously assumed.
  2. The post-mortem gate is ¬ForceState (see above), not the per-state
     transition-condition case.
Also found: the executed array's Ar-feed row is (0,0,3,3,3) while the
on-diagram documentation table says (0,0,2,2,2). NOT harmless: per the
controller-VI exports (2026-07-08), mode 3 = cascaded closed loop on the
cascade-capable loops (Texh/Toil/Ar), and NG defines modes 4/5/6 = closed
loop on lambda/IMEP/torque feedback — so the executed 3 PERMITS cascaded Ar
control from MOTORING (the doc table's 2 would forbid it), and NG's FIRING
cap of 6 permits all NG feedback modes. The ">2" cells are real mode caps,
not typos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .control_settings import ControlSettings, SystemState

# States, in table-column order.
_STATE_COLUMNS = [-1, 0, 1, 2, 3]  # SAFE, STAND_BY, MOTORING, IDLING, FIRING

# MAX LEVEL OF CONTROL — per-controller cap per state (columns follow
# _STATE_COLUMNS). Transcribed from the EXECUTED 16-row array constant in the
# full-res 2026-07-07 export (not the on-diagram doc table, which disagrees on
# the Ar row). The ">2" cells are NOT typos (resolved 2026-07-08 from the
# controller exports): each controller's mode enum extends past 2 — mode 3 =
# cascaded closed loop (Texh/Toil/Ar), NG modes 4/5/6 = closed loop on
# lambda/IMEP/torque feedback — so cap 3 permits cascade and NG's FIRING cap
# of 6 permits every NG feedback mode. Rows 13-15 are the NG/Ar/O2 feed-valve
# booleans.
MAX_LEVEL_OF_CONTROL: dict[str, tuple[int, int, int, int, int]] = {
    "ng_feed":    (0, 0, 0, 0, 6),  # 6 = NG's highest feedback mode (torque)
    "ar_feed":    (0, 0, 3, 3, 3),  # 3 = cascade; doc table says 2s (would forbid it)
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
    "ng_valve":   (0, 1, 1, 1, 1),  # feed valves: closed (0) only in SAFE
    "ar_valve":   (0, 1, 1, 1, 1),
    "o2_valve":   (0, 1, 1, 1, 1),
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
    """The VI's per-state "HERE SPECIFIC CONDITIONS MAY BE SET" case — all
    cases constant TRUE (no plant-feedback guards are implemented). NOT part of
    the post-mortem gate (that is ¬ForceState — resolved 2026-07-07); kept only
    as the hook where real per-state guards would land if ever added."""
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
    # Feed valves clamp against their own rows 13-15 = (0,1,1,1,1): forced
    # closed only in SAFE, requested value passes through elsewhere (verified
    # 2026-07-07 full-res export). Outside SAFE the gas cut comes from the
    # feed-controller mode going to 0, not from this valve boolean.
    p.ng_valve = bool(_cap("ng_valve", int(q.ng_valve), col))
    p.ar_valve = bool(_cap("ar_valve", int(q.ar_valve), col))
    p.o2_valve = bool(_cap("o2_valve", int(q.o2_valve), col))
    return limited


def decide(inputs: StateDecisionInputs) -> StateDecision:
    """One full tick of the StateMachine VI."""
    limits = source_limits(inputs)
    new_state = decide_state(inputs)
    # Pixel-verified 2026-07-07: PostMortemSave = (CURRENT > new) ∧ ¬ForceState
    # — a manually forced drop does not trigger the post-mortem save.
    post_mortem = (new_state < inputs.current_state) and not inputs.force_state
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
