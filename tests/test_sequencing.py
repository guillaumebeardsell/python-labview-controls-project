"""Tests for the generic sequencing framework (Phase D1)."""

import random

import pytest

from supervisory.sequencing import (
    Action,
    Branch,
    Hold,
    Invariant,
    Sequence,
    SequenceRunner,
    Status,
)


class FakeTelemetry:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeIntent:
    def __init__(self):
        self.log = []


def set_flag(name):
    def change(intent):
        intent.log.append(name)
    return change


def run(runner, script, intent=None):
    """Drive the runner with a scripted list of (telemetry, stale) per tick.
    Applies returned changes to `intent`. Returns tick results."""
    results = []
    for i, (tm, stale) in enumerate(script):
        res = runner.tick(float(i), tm, stale)
        for ch in res.changes:
            if intent is not None:
                ch(intent)
        results.append(res)
        if runner.status in (Status.DONE, Status.ABORTED):
            break
    return results


def simple_sequence(**kw):
    return Sequence(
        name="simple",
        steps=(
            Action("open vents", change=set_flag("vents_open"),
                   confirm=lambda tm: tm.vents_open, timeout_s=5.0),
            Action("note", change=set_flag("noted")),
        ),
        abort_change=set_flag("ABORT_LANDING"),
        **kw,
    )


# ------------------------------------------------------------- happy path

def test_happy_path_confirm_then_done():
    seq = simple_sequence()
    r = SequenceRunner(seq)
    r.start()
    intent = FakeIntent()
    script = [
        (FakeTelemetry(vents_open=False), False),  # change emitted
        (FakeTelemetry(vents_open=False), False),  # waiting
        (FakeTelemetry(vents_open=True), False),   # confirmed -> advance
        (FakeTelemetry(vents_open=True), False),   # step 2 change, advance next
        (FakeTelemetry(vents_open=True), False),
    ]
    run(r, script, intent)
    assert r.status is Status.DONE
    assert intent.log == ["vents_open", "noted"]


def test_change_emitted_exactly_once():
    r = SequenceRunner(simple_sequence())
    r.start()
    intent = FakeIntent()
    script = [(FakeTelemetry(vents_open=False), False)] * 4
    run(r, script, intent)
    assert intent.log.count("vents_open") == 1


# ----------------------------------------------------------------- aborts

def test_timeout_aborts_and_lands():
    r = SequenceRunner(simple_sequence())
    r.start()
    intent = FakeIntent()
    script = [(FakeTelemetry(vents_open=False), False)] * 10  # never confirms
    results = run(r, script, intent)
    assert r.status is Status.ABORTED
    assert "timeout:open vents" in r.abort_reason
    assert intent.log[-1] == "ABORT_LANDING"
    assert results[-1].abort_reason == r.abort_reason


def test_invariant_violation_aborts_mid_step():
    seq = simple_sequence(invariants=(Invariant("coolant", lambda tm: tm.coolant_ok),))
    r = SequenceRunner(seq)
    r.start()
    intent = FakeIntent()
    script = [
        (FakeTelemetry(vents_open=False, coolant_ok=True), False),
        (FakeTelemetry(vents_open=False, coolant_ok=False), False),  # violation
    ]
    run(r, script, intent)
    assert r.status is Status.ABORTED
    assert r.abort_reason == "invariant:coolant"
    assert intent.log[-1] == "ABORT_LANDING"


def test_stale_telemetry_aborts():
    r = SequenceRunner(simple_sequence())
    r.start()
    intent = FakeIntent()
    run(r, [(FakeTelemetry(vents_open=False), False), (None, True)], intent)
    assert r.status is Status.ABORTED
    assert r.abort_reason == "stale telemetry"


def test_stale_grace_ticks():
    r = SequenceRunner(simple_sequence(), max_stale_ticks=2)
    r.start()
    intent = FakeIntent()
    script = [
        (FakeTelemetry(vents_open=False), False),
        (None, True), (None, True),                       # within grace
        (FakeTelemetry(vents_open=True), False),          # recovers, confirms
        (FakeTelemetry(vents_open=True), False),
        (FakeTelemetry(vents_open=True), False),
    ]
    run(r, script, intent)
    assert r.status is Status.DONE


def test_operator_abort_any_time():
    r = SequenceRunner(simple_sequence())
    r.start()
    intent = FakeIntent()
    r.tick(0.0, FakeTelemetry(vents_open=False), False)
    r.abort("operator")
    res = r.tick(1.0, FakeTelemetry(vents_open=False), False)
    for ch in res.changes:
        ch(intent)
    assert r.status is Status.ABORTED
    assert r.abort_reason == "operator"
    assert intent.log[-1] == "ABORT_LANDING"


def test_abort_landing_emitted_exactly_once():
    r = SequenceRunner(simple_sequence())
    r.start()
    intent = FakeIntent()
    script = [(FakeTelemetry(vents_open=False), False)] * 10
    run(r, script, intent)
    r.tick(99.0, FakeTelemetry(vents_open=False), False)  # extra ticks after abort
    assert intent.log.count("ABORT_LANDING") == 1


def test_confirm_requires_timeout():
    with pytest.raises(ValueError):
        Action("bad", confirm=lambda tm: True)


# ------------------------------------------------------------------- holds

def test_hold_blocks_until_confirmed():
    seq = Sequence("h", steps=(Hold("check", "verify lineup"),
                               Action("after", change=set_flag("after"))),
                   abort_change=set_flag("ABORT"))
    r = SequenceRunner(seq)
    r.start()
    intent = FakeIntent()
    tm = FakeTelemetry()
    r.tick(0.0, tm, False)
    r.tick(1.0, tm, False)
    assert r.status is Status.HOLDING
    r.confirm_hold()
    run(r, [(tm, False)] * 4, intent)
    assert r.status is Status.DONE
    assert intent.log == ["after"]


def test_hold_timeout_aborts():
    seq = Sequence("h", steps=(Hold("check", "verify", timeout_s=2.0),),
                   abort_change=set_flag("ABORT"))
    r = SequenceRunner(seq)
    r.start()
    tm = FakeTelemetry()
    for i in range(5):
        r.tick(float(i), tm, False)
    assert r.status is Status.ABORTED
    assert "hold timeout" in r.abort_reason


# ----------------------------------------------------------------- branches

def test_branch_takes_then_arm():
    seq = Sequence("b", steps=(
        Branch("already open?", lambda tm: tm.vents_open,
               then=(Action("skip", change=set_flag("skipped")),),
               otherwise=(Action("open", change=set_flag("opened")),)),
    ))
    r = SequenceRunner(seq)
    r.start()
    intent = FakeIntent()
    run(r, [(FakeTelemetry(vents_open=True), False)] * 4, intent)
    assert intent.log == ["skipped"]
    assert r.status is Status.DONE


def test_branch_takes_otherwise_arm():
    seq = Sequence("b", steps=(
        Branch("already open?", lambda tm: tm.vents_open,
               then=(Action("skip", change=set_flag("skipped")),),
               otherwise=(Action("open", change=set_flag("opened")),)),
    ))
    r = SequenceRunner(seq)
    r.start()
    intent = FakeIntent()
    run(r, [(FakeTelemetry(vents_open=False), False)] * 4, intent)
    assert intent.log == ["opened"]


# -------------------------------------------------- randomized fault injection

def test_random_fault_injection_always_lands_safe():
    """Property: whatever single fault occurs at whatever tick, the runner ends
    in DONE or ABORTED, and every ABORTED run emitted the abort landing."""
    for seed in range(200):
        rng = random.Random(seed)
        seq = simple_sequence(invariants=(Invariant("inv", lambda tm: getattr(tm, "ok", True)),))
        r = SequenceRunner(seq)
        r.start()
        intent = FakeIntent()
        fault_tick = rng.randrange(0, 8)
        fault = rng.choice(["stale", "invariant", "operator", "never_confirm"])
        for i in range(30):
            if r.status in (Status.DONE, Status.ABORTED):
                break
            stale = fault == "stale" and i >= fault_tick
            ok = not (fault == "invariant" and i >= fault_tick)
            confirmed = (fault != "never_confirm") and i >= 2
            if fault == "operator" and i == fault_tick:
                r.abort("operator")
            tm = None if stale else FakeTelemetry(vents_open=confirmed, ok=ok)
            res = r.tick(float(i), tm, stale)
            for ch in res.changes:
                ch(intent)
        assert r.status in (Status.DONE, Status.ABORTED), f"seed {seed}"
        if r.status is Status.ABORTED:
            assert intent.log.count("ABORT_LANDING") == 1, f"seed {seed}: {intent.log}"
        else:
            assert "ABORT_LANDING" not in intent.log, f"seed {seed}"
