"""Round-trip and structural tests for the MONARCH ControlSettings contract.

These validate the serialization *mechanism* on the real, deeply-nested cluster
shape (nested models, arrays of bool/float/int, an I8 enum) — the same mechanism
every future MONARCH port reuses.
"""

import json

from supervisory.monarch import ControlSettings, SystemState
from supervisory.monarch.control_settings import NgChannel, PidControlReferences


def test_defaults_construct():
    cs = ControlSettings()
    assert cs.speed_ref == 1800.0
    assert cs.requested_mode is SystemState.STAND_BY
    assert len(cs.activate_cylinder) == 6
    assert len(cs.pid_control_references.mtr_modbus_floats) == 19
    assert len(cs.pid_control_references.mtr_modbus_u16) == 6


def test_round_trip_defaults():
    cs = ControlSettings()
    assert ControlSettings.model_validate_json(cs.model_dump_json()) == cs


def test_round_trip_populated():
    cs = ControlSettings(
        spark_advance_cadbtdc=22.5,
        imep_ref=8.0,
        speed_ref=2000.0,
        ign_enable=True,
        di_enable=True,
        activate_cylinder=[True, True, False, True, False, False],
        force_motoring=True,
        requested_mode=SystemState.FIRING,
        lambda_ref=1.05,
        ca50_setpoint_cadatdc=8.0,
        ca50_control=True,
        emergency_stop=False,
        pid_control_references=PidControlReferences(
            intake_vent=True,  # 1 = closed
            ng=NgChannel(mode=6, ng_fc_001_ref=3.2, imep_ref=8.0, nm_ref=120.0),
            o2_ff_ng=True,
            mtr_modbus_floats=[float(i) for i in range(19)],
            mtr_modbus_u16=[i for i in range(6)],
            mtr_hb=True,
            pc_hb=True,
        ),
    )
    restored = ControlSettings.model_validate_json(cs.model_dump_json())
    assert restored == cs
    # spot-check nested values survive the round trip
    assert restored.pid_control_references.ng.mode == 6
    assert restored.requested_mode is SystemState.FIRING


def test_serializes_to_single_json_line():
    # The transport frames messages by LF, so a payload must not contain newlines.
    payload = ControlSettings().model_dump_json()
    assert "\n" not in payload


def test_enum_serializes_as_int():
    cs = ControlSettings(requested_mode=SystemState.SAFE)
    obj = json.loads(cs.model_dump_json())
    assert obj["requested_mode"] == -1  # I8 wire value, not the name


def test_unknown_fields_ignored():
    # Forward compatibility (ICD section 3): a future field must not break parsing.
    raw = json.loads(ControlSettings().model_dump_json())
    raw["some_future_field"] = 123
    cs = ControlSettings.model_validate(raw)
    assert cs.speed_ref == 1800.0
