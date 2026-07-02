from supervisory.messages import Command
from supervisory.sim import SimPlant


def cmd(cmd_id, name, **params):
    return Command(id=cmd_id, name=name, params=params)


def test_start_requires_idle():
    p = SimPlant()
    assert p.handle_command(cmd(1, "start")).accepted
    assert p.mode == "RUNNING"
    assert not p.handle_command(cmd(2, "start")).accepted  # already running


def test_start_rejected_on_interlock():
    p = SimPlant()
    p.interlock_ok = False
    ack = p.handle_command(cmd(1, "start"))
    assert not ack.accepted
    assert "interlock" in ack.reason


def test_setpoint_validation():
    p = SimPlant()
    assert p.handle_command(cmd(1, "set_setpoint", value=80.0)).accepted
    assert p.setpoint_c == 80.0
    assert not p.handle_command(cmd(2, "set_setpoint", value=999.0)).accepted
    assert not p.handle_command(cmd(3, "set_setpoint")).accepted  # missing value


def test_unknown_command_nacked():
    assert not SimPlant().handle_command(cmd(1, "warp_drive")).accepted


def test_watchdog_safe_hold_and_reset():
    p = SimPlant()
    p.handle_command(cmd(1, "start"))
    p.tick(6.0)  # heartbeat silence longer than the 5 s watchdog
    assert p.mode == "SAFE_HOLD"
    assert not p.handle_command(cmd(2, "start")).accepted  # held: only reset allowed
    assert p.handle_command(cmd(3, "reset")).accepted
    assert p.mode == "IDLE"


def test_heartbeat_keeps_watchdog_happy():
    p = SimPlant()
    for _ in range(10):
        p.heartbeat()
        p.tick(1.0)
    assert p.mode == "IDLE"


def test_interlock_trip_forces_safe_hold_and_blocks_reset():
    p = SimPlant()
    p.handle_command(cmd(1, "start"))
    p.interlock_ok = False
    p.heartbeat()
    p.tick(1.0)
    assert p.mode == "SAFE_HOLD"
    assert not p.handle_command(cmd(2, "reset")).accepted  # interlock still tripped
