import pytest
from pydantic import ValidationError

from supervisory.messages import Command, CommandAck, Heartbeat, Telemetry, dump, parse


def test_round_trip_all_types():
    msgs = [
        Telemetry(seq=1, ts=123.5, mode="IDLE", channels={"temp_c": 1.5}, flags={"ok": True}),
        Command(id=7, name="set_setpoint", params={"value": 80.0, "ramp": True, "profile": "fast"}),
        CommandAck(id=7, accepted=False, reason="interlock not OK"),
        Heartbeat(seq=3, ts=99.0),
    ]
    for msg in msgs:
        assert parse(dump(msg)) == msg


def test_unknown_fields_ignored():
    line = '{"type": "telemetry", "seq": 1, "ts": 0.0, "mode": "IDLE", "future_field": 42}'
    tm = parse(line)
    assert tm.mode == "IDLE"


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        parse('{"type": "mystery", "seq": 1}')


def test_malformed_json_rejected():
    with pytest.raises(ValidationError):
        parse("this is not json")


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        parse('{"type": "command", "name": "start"}')  # no id
