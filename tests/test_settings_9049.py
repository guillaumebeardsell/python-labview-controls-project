"""Tests for the 9049_ControlSettings model (wire layout confirmed from the
2026-07-07 ControlSettingsRaster block-diagram print)."""

from supervisory.monarch.settings_9049 import Settings9049
from supervisory.monarch import SystemState


def test_round_trip():
    s = Settings9049(system_state=SystemState.IDLING, spark_enable=True,
                     spark_timing_cadbtdc=22.5, engine_speed_rpm=900.0)
    assert Settings9049.model_validate_json(s.model_dump_json()) == s


def test_unknown_fields_ignored():
    s = Settings9049.model_validate({"system_state": 1, "future": 42})
    assert s.system_state is SystemState.MOTORING


def test_array_round_trip():
    raw = [2.0, 1.0, 1.0, 2.5, 12.0, 1.0, 22.5, 900.0]
    s = Settings9049.from_array(raw)
    assert s.system_state is SystemState.IDLING
    assert s.inj_enable and s.main_enable and s.spark_enable
    assert s.main_duration_ms == 2.5
    assert s.main_soi_cadbtdc == 12.0
    assert s.spark_timing_cadbtdc == 22.5
    assert s.engine_speed_rpm == 900.0
    assert s.to_array() == raw


def test_enable_gate_consistency_check():
    ok = Settings9049(system_state=SystemState.IDLING, spark_enable=True)
    assert ok.consistent_with_state()
    bad = Settings9049(system_state=SystemState.MOTORING, spark_enable=True)
    assert not bad.consistent_with_state()  # spark enabled below IDLING = violation
    idle = Settings9049(system_state=SystemState.STAND_BY)
    assert idle.consistent_with_state()
