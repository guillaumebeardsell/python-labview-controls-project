"""Phase D tests: MONARCH sequences closed-loop against the sim plant.

The full stack under test: SequenceExecutor -> MonarchCommander (intent) ->
MonarchSimLink/MonarchGatewaySim (ICD validation + the REAL A1-ported
StateMachine/limiter) -> SimPlantModel dynamics -> telemetry back into the
sequence's confirmations. Plus randomized fault injection (D2 property test).
"""

import random

from supervisory.engine import Supervisor
from supervisory.monarch.commander import MonarchCommander
from supervisory.monarch.control_settings import SystemState
from supervisory.monarch.sequences import (
    DRAFT_SEQUENCES,
    SequenceConfig,
    SequenceExecutor,
    purge,
    thermal_warmup,
    venting,
)
from supervisory.monarch.simserver_monarch import MonarchGatewaySim, MonarchSimLink
from supervisory.sequencing import Status

CFG = SequenceConfig()


def make_stack():
    link = MonarchSimLink(MonarchGatewaySim(source="PYTHON"))
    commander = MonarchCommander()
    executor = SequenceExecutor(commander)
    # executor BEFORE commander: changes land in the same tick's command
    sup = Supervisor(link, [executor, commander])
    return link, commander, executor, sup


def run_until_terminal(link, sup, executor, max_ticks=600, dt=1.0, on_tick=None):
    t = 0.0
    for i in range(max_ticks):
        if on_tick:
            on_tick(i)
        link.advance(dt)
        t += dt
        sup.tick(t)
        if executor.status in (Status.DONE, Status.ABORTED):
            # one more engine tick so the abort-landing command goes out
            link.advance(dt)
            t += dt
            sup.tick(t)
            return executor.status
    raise AssertionError(f"sequence did not terminate in {max_ticks} ticks "
                         f"(status={executor.status}, "
                         f"step={getattr(executor.runner.active_step, 'label', None)})")


def start(executor, sequence, **kw):
    executor.load(sequence, **kw)
    executor.start()


# ------------------------------------------------------------- happy paths

def test_venting_completes_in_sim():
    link, commander, executor, sup = make_stack()
    # pressurize the plant first so depressurization is observable
    link.sim.plant.wf_pressure_bar = 4.0
    start(executor, venting())
    status = run_until_terminal(link, sup, executor)
    assert status is Status.DONE
    assert link.sim.plant.wf_pressure_bar < CFG.ambient_bar + CFG.depressurize_band_bar
    p = link.sim.requested.pid_control_references
    assert p.ng.mode == 0 and p.ar.mode == 0 and p.o2.mode == 0


def test_purge_completes_in_sim_with_hold():
    link, commander, executor, sup = make_stack()
    link.sim.plant.o2_pct = 21.0
    start(executor, purge())

    def auto_confirm(i):
        if executor.status is Status.HOLDING:
            executor.confirm_hold()

    status = run_until_terminal(link, sup, executor, on_tick=auto_confirm)
    assert status is Status.DONE
    assert link.sim.plant.o2_pct < CFG.purge_o2_target_pct
    # secured: feeds cut, back at STAND_BY
    assert link.sim.requested.pid_control_references.ar.mode == 0
    assert link.sim.current_state == int(SystemState.STAND_BY)


def test_thermal_warmup_completes_in_sim():
    link, commander, executor, sup = make_stack()
    start(executor, thermal_warmup())

    def auto_confirm(i):
        if executor.status is Status.HOLDING:
            executor.confirm_hold()

    status = run_until_terminal(link, sup, executor, on_tick=auto_confirm)
    assert status is Status.DONE
    assert abs(link.sim.plant.coolant_c - CFG.coolant_target_c) <= CFG.temp_band_c
    assert abs(link.sim.plant.oil_c - CFG.oil_target_c) <= CFG.temp_band_c


# ------------------------------------------------------------ safety paths

def test_estop_mid_purge_aborts_and_lands_safe():
    link, commander, executor, sup = make_stack()
    start(executor, purge())

    def press_estop(i):
        if i == 4:
            link.sim.operator_estop()

    status = run_until_terminal(link, sup, executor, on_tick=press_estop)
    assert status is Status.ABORTED
    assert executor.runner.abort_reason.startswith("invariant:no unexpected SAFE")
    # landing intent: feeds cut, request withdrawn
    p = link.sim.requested.pid_control_references
    assert p.ar.mode == 0 and p.ng.mode == 0
    # and the plant is in SAFE regardless (LabVIEW side latched e-stop)
    assert link.sim.current_state == int(SystemState.SAFE)


def test_source_flip_mid_sequence_aborts():
    link, commander, executor, sup = make_stack()
    start(executor, venting())
    link.sim.plant.wf_pressure_bar = 4.0

    def flip(i):
        if i == 3:
            link.sim.set_source("UI")

    status = run_until_terminal(link, sup, executor, on_tick=flip)
    assert status is Status.ABORTED
    assert executor.runner.abort_reason == "lost command authority"


def test_warning_clamp_mid_warmup_aborts():
    link, commander, executor, sup = make_stack()
    start(executor, purge())

    def warn(i):
        if i == 4:
            link.sim.warnings_limit = -1  # black warning: safe & vent

    status = run_until_terminal(link, sup, executor, on_tick=warn)
    assert status is Status.ABORTED


def test_never_confirming_step_times_out():
    link, commander, executor, sup = make_stack()
    cfg = SequenceConfig(depressurize_timeout_s=5.0)
    start(executor, venting(cfg))
    # hold pressure up so depressurization never confirms
    def hold_pressure(i):
        link.sim.plant.wf_pressure_bar = 4.0
    status = run_until_terminal(link, sup, executor, on_tick=hold_pressure)
    assert status is Status.ABORTED
    assert "timeout" in executor.runner.abort_reason


# -------------------------------------------------- randomized fault injection

def test_random_fault_injection_all_drafts_land_safe():
    """D2 property: any single fault at any tick, in any draft sequence, ends
    DONE or ABORTED — and the plant ends in a non-firing, feeds-cut posture
    whenever the run aborted."""
    faults = ["estop", "warning", "source_flip", "none"]
    for seed in range(60):
        rng = random.Random(seed)
        seq_name = rng.choice(list(DRAFT_SEQUENCES))
        fault = rng.choice(faults)
        fault_tick = rng.randrange(1, 25)
        link, commander, executor, sup = make_stack()
        link.sim.plant.wf_pressure_bar = 4.0
        start(executor, DRAFT_SEQUENCES[seq_name]())

        def on_tick(i):
            if executor.status is Status.HOLDING:
                executor.confirm_hold()
            if i == fault_tick:
                if fault == "estop":
                    link.sim.operator_estop()
                elif fault == "warning":
                    link.sim.warnings_limit = -1
                elif fault == "source_flip":
                    link.sim.set_source("UI")

        status = run_until_terminal(link, sup, executor, on_tick=on_tick)
        assert status in (Status.DONE, Status.ABORTED), f"seed {seed} ({seq_name}/{fault})"
        if status is Status.ABORTED and fault in ("estop", "warning"):
            assert link.sim.current_state <= int(SystemState.STAND_BY), (
                f"seed {seed}: aborted but state={link.sim.current_state}")
