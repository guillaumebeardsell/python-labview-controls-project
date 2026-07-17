"""Tests for the operator CLI's state-ladder guard (examples/monarch_operate.py).

The 9056 StateMachine rate-limits upward transitions to +1 per step, so the
CLI refuses >+1 upward mode requests with an explicit message instead of
letting the plant silently clamp the state below what was asked.
"""

import pytest
from pydantic import ValidationError

from examples.monarch_operate import MODE_WORDS, MODES, ladder_refusal, set_path
from supervisory.monarch.control_settings import ControlSettings, SystemState


class _StubCommander:
    def __init__(self):
        self.intent = ControlSettings()

    def modify(self, fn):
        fn(self.intent)


class _StubSession:
    def __init__(self):
        self.commander = _StubCommander()


def test_upward_jump_is_refused_with_next_step_named():
    msg = ladder_refusal(int(SystemState.STAND_BY), SystemState.IDLING)
    assert msg is not None and msg.startswith("REFUSED")
    assert "mode motoring" in msg  # the step to request instead


def test_bigger_jump_from_safe_is_refused():
    msg = ladder_refusal(int(SystemState.SAFE), SystemState.FIRING)
    assert msg is not None and "mode standby" in msg


def test_plus_one_upward_is_allowed():
    assert ladder_refusal(int(SystemState.STAND_BY), SystemState.MOTORING) is None
    assert ladder_refusal(int(SystemState.IDLING), SystemState.FIRING) is None


def test_same_state_and_downward_always_pass():
    assert ladder_refusal(int(SystemState.IDLING), SystemState.IDLING) is None
    assert ladder_refusal(int(SystemState.FIRING), SystemState.SAFE) is None
    assert ladder_refusal(int(SystemState.MOTORING), SystemState.STAND_BY) is None


def test_unknown_current_state_passes_through():
    # LabVIEW enforces the ladder regardless; without telemetry the CLI
    # does not second-guess the request.
    assert ladder_refusal(None, SystemState.FIRING) is None


def test_mode_words_cover_every_state():
    assert set(MODE_WORDS) == set(MODES.values())


# ---- set_path validation: a bad value must never poison the intent --------

def test_set_path_coerces_uppercase_booleans():
    # `set ign_enable FALSE` poisoned the intent live on 2026-07-16 — the
    # string "FALSE" landed in a bool field and every 1 Hz emit NACKed.
    s = _StubSession()
    set_path(s, "ign_enable", "FALSE")
    assert s.commander.intent.ign_enable is False
    set_path(s, "ign_enable", "TRUE")
    assert s.commander.intent.ign_enable is True


def test_set_path_coerces_numeric_strings():
    s = _StubSession()
    out = set_path(s, "spark_advance_cadbtdc", "20")
    assert s.commander.intent.spark_advance_cadbtdc == 20.0
    assert "20" in out


def test_set_path_rejects_garbage_without_mutating():
    s = _StubSession()
    with pytest.raises(ValidationError):
        set_path(s, "ign_enable", "Falze")
    assert s.commander.intent.ign_enable is False  # untouched default


def test_set_path_validates_list_fields():
    s = _StubSession()
    set_path(s, "activate_cylinder", "[true,false,true,false,true,false]")
    assert s.commander.intent.activate_cylinder == [True, False, True,
                                                    False, True, False]
    with pytest.raises(ValidationError):
        set_path(s, "activate_cylinder", '["notabool",1,1,1,1,1]')


def test_set_path_unknown_field_still_raises():
    s = _StubSession()
    with pytest.raises(AttributeError):
        set_path(s, "no_such_field", "1")
