from supervisory.engine import CommandRequest, StateMachine, Supervisor
from supervisory.messages import Command, Heartbeat
from supervisory.sim import SimPlantLink


class Scripted(StateMachine):
    """Returns the next scripted request list each step; records every view."""

    name = "scripted"

    def __init__(self, script=None):
        self.script = list(script or [])
        self.views = []

    def step(self, view):
        self.views.append(view)
        return self.script.pop(0) if self.script else []


class Boom(StateMachine):
    name = "boom"

    def step(self, view):
        raise RuntimeError("machine bug")


def sent_commands(link):
    return [m for m in link.sent if isinstance(m, Command)]


def test_stale_before_first_telemetry_drops_commands():
    link = SimPlantLink()
    machine = Scripted([[CommandRequest("start")]])
    sup = Supervisor(link, [machine])
    view = sup.tick(0.0)
    assert view.stale
    assert view.telemetry is None
    assert sent_commands(link) == []
    # heartbeat still flows while connected, even without telemetry
    assert any(isinstance(m, Heartbeat) for m in link.sent)


def test_staleness_follows_telemetry_age():
    link = SimPlantLink()
    sup = Supervisor(link, [], telemetry_timeout_s=3.0)
    link.advance(1.0)
    assert not sup.tick(0.0).stale
    assert not sup.tick(3.0).stale  # exactly at the limit
    assert sup.tick(3.5).stale


def test_command_flow_ack_and_effect():
    link = SimPlantLink()
    machine = Scripted([[CommandRequest("start")]])
    sup = Supervisor(link, [machine])
    link.advance(1.0)
    sup.tick(0.0)
    cmds = sent_commands(link)
    assert [c.id for c in cmds] == [1]
    link.advance(1.0)
    view = sup.tick(1.0)
    assert [(a.id, a.accepted) for a in view.acks] == [(1, True)]
    assert view.telemetry.mode == "RUNNING"  # effect confirmed via telemetry


def test_rejected_command_ack_reported():
    link = SimPlantLink()
    link.plant.interlock_ok = False
    machine = Scripted([[CommandRequest("start")]])
    sup = Supervisor(link, [machine])
    link.advance(1.0)
    sup.tick(0.0)
    view = sup.tick(1.0)
    (ack,) = view.acks
    assert not ack.accepted
    assert "interlock" in ack.reason


def test_stale_view_drops_new_commands():
    link = SimPlantLink()
    machine = Scripted([[CommandRequest("start")], [CommandRequest("stop")]])
    sup = Supervisor(link, [machine], telemetry_timeout_s=3.0)
    link.advance(1.0)
    sup.tick(0.0)  # fresh: start goes out
    sup.tick(10.0)  # stale: stop must be dropped
    assert [c.name for c in sent_commands(link)] == ["start"]


def test_machine_exception_does_not_stop_others():
    link = SimPlantLink()
    good = Scripted([[CommandRequest("start")]])
    sup = Supervisor(link, [Boom(), good])
    link.advance(1.0)
    sup.tick(0.0)
    assert [c.name for c in sent_commands(link)] == ["start"]


def test_command_ids_and_heartbeat_seqs_increment():
    link = SimPlantLink()
    machine = Scripted([[CommandRequest("set_setpoint", {"value": 50.0})], [CommandRequest("start")]])
    sup = Supervisor(link, [machine])
    link.advance(1.0)
    sup.tick(0.0)
    link.advance(1.0)
    sup.tick(1.0)
    assert [c.id for c in sent_commands(link)] == [1, 2]
    assert [h.seq for h in link.sent if isinstance(h, Heartbeat)] == [1, 2]


class HeatAndStop(StateMachine):
    """Minimal port-style sequence: wait ready, heat to target, stop."""

    name = "heat_and_stop"

    def __init__(self, target_c):
        self.state = "WAIT_READY"
        self.target_c = target_c

    def step(self, view):
        tm = view.telemetry
        if view.stale or tm is None:
            return []
        if self.state == "WAIT_READY" and tm.mode == "IDLE" and tm.flags.get("interlock_ok"):
            self.state = "HEATING"
            return [CommandRequest("set_setpoint", {"value": 100.0}), CommandRequest("start")]
        if self.state == "HEATING" and tm.channels["temp_c"] >= self.target_c:
            self.state = "DONE"
            return [CommandRequest("stop")]
        return []


def test_full_sequence_against_sim_plant():
    link = SimPlantLink()
    machine = HeatAndStop(target_c=30.0)
    sup = Supervisor(link, [machine])
    for i in range(60):
        link.advance(1.0)
        sup.tick(float(i))
        if machine.state == "DONE":
            break
    assert machine.state == "DONE"
    assert link.plant.mode == "IDLE"  # started, heated, stopped
    assert [c.name for c in sent_commands(link)] == ["set_setpoint", "start", "stop"]
