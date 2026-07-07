"""Tests for the (doc-transcribed) 9049_ControlSettings model."""

from supervisory.monarch.settings_9049 import Settings9049
from supervisory.monarch import SystemState


def test_round_trip():
    s = Settings9049(system_state=SystemState.IDLING, spark_enable=True,
                     spark_timing_cadbtdc=22.5, engine_speed_rpm=900.0)
    assert Settings9049.model_validate_json(s.model_dump_json()) == s


def test_unknown_fields_ignored():
    s = Settings9049.model_validate({"system_state": 1, "future": 42})
    assert s.system_state is SystemState.MOTORING


def test_enable_gate_consistency_check():
    ok = Settings9049(system_state=SystemState.IDLING, spark_enable=True)
    assert ok.consistent_with_state()
    bad = Settings9049(system_state=SystemState.MOTORING, spark_enable=True)
    assert not bad.consistent_with_state()  # spark enabled below IDLING = violation
    idle = Settings9049(system_state=SystemState.STAND_BY)
    assert idle.consistent_with_state()
