"""Tests for the APC_9056_WarningIntegration port (Phase A3)."""

from supervisory.monarch.state_machine import StateDecisionInputs, decide_state
from supervisory.monarch import ControlSettings
from supervisory.monarch.warning_policy import (
    ChannelLimits,
    HeartbeatStallDetector,
    LEVEL_TO_STATE_LIMIT,
    WarningPolicy,
    level_to_state_limit,
)


# ----------------------------------------------------------- level mapping

def test_level_to_state_limit_matches_vi_cases():
    # d2-d5 frames: 1->3, 2->2, 3->1, 4->-1; "0, Default" -> 3
    assert LEVEL_TO_STATE_LIMIT == {0: 3, 1: 3, 2: 2, 3: 1, 4: -1}
    assert level_to_state_limit(0) == 3
    assert level_to_state_limit(4) == -1
    assert level_to_state_limit(99) == 3  # unknown level takes the Default case


# ------------------------------------------------------------ fresh levels

def high_channel(t1=10, t2=20, t3=30, t4=40, **kw):
    return ChannelLimits(thresholds=(t1, t2, t3, t4), sign=1, **kw)


def test_fresh_level_high_limits():
    ch = high_channel()
    assert ch.fresh_level(5) == 0
    assert ch.fresh_level(15) == 1
    assert ch.fresh_level(25) == 2
    assert ch.fresh_level(35) == 3
    assert ch.fresh_level(45) == 4


def test_fresh_level_low_limits_via_sign():
    # sign=-1 warns when value drops BELOW the thresholds
    ch = ChannelLimits(thresholds=(40, 30, 20, 10), sign=-1)
    assert ch.fresh_level(50) == 0
    assert ch.fresh_level(35) == 1
    assert ch.fresh_level(25) == 2
    assert ch.fresh_level(15) == 3
    assert ch.fresh_level(5) == 4


def test_fresh_level_respects_enable_flags():
    ch = ChannelLimits(thresholds=(10, 20, 30, 40), sign=1,
                       enabled=(True, False, True, False))
    assert ch.fresh_level(25) == 1   # level 2 disabled -> stays at 1
    assert ch.fresh_level(35) == 3
    assert ch.fresh_level(45) == 3   # level 4 disabled


# ---------------------------------------------------------------- latching

def make_policy():
    return WarningPolicy(channels={"oil_p": high_channel()})


def test_soft_warning_self_clears():
    p = make_policy()
    assert p.step({"oil_p": 15}) == 3   # level 1 -> no restriction
    assert p.max_level() == 1
    assert p.step({"oil_p": 5}) == 3    # back in range: soft clears
    assert p.max_level() == 0


def test_level2_latches_until_operator_clear():
    p = make_policy()
    assert p.step({"oil_p": 25}) == 2   # level 2 -> cap IDLING
    assert p.step({"oil_p": 5}) == 2    # value recovered, latch holds
    assert p.step({"oil_p": 5}, operator_clear=True) == 3
    assert p.max_level() == 0


def test_operator_clear_repopulates_if_still_tripped():
    p = make_policy()
    p.step({"oil_p": 45})               # level 4
    limit = p.step({"oil_p": 45}, operator_clear=True)
    assert limit == -1                   # cleared, but still tripped -> re-latches
    assert p.max_level() == 4


def test_latch_ratchets_up_not_down():
    p = make_policy()
    p.step({"oil_p": 25})   # 2
    p.step({"oil_p": 45})   # 4
    p.step({"oil_p": 25})   # back to 2 instantaneous
    assert p.max_level() == 4  # latch holds the worst


def test_aggregation_takes_worst_channel():
    p = WarningPolicy(channels={
        "a": high_channel(),
        "b": ChannelLimits(thresholds=(1, 2, 3, 4), sign=1),
    })
    assert p.step({"a": 15, "b": 3.5}) == 1  # a: level1, b: level3 -> motoring cap


def test_extra_levels_latch_and_aggregate():
    p = WarningPolicy()
    assert p.step({}, extra_levels={"cyl_knock": 4}) == -1
    assert p.step({}, extra_levels={"cyl_knock": 0}) == -1  # latched
    assert p.step({}, extra_levels={"cyl_knock": 0}, operator_clear=True) == 3


def test_missing_channel_value_keeps_latch():
    p = make_policy()
    p.step({"oil_p": 25})
    assert p.step({}) == 2  # no new sample: latch unchanged


# --------------------------------------------------- end-to-end with the SM

def test_policy_feeds_state_machine():
    p = make_policy()
    limit = p.step({"oil_p": 35})  # level 3 -> cap MOTORING
    state = decide_state(StateDecisionInputs(
        current_state=3,
        settings=ControlSettings(requested_mode=3),
        warnings_limit=limit,
    ))
    assert state == 1  # FIRING knocked down to MOTORING by the warning


# ------------------------------------------------------- heartbeat detector

def test_heartbeat_stall_detector_matches_vi_counter():
    d = HeartbeatStallDetector(threshold=3)
    assert d.update(1.0) is False
    assert d.update(2.0) is False  # changing -> counter resets
    assert d.update(2.0) is False  # 1
    assert d.update(2.0) is False  # 2
    assert d.update(2.0) is True   # 3 -> stalled
    assert d.update(3.0) is False  # change resets
