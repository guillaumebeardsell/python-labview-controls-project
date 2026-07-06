"""Phase B2 tests: MonarchCommander + MonarchGatewaySim against the ICD v0.2
draft failure matrix. Socket-free: the sim runs the real A1-ported StateMachine,
the commander runs under the generic Supervisor engine via MonarchSimLink.

Drill mapping (docs/phases/phase-b-command-path.md B4): #1/#2 pc_hb stall →
SAFE; #4 garbage → NACK, session survives; #5 range NACK; #6 flood rate limit;
#7 source flip bumpless; #8 e-stop precedence; #9 staleness stops the stream.
(#3 TCP drop is transport-level, covered by tests/test_tcp_link.py.)
"""

from supervisory.engine import Supervisor
from supervisory.messages import Command
from supervisory.monarch.commander import MonarchCommander
from supervisory.monarch.control_settings import ControlSettings, SystemState
from supervisory.monarch.labview_mapping import control_settings_to_labview
from supervisory.monarch.simserver_monarch import MonarchGatewaySim, MonarchSimLink
from supervisory.monarch.state_machine import NO_LIMIT


def make_stack(source="PYTHON"):
    link = MonarchSimLink(MonarchGatewaySim(source=source))
    commander = MonarchCommander()
    sup = Supervisor(link, [commander])
    return link, commander, sup


def run_ticks(link, sup, n, t0=0.0, dt=1.0):
    """advance sim + engine tick, n times; returns the final engine time."""
    t = t0
    for _ in range(n):
        link.advance(dt)
        t += dt
        sup.tick(t)
    return t


def valid_settings_params(**overrides):
    cs = ControlSettings()
    for k, v in overrides.items():
        setattr(cs, k, v)
    return {"settings": control_settings_to_labview(cs)}


# ---- happy path -------------------------------------------------------------

def test_seed_is_bumpless_and_pc_hb_toggles():
    link, commander, sup = make_stack()
    baseline = link.sim.requested.model_copy(deep=True)
    run_ticks(link, sup, 3)
    assert commander.commanding
    assert link.sim.accepted_count >= 2
    # bumpless: what Python asserts equals what the plant already had
    got = link.sim.requested.model_copy(deep=True)
    got.pid_control_references.pc_hb = baseline.pid_control_references.pc_hb
    assert got == baseline
    # pc_hb alternates between consecutive accepted commands
    cmds = [m for m in link.sent if isinstance(m, Command)]
    hbs = [c.params["settings"]["PID control references"]["PC_HB"] for c in cmds[-2:]]
    assert hbs[0] != hbs[1]


def test_mode_request_steps_up_one_per_tick():
    link, commander, sup = make_stack()
    run_ticks(link, sup, 1)
    commander.request_mode(SystemState.FIRING)
    states = []
    t = 1.0
    for _ in range(5):
        link.advance(1.0)  # frame N reflects the command accepted on tick N-1
        t += 1.0
        sup.tick(t)
        states.append(link.sim.current_state)
    assert states == [0, 1, 2, 3, 3]  # one step per tick, never a jump


# ---- drills #1/#2: frozen/killed Python => pc_hb stalls => SAFE --------------

def test_pc_hb_stall_clamps_to_safe_and_recovers():
    link, commander, sup = make_stack()
    t = run_ticks(link, sup, 3)
    assert link.sim.current_state >= 0
    # freeze: sim time advances, no commands arrive
    for _ in range(7):
        link.sim.tick(1.0)
    assert link.sim.pc_not_responding
    assert link.sim.current_state == -1  # SAFE
    # recovery: Python resumes; toggling pc_hb clears the flag; state climbs by 1
    t = run_ticks(link, sup, 3, t0=t + 7.0)
    assert not link.sim.pc_not_responding
    assert link.sim.current_state >= 0


def test_watchdog_inert_while_source_is_ui():
    # the clamp is gated on source=PYTHON (nothing toggles PC_HB in UI mode yet)
    sim = MonarchGatewaySim(source="UI")
    for _ in range(10):
        sim.tick(1.0)
    assert not sim.pc_not_responding
    assert sim.current_state >= 0


# ---- drill #4: garbage => NACK, nothing changes ------------------------------

def test_malformed_settings_nacked_as_parse():
    sim = MonarchGatewaySim(source="PYTHON")
    before = sim.requested.model_copy(deep=True)
    ack = sim.handle_command(Command(id=1, name="set_control_settings",
                                     params={"settings": "not an object"}))
    assert not ack.accepted and ack.reason == "parse"
    ack = sim.handle_command(Command(id=2, name="set_control_settings",
                                     params={"settings": {"Speed ref": "abc"}}))
    assert not ack.accepted and ack.reason == "parse"
    ack = sim.handle_command(Command(id=3, name="warp_drive", params={}))
    assert not ack.accepted and "unknown command" in ack.reason
    assert sim.requested == before


# ---- drill #5: out-of-range => NACK ------------------------------------------

def test_out_of_range_nacked():
    sim = MonarchGatewaySim(source="PYTHON")
    ack = sim.handle_command(Command(id=1, name="set_control_settings",
                                     params=valid_settings_params(speed_ref=9999.0)))
    assert not ack.accepted and ack.reason.startswith("range")


# ---- drill #6: flood => rate limit -------------------------------------------

def test_command_flood_rate_limited():
    sim = MonarchGatewaySim(source="PYTHON")
    results = [
        sim.handle_command(Command(id=i, name="set_control_settings",
                                   params=valid_settings_params()))
        for i in range(1, 8)  # 7 commands, same sim second
    ]
    assert [a.accepted for a in results[:5]] == [True] * 5
    assert all(not a.accepted and a.reason == "rate" for a in results[5:])


# ---- drill #7: source select + bumpless handover -----------------------------

def test_commands_nacked_while_source_ui():
    sim = MonarchGatewaySim(source="UI")
    ack = sim.handle_command(Command(id=1, name="set_control_settings",
                                     params=valid_settings_params()))
    assert not ack.accepted and ack.reason == "source is UI"


def test_commander_stays_silent_while_source_ui_then_hands_over_bumplessly():
    link, commander, sup = make_stack(source="UI")
    ui_settings = ControlSettings(speed_ref=1234.0)
    link.sim.ui_write(ui_settings)
    t = run_ticks(link, sup, 3)
    assert not commander.commanding
    assert link.sim.accepted_count == 0  # never even attempted
    # operator flips the source; first Python frame equals the UI's last one
    link.sim.set_source("PYTHON")
    run_ticks(link, sup, 2, t0=t)
    assert commander.commanding
    assert link.sim.requested.speed_ref == 1234.0


# ---- drill #8: e-stop precedence ----------------------------------------------

def test_estop_latches_and_python_cannot_clear():
    link, commander, sup = make_stack()
    t = run_ticks(link, sup, 2)
    commander.modify(lambda s: setattr(s, "emergency_stop", True))
    t = run_ticks(link, sup, 2, t0=t)  # tick 1 latches; tick 2's frame shows SAFE
    assert link.sim.estop_latched
    assert link.sim.current_state == -1
    # Python withdraws its e-stop request and (maliciously) tries to clear
    commander.modify(lambda s: setattr(s, "emergency_stop", False))
    commander.modify(lambda s: setattr(s, "clear_emergency_stop", True))
    t = run_ticks(link, sup, 2, t0=t)
    assert link.sim.estop_latched          # latch holds
    assert link.sim.current_state == -1    # still SAFE
    assert not link.sim.requested.clear_emergency_stop  # commander forced it False
    # only the operator clears; then the state climbs again
    link.sim.operator_clear_estop()
    run_ticks(link, sup, 2, t0=t)
    assert link.sim.current_state >= 0


def test_direct_clear_attempt_is_nacked():
    sim = MonarchGatewaySim(source="PYTHON")
    ack = sim.handle_command(Command(id=1, name="set_control_settings",
                                     params=valid_settings_params(clear_emergency_stop=True)))
    assert not ack.accepted and ack.reason == "operator only"


# ---- drill #9: telemetry staleness stops the stream ---------------------------

def test_stale_telemetry_stops_commanding_and_reseeds():
    link, commander, sup = make_stack()
    t = run_ticks(link, sup, 2)
    sent_before = link.sim.accepted_count
    sup.tick(t + 10.0)  # no telemetry advanced: stale
    sup.tick(t + 11.0)
    assert link.sim.accepted_count == sent_before  # nothing sent while stale
    assert not commander.commanding
    assert commander.intent is None  # will re-seed from telemetry (bumpless)
    run_ticks(link, sup, 2, t0=t + 11.0)
    assert commander.commanding


# ---- telemetry envelope carries the source ------------------------------------

def test_envelope_reports_command_source_and_limited_settings():
    link, _, sup = make_stack()
    link.advance(1.0)
    msgs = link.poll()
    tm = msgs[0]
    assert tm.command_source == "PYTHON"
    assert tm.limited_settings is not None
    assert tm.warnings_limit == NO_LIMIT
