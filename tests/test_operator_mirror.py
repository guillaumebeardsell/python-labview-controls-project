"""Tests for ICD §7.8 operator-request mirroring: the UI stays the operator's
input surface while Python holds authority."""

from supervisory.engine import Supervisor
from supervisory.monarch.commander import MonarchCommander
from supervisory.monarch.control_settings import ControlSettings, SystemState
from supervisory.monarch.operator_mirror import OperatorRequestMirror
from supervisory.monarch.sequences import SequenceExecutor, venting
from supervisory.monarch.simserver_monarch import MonarchGatewaySim, MonarchSimLink
from supervisory.sequencing import Status


def make_stack():
    link = MonarchSimLink(MonarchGatewaySim(source="PYTHON"))
    commander = MonarchCommander()
    executor = SequenceExecutor(commander)
    mirror = OperatorRequestMirror(commander, executor)
    sup = Supervisor(link, [mirror, executor, commander])
    return link, commander, executor, mirror, sup


def run_ticks(link, sup, n, t0=0.0, dt=1.0):
    t = t0
    for _ in range(n):
        link.advance(dt)
        t += dt
        sup.tick(t)
    return t


def ui_request(**overrides) -> ControlSettings:
    cs = ControlSettings()
    for key, value in overrides.items():
        setattr(cs, key, value)
    return cs


def test_operator_mode_request_flows_through_python():
    """Operator asks for MOTORING on the UI while Python drives: the request
    mirrors into Python's intent, the command carries it, the plant steps up."""
    link, commander, executor, mirror, sup = make_stack()
    t = run_ticks(link, sup, 2)  # authority + seed
    link.sim.ui_write(ui_request(requested_mode=SystemState.MOTORING))
    run_ticks(link, sup, 4, t0=t)
    assert mirror.mirrored_count > 0
    assert commander.intent.requested_mode == SystemState.MOTORING
    assert link.sim.current_state == int(SystemState.MOTORING)


def test_operator_speed_change_flows_through():
    link, commander, executor, mirror, sup = make_stack()
    t = run_ticks(link, sup, 2)
    link.sim.ui_write(ui_request(speed_ref=900.0))
    run_ticks(link, sup, 3, t0=t)
    assert link.sim.requested.speed_ref == 900.0


def test_estop_is_set_only_through_mirror():
    link, commander, executor, mirror, sup = make_stack()
    t = run_ticks(link, sup, 2)
    link.sim.ui_write(ui_request(emergency_stop=True))
    t = run_ticks(link, sup, 3, t0=t)
    assert commander.intent.emergency_stop is True
    assert link.sim.current_state == int(SystemState.SAFE)
    # operator releases the button: mirroring False must NOT clear the latch
    link.sim.ui_write(ui_request(emergency_stop=False))
    run_ticks(link, sup, 3, t0=t)
    assert commander.intent.emergency_stop is True  # still set in the intent
    assert link.sim.current_state == int(SystemState.SAFE)


def test_clear_estop_never_mirrors():
    link, commander, executor, mirror, sup = make_stack()
    t = run_ticks(link, sup, 2)
    link.sim.ui_write(ui_request(clear_emergency_stop=True))
    run_ticks(link, sup, 3, t0=t)
    assert commander.intent.clear_emergency_stop is False


def test_sequence_owns_intent_but_safety_mirrors():
    link, commander, executor, mirror, sup = make_stack()
    link.sim.plant.wf_pressure_bar = 4.0
    t = run_ticks(link, sup, 2)
    executor.load(venting())
    executor.start()
    t = run_ticks(link, sup, 2, t0=t)
    assert executor.status in (Status.RUNNING, Status.HOLDING)
    # operator asks for FIRING mid-sequence: must NOT take (sequence owns mode)
    link.sim.ui_write(ui_request(requested_mode=SystemState.FIRING,
                                 force_motoring=True))
    run_ticks(link, sup, 2, t0=t)
    assert commander.intent.requested_mode != SystemState.FIRING
    # but the safety override mirrored instantly
    assert commander.intent.force_motoring is True


def test_transparent_when_no_sequence():
    """With no sequence, Python-in-command behaves like UI-in-command: the
    whole request cluster mirrors (minus heartbeats/clear)."""
    link, commander, executor, mirror, sup = make_stack()
    t = run_ticks(link, sup, 2)
    req = ui_request(requested_mode=SystemState.MOTORING, speed_ref=1200.0)
    req.pid_control_references.tcoolant.mode = 2
    req.pid_control_references.tcoolant.ec_tt_001_ref = 55.0
    link.sim.ui_write(req)
    run_ticks(link, sup, 3, t0=t)
    got = commander.intent
    assert got.speed_ref == 1200.0
    assert got.pid_control_references.tcoolant.mode == 2
    assert got.pid_control_references.tcoolant.ec_tt_001_ref == 55.0


def test_heartbeat_still_owned_by_commander():
    """Mirroring must not stomp pc_hb: it keeps toggling across sends."""
    link, commander, executor, mirror, sup = make_stack()
    t = run_ticks(link, sup, 2)
    link.sim.ui_write(ui_request(speed_ref=800.0))
    run_ticks(link, sup, 4, t0=t)
    from supervisory.messages import Command
    cmds = [m for m in link.sent if isinstance(m, Command)]
    hbs = [c.params["settings"]["PID control references"]["PC_HB"] for c in cmds[-3:]]
    assert hbs[0] != hbs[1] and hbs[1] != hbs[2]  # still alternating
