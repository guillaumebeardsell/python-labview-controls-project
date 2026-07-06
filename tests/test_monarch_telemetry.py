"""Tests for MONARCH telemetry ingestion: raw-flatten <-> model, the envelope
parser, and the link parser's fallback."""

import json
import pathlib

from supervisory.messages import CommandAck, Heartbeat
from supervisory.monarch import (
    ControlSettings,
    MonarchTelemetry,
    SystemState,
    control_settings_from_labview,
    monarch_parser,
)
from supervisory.monarch.control_settings import NgChannel, PidControlReferences
from supervisory.monarch.labview_mapping import control_settings_to_labview

CAPTURE = (
    pathlib.Path(__file__).parent.parent
    / "original-labview-codebase"
    / "control_settings_flatten.txt"
)


def test_model_to_labview_round_trips():
    cs = ControlSettings(
        spark_advance_cadbtdc=18.0,
        speed_ref=2100.0,
        requested_mode=SystemState.FIRING,
        ign_enable=True,
        activate_cylinder=[True, False, True, True, False, True],
        pid_control_references=PidControlReferences(
            intake_vent=True,
            ng=NgChannel(mode=6, ng_fc_001_ref=2.5, nm_ref=95.0),
            mtr_modbus_u16=[1, 2, 3, 4, 5, 6, 7],
        ),
    )
    lv = control_settings_to_labview(cs)
    # realistic shape: PID references nested under their LabVIEW label
    assert "PID control references" in lv
    assert "Spark advance [CADBTDC]" in lv
    back, unmapped = control_settings_from_labview(lv)
    assert not unmapped
    assert back == cs


def test_from_real_capture():
    lv = json.loads(CAPTURE.read_text(encoding="utf-8-sig"))
    cs, unmapped = control_settings_from_labview(lv)
    assert not unmapped
    assert cs.di_advance_cadbtdc == 160.0
    assert cs.speed_ref == 900.0
    assert cs.requested_mode is SystemState.SAFE
    assert cs.activate_cylinder == [True] * 6
    assert len(cs.pid_control_references.mtr_modbus_u16) == 7
    assert cs.pid_control_references.ng.mode == 1


def _envelope(cs: ControlSettings, seq=1, state=SystemState.IDLING) -> str:
    return json.dumps({
        "type": "telemetry", "seq": seq, "ts": 123.0,
        "system_state": int(state), "settings": control_settings_to_labview(cs),
    })


def test_monarch_parser_decodes_telemetry():
    cs = ControlSettings(speed_ref=1500.0, requested_mode=SystemState.MOTORING)
    msg = monarch_parser(_envelope(cs, seq=7, state=SystemState.MOTORING))
    assert isinstance(msg, MonarchTelemetry)
    assert msg.seq == 7
    assert msg.system_state is SystemState.MOTORING
    assert msg.settings.speed_ref == 1500.0
    assert msg.unmapped == ()


def test_stage1_envelope_leaves_stage2_fields_none():
    # A Stage-1 gateway sends only system_state + settings.
    msg = monarch_parser(_envelope(ControlSettings()))
    assert msg.warnings_limit is None
    assert msg.manual_state is None
    assert msg.force_state is None
    assert msg.limited_settings is None


def test_full_stage2_envelope_decodes():
    requested = ControlSettings(requested_mode=SystemState.FIRING, ign_enable=True)
    requested.pid_control_references.ng.mode = 6
    limited = requested.model_copy(deep=True)
    limited.ign_enable = False  # what the limiter allowed
    env = json.dumps({
        "type": "telemetry", "seq": 3, "ts": 1.0,
        "system_state": int(SystemState.IDLING),  # decided != requested
        "warnings_limit": int(SystemState.IDLING),
        "manual_state": -128,
        "force_state": False,
        "settings": control_settings_to_labview(requested),
        "limited_settings": control_settings_to_labview(limited),
    })
    msg = monarch_parser(env)
    assert msg.system_state is SystemState.IDLING
    assert msg.settings.requested_mode is SystemState.FIRING       # requested
    assert msg.warnings_limit == int(SystemState.IDLING)
    assert msg.force_state is False
    assert msg.limited_settings is not None
    assert msg.settings.ign_enable is True and msg.limited_settings.ign_enable is False
    assert msg.unmapped == ()


def test_limited_settings_unmapped_is_prefixed():
    lv = control_settings_to_labview(ControlSettings())
    bad = control_settings_to_labview(ControlSettings())
    bad["Mystery Limited Field"] = 1
    env = json.dumps({"type": "telemetry", "seq": 1, "ts": 0.0, "system_state": 0,
                      "settings": lv, "limited_settings": bad})
    msg = monarch_parser(env)
    assert any(u.startswith("limited_settings/") for u in msg.unmapped)


def test_monarch_telemetry_survives_recorder_dump():
    # the JSONL recorder calls model_dump(); it must serialize the nested model
    cs = ControlSettings(requested_mode=SystemState.FIRING)
    msg = monarch_parser(_envelope(cs))
    obj = msg.model_dump()
    assert obj["settings"]["requested_mode"] == 3
    assert obj["system_state"] == 2


def test_monarch_parser_falls_back_for_other_types():
    ack = monarch_parser('{"type":"command_ack","id":4,"accepted":false,"reason":"nope"}')
    assert isinstance(ack, CommandAck) and ack.id == 4
    hb = monarch_parser('{"type":"heartbeat","seq":2,"ts":1.0}')
    assert isinstance(hb, Heartbeat)


def test_unknown_settings_label_reported_not_fatal():
    cs = ControlSettings()
    lv = control_settings_to_labview(cs)
    lv["Some Future Field"] = 42
    env = json.dumps({"type": "telemetry", "seq": 1, "ts": 0.0,
                      "system_state": 0, "settings": lv})
    msg = monarch_parser(env)
    assert isinstance(msg, MonarchTelemetry)
    assert "Some Future Field" in msg.unmapped  # surfaced, not crashed
