"""Test matrix for the APC_9056_StateMachine port.

Two layers: an exhaustive sweep asserting the spec formula (MIN over limitation
sources, step-by-1, absolute ManualState override) over every input
combination, and directed hand-computed cases pinning concrete behaviors —
including the safety-relevant ones (SAFE reachable in one step, the combustion
invariant, vent polarity, the DisregardWarnings bypass).
"""

import itertools

import pytest

from supervisory.monarch import ControlSettings, SystemState
from supervisory.monarch.state_machine import (
    MAX_LEVEL_OF_CONTROL,
    NO_LIMIT,
    StateDecisionInputs,
    decide,
    decide_state,
    limit_settings,
    max_levels_for_state,
    source_limits,
)

STATES = [-1, 0, 1, 2, 3]


def make_settings(requested=0, estop=False, f_mot=False, f_idl=False, **kwargs):
    cs = ControlSettings(
        requested_mode=requested,
        emergency_stop=estop,
        force_motoring=f_mot,
        force_idling=f_idl,
        **kwargs,
    )
    return cs


def make_inputs(current=0, requested=0, warnings=NO_LIMIT, estop=False,
                f_mot=False, f_idl=False, force=False, manual=0, disregard=False):
    return StateDecisionInputs(
        current_state=current,
        settings=make_settings(requested, estop, f_mot, f_idl),
        warnings_limit=warnings,
        force_state=force,
        manual_state=manual,
        disregard_warnings=disregard,
    )


# ---------------------------------------------------------------- exhaustive

def test_exhaustive_arbitration_sweep():
    """Every combination of current x requested x warnings x overrides x force:
    the output must equal the spec formula (MIN incl. step-up; ManualState
    absolute when forced). ~30k cases."""
    count = 0
    for current, requested, warnings in itertools.product(STATES, STATES, STATES):
        for estop, f_mot, f_idl in itertools.product([False, True], repeat=3):
            for force, manual in [(False, 0), (True, -1), (True, 0), (True, 3)]:
                inputs = make_inputs(current, requested, warnings,
                                     estop, f_mot, f_idl, force, manual)
                got = decide_state(inputs)
                if force:
                    expected = manual
                else:
                    expected = min(
                        requested,
                        warnings,
                        -1 if estop else NO_LIMIT,
                        1 if f_mot else NO_LIMIT,
                        2 if f_idl else NO_LIMIT,
                        current + 1,
                    )
                assert got == expected, (
                    f"current={current} req={requested} warn={warnings} "
                    f"estop={estop} f_mot={f_mot} f_idl={f_idl} "
                    f"force={force} manual={manual}: got {got}, want {expected}"
                )
                count += 1
    assert count == 5 * 5 * 5 * 8 * 4


def test_sweep_invariants_without_force():
    """Independently of the formula: the state never exceeds any active limit
    and never climbs more than one step."""
    for current, requested, warnings in itertools.product(STATES, STATES, STATES):
        for estop, f_mot, f_idl in itertools.product([False, True], repeat=3):
            inputs = make_inputs(current, requested, warnings, estop, f_mot, f_idl)
            got = decide_state(inputs)
            assert got <= requested
            assert got <= warnings
            assert got <= current + 1
            if estop:
                assert got == -1  # e-stop always wins outright
            if f_mot:
                assert got <= 1
            if f_idl:
                assert got <= 2


# ------------------------------------------------------------------ directed

@pytest.mark.parametrize("current,requested,expected", [
    (0, 3, 1),   # step-up limited to +1
    (1, 3, 2),
    (2, 3, 3),
    (3, 3, 3),
    (3, 0, 0),   # decreases are immediate (no step limit down)
    (3, -1, -1), # SAFE reachable in one step from FIRING
    (-1, 3, 0),  # climbing out of SAFE: one step at a time
])
def test_step_rule(current, requested, expected):
    assert decide_state(make_inputs(current, requested)) == expected


def test_walk_up_takes_exactly_four_ticks():
    state = 0
    trace = []
    for _ in range(6):
        state = decide_state(make_inputs(current=state, requested=3))
        trace.append(state)
    assert trace == [1, 2, 3, 3, 3, 3]


def test_estop_beats_everything_including_requested_firing():
    assert decide_state(make_inputs(current=3, requested=3, estop=True)) == -1


def test_estop_vs_forcestate():
    # ForceState is wired directly to the output — it overrides even e-stop.
    # (LabVIEW wiring: the ManualState case output goes straight to SYSTEM
    # STATE.) Safety-relevant: documented in the shadow report.
    inputs = make_inputs(current=0, requested=0, estop=True, force=True, manual=2)
    assert decide_state(inputs) == 2


def test_forcestate_bypasses_step_rule():
    assert decide_state(make_inputs(current=0, force=True, manual=3)) == 3


def test_warnings_clamp_forces_step_down():
    # running at FIRING, warnings drop the permitted max to MOTORING
    assert decide_state(make_inputs(current=3, requested=3, warnings=1)) == 1


def test_post_mortem_on_forced_downward_transition():
    d = decide(make_inputs(current=3, requested=3, estop=True))
    assert d.system_state == -1
    assert d.post_mortem is True
    d2 = decide(make_inputs(current=0, requested=3))
    assert d2.post_mortem is False  # upward transition
    # ForceState-driven drops do NOT post-mortem (gate is ¬ForceState,
    # pixel-verified 2026-07-07)
    d3 = decide(make_inputs(current=3, requested=3, force=True, manual=-1))
    assert d3.system_state == -1
    assert d3.post_mortem is False


def test_source_limits_reported():
    lims = source_limits(make_inputs(current=1, requested=3, warnings=2, f_idl=True))
    assert lims == {"requested": 3, "warnings": 2, "estop": 3,
                    "force_motoring": 3, "force_idling": 2, "step_up": 2}


# ------------------------------------------------------------------- limiter

def _maxed_settings():
    """A request asking for everything: all modes high, all booleans set."""
    cs = ControlSettings(requested_mode=3, ign_enable=True, di_enable=True)
    p = cs.pid_control_references
    p.ng.mode = 6
    p.o2.mode = p.dyno.mode = p.membrane.mode = 2
    p.tcoolant.mode = 2
    p.ar.mode = p.texh.mode = p.toil.mode = 3  # saturate the 3-capped rows
    p.intake_vent = p.cross_vent = p.exhaust_vent = True  # closed
    p.ng_valve = p.ar_valve = p.o2_valve = True  # open
    return cs


@pytest.mark.parametrize("state,col", [(-1, 0), (0, 1), (1, 2), (2, 3), (3, 4)])
def test_limiter_matches_table_when_everything_requested(state, col):
    lim = limit_settings(_maxed_settings(), state)
    p = lim.pid_control_references
    T = MAX_LEVEL_OF_CONTROL
    assert p.ng.mode == T["ng_feed"][col]
    assert p.ar.mode == T["ar_feed"][col]
    assert p.o2.mode == T["o2_feed"][col]
    assert p.tcoolant.mode == T["cool_temp"][col]
    assert p.texh.mode == T["exh_temp"][col]
    assert p.toil.mode == T["oil_temp"][col]
    assert p.intake_vent == bool(T["int_vent"][col])
    assert p.cross_vent == bool(T["cross_vent"][col])
    assert p.exhaust_vent == bool(T["exh_vent"][col])
    assert p.dyno.mode == T["dyno"][col]
    assert p.membrane.mode == T["mtr"][col]
    assert lim.ign_enable == bool(T["ign"][col])
    assert lim.di_enable == bool(T["di"][col])
    # feed valves have their own vent-style rows (closed only in SAFE)
    assert p.ng_valve == bool(min(1, T["ng_valve"][col]))
    assert p.ar_valve == bool(min(1, T["ar_valve"][col]))
    assert p.o2_valve == bool(min(1, T["o2_valve"][col]))


def test_safe_state_forces_safe_positions():
    lim = limit_settings(_maxed_settings(), -1)
    p = lim.pid_control_references
    # vents open (False = open), feeds closed, IGN/DI off, dyno stopped
    assert not p.intake_vent and not p.cross_vent and not p.exhaust_vent
    assert not p.ng_valve and not p.ar_valve and not p.o2_valve
    assert p.ng.mode == 0 and p.ar.mode == 0 and p.o2.mode == 0
    assert not lim.ign_enable and not lim.di_enable
    assert p.dyno.mode == 0
    # thermal loops stay allowed at level 1 (their safe action is max flow)
    assert p.tcoolant.mode == 1 and p.texh.mode == 1 and p.toil.mode == 1


def test_combustion_invariant_leaving_firing():
    """Discontinuing combustion must also cut NG and O2 (the report's hard
    rule). As-built, dropping out of FIRING zeroes the NG/O2 feed-controller
    MODES in the same tick (flow refs -> 0); the shutoff-valve booleans are
    only forced closed in SAFE (their rows are 0,1,1,1,1 — verified
    2026-07-07), so the cut comes from the controllers, not the valves."""
    d = decide(make_inputs(current=3, requested=0))
    assert d.system_state == 0
    p = d.limited_settings.pid_control_references
    # request still asks for gas; the limiter must cut the controller modes
    assert p.ng.mode == 0 and p.o2.mode == 0
    # valves pass through in STAND_BY (as-built); only SAFE forces them shut
    d_safe = decide(make_inputs(current=3, requested=-1))
    p_safe = d_safe.limited_settings.pid_control_references
    assert not p_safe.ng_valve and not p_safe.o2_valve


def test_min_never_raises_a_request():
    """The limiter only lowers: a default (all-zero/False) request passes
    through unchanged in every state."""
    cs = ControlSettings()
    for state in STATES:
        lim = limit_settings(cs, state)
        assert lim == cs


def test_disregard_warnings_bypasses_all_caps():
    cs = _maxed_settings()
    lim = limit_settings(cs, -1, disregard_warnings=True)
    assert lim == cs  # nothing clamped, even in SAFE


def test_non_mode_fields_pass_through():
    cs = _maxed_settings()
    cs.spark_advance_cadbtdc = 22.5
    cs.speed_ref = 1800.0
    cs.lambda_ref = 1.05
    lim = limit_settings(cs, -1)
    assert lim.spark_advance_cadbtdc == 22.5
    assert lim.speed_ref == 1800.0
    assert lim.lambda_ref == 1.05


def test_out_of_range_state_degrades_to_all_safe():
    # LabVIEW Index Array returns the default element out of range -> caps 0
    lim = limit_settings(_maxed_settings(), -128)
    p = lim.pid_control_references
    assert p.ng.mode == 0 and lim.ign_enable is False and p.intake_vent is False
    assert max_levels_for_state(-128) == {k: 0 for k in MAX_LEVEL_OF_CONTROL}


def test_max_levels_row():
    assert max_levels_for_state(3)["ng_feed"] == 6  # the as-built table value
    assert max_levels_for_state(0)["cool_temp"] == 2
