"""Tests for the Phase-E engines: temporal warning rules and setpoint schedule."""

from supervisory.monarch.schedule import ScheduleRow, Scheduler
from supervisory.monarch.temporal_rules import NO_LIMIT, TemporalRule, TemporalRuleEngine


class T:  # minimal telemetry stand-in with a plant dict
    def __init__(self, **plant):
        self.plant = plant


def low_oil_rule(cap=1, for_s=5.0, states=frozenset({1, 2, 3})):
    return TemporalRule(
        name="oil low",
        predicate=lambda tm: tm.plant.get("oil_bar", 99) < 1.0,
        for_s=for_s,
        while_states=states,
        cap_state=cap,
        message="oil low",
    )


# ------------------------------------------------------------ temporal rules

def test_rule_needs_continuous_duration():
    eng = TemporalRuleEngine((low_oil_rule(),))
    assert eng.step(0.0, T(oil_bar=0.5), 2) == (NO_LIMIT, [])
    assert eng.step(3.0, T(oil_bar=0.5), 2) == (NO_LIMIT, [])   # 3 s < 5 s
    cap, alerts = eng.step(5.0, T(oil_bar=0.5), 2)
    assert cap == 1 and alerts == ["oil low: oil low"]


def test_interruption_resets_the_clock():
    eng = TemporalRuleEngine((low_oil_rule(),))
    eng.step(0.0, T(oil_bar=0.5), 2)
    eng.step(3.0, T(oil_bar=5.0), 2)      # recovers: clock resets
    assert eng.step(7.0, T(oil_bar=0.5), 2)[0] == NO_LIMIT  # only 0 s so far
    assert eng.step(12.0, T(oil_bar=0.5), 2)[0] == 1


def test_rule_only_armed_in_declared_states():
    eng = TemporalRuleEngine((low_oil_rule(),))
    eng.step(0.0, T(oil_bar=0.5), 0)      # STAND_BY: not armed
    assert eng.step(10.0, T(oil_bar=0.5), 0)[0] == NO_LIMIT


def test_cap_rule_latches_until_operator_clear():
    eng = TemporalRuleEngine((low_oil_rule(),))
    eng.step(0.0, T(oil_bar=0.5), 2)
    eng.step(6.0, T(oil_bar=0.5), 2)
    assert eng.step(20.0, T(oil_bar=9.0), 2)[0] == 1   # recovered but latched
    eng.operator_clear()
    assert eng.step(21.0, T(oil_bar=9.0), 2)[0] == NO_LIMIT
    assert eng.tripped() == []


def test_alert_only_rule_rearms():
    rule = TemporalRule("watch", lambda tm: tm.plant.get("x", 0) > 1,
                        for_s=2.0, cap_state=None, message="x high")
    eng = TemporalRuleEngine((rule,))
    eng.step(0.0, T(x=2), 2)
    _, alerts = eng.step(2.0, T(x=2), 2)
    assert alerts  # fired once
    assert eng.step(3.0, T(x=2), 2)[1] == []          # no repeat while held
    eng.step(4.0, T(x=0), 2)                          # clears -> re-arms
    eng.step(5.0, T(x=2), 2)
    assert eng.step(7.0, T(x=2), 2)[1]                # fires again


def test_raising_predicate_fails_toward_caution():
    rule = TemporalRule("boom", lambda tm: 1 / 0, for_s=1.0, cap_state=0)
    eng = TemporalRuleEngine((rule,))
    eng.step(0.0, T(), 2)
    assert eng.step(1.0, T(), 2)[0] == 0  # treated as holding -> trips


def test_multiple_rules_min_cap_wins():
    eng = TemporalRuleEngine((
        low_oil_rule(cap=1, for_s=1.0),
        TemporalRule("vent", lambda tm: tm.plant.get("p", 0) > 9,
                     for_s=1.0, cap_state=-1),
    ))
    eng.step(0.0, T(oil_bar=0.5, p=10), 2)
    cap, _ = eng.step(1.0, T(oil_bar=0.5, p=10), 2)
    assert cap == -1


# ---------------------------------------------------------------- scheduler

class Intent:
    def __init__(self):
        self.values = {}


def setter(key, value):
    def change(intent):
        intent.values[key] = value
    return change


def make_scheduler():
    return Scheduler(rows=(
        ScheduleRow("idle-low", state=2, speed_min=0, speed_max=1000,
                    changes=(setter("dyno_ref", 900),)),
        ScheduleRow("idle-high", state=2, speed_min=1000, speed_max=3000,
                    changes=(setter("dyno_ref", 1800),)),
    ))


def test_row_applied_once_on_entry():
    sch = make_scheduler()
    intent = Intent()
    for ch in sch.step(2, 900):
        ch(intent)
    assert intent.values == {"dyno_ref": 900}
    assert sch.step(2, 900) == []          # steady state: no re-assert
    assert sch.applied_log == ["idle-low"]


def test_op_point_change_applies_new_row():
    sch = make_scheduler()
    intent = Intent()
    for ch in sch.step(2, 900):
        ch(intent)
    for ch in sch.step(2, 1800):
        ch(intent)
    assert intent.values["dyno_ref"] == 1800
    assert sch.applied_log == ["idle-low", "idle-high"]


def test_manual_override_not_fought():
    sch = make_scheduler()
    intent = Intent()
    for ch in sch.step(2, 900):
        ch(intent)
    intent.values["dyno_ref"] = 950        # operator touches it
    sch.manual_override()
    assert sch.step(2, 900) == []          # same op-point: scheduler yields
    assert intent.values["dyno_ref"] == 950
    for ch in sch.step(2, 1800):           # op-point change re-arms
        ch(intent)
    assert intent.values["dyno_ref"] == 1800


def test_no_matching_row_is_a_noop():
    sch = make_scheduler()
    assert sch.step(3, 900) == []          # FIRING has no rows in this table
    assert sch.applied_log == []
