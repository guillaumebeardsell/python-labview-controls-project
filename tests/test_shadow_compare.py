"""Tests for tools/shadow_compare.py — the Phase A2 harness."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from supervisory.monarch import ControlSettings, MonarchTelemetry
from supervisory.monarch.state_machine import (
    StateDecisionInputs,
    decide_state,
    limit_settings,
)
from tools.shadow_compare import Report, compare_stream


def frame(seq, state, requested, limited=None, warnings=None):
    return MonarchTelemetry(
        seq=seq,
        ts=float(seq),
        system_state=state,
        settings=ControlSettings(requested_mode=requested),
        warnings_limit=warnings,
        limited_settings=limited,
    )


def faithful_walk(requested_sequence, start=0):
    """Frames whose system_state is what the port itself would decide —
    a LabVIEW that agrees perfectly."""
    frames = []
    state = start
    for i, req in enumerate(requested_sequence):
        if i > 0:
            state = decide_state(StateDecisionInputs(
                current_state=state, settings=ControlSettings(requested_mode=req)))
        frames.append(frame(i + 1, state, req))
    return frames


def test_agreeing_stream():
    rep = compare_stream(faithful_walk([0, 3, 3, 3, 3, 0, -1, 0]), Report())
    assert rep.compared == 7
    assert rep.state_matches == 7
    assert not rep.state_divergences


def test_divergence_detected():
    frames = faithful_walk([0, 3, 3, 3])
    # corrupt one LabVIEW output: claim FIRING straight from STAND_BY
    frames[1] = frame(2, 3, 3)
    rep = compare_stream(frames, Report())
    assert rep.state_divergences
    d = rep.state_divergences[0]
    assert d["labview"] == 3 and d["python"] == 1
    assert d["reduced_coverage"] is True  # no extras in these frames


def test_session_reset_skips_first_frame():
    a = faithful_walk([0, 3, 3])
    b = faithful_walk([0, 3, 3])  # seq restarts at 1 -> new session
    rep = compare_stream(a + b, Report())
    assert rep.sessions == 2
    assert rep.compared == 4  # 2 per session, first of each skipped


def test_limited_settings_compared():
    cs = ControlSettings(requested_mode=2, ign_enable=True)
    good = frame(2, 1, 2, limited=limit_settings(cs, 1))
    good.settings.ign_enable = True
    frames = [frame(1, 0, 0), good]
    # make settings consistent for the second frame
    frames[1] = MonarchTelemetry(
        seq=2, ts=2.0, system_state=1,
        settings=cs, limited_settings=limit_settings(cs, 1))
    rep = compare_stream(frames, Report())
    assert rep.limited_compared == 1
    assert rep.limited_matches == 1


def test_limited_divergence_reports_paths():
    cs = ControlSettings(requested_mode=2, ign_enable=True)
    wrong = limit_settings(cs, 1).model_copy(deep=True)
    wrong.ign_enable = True  # limiter should have gated IGN in MOTORING
    frames = [
        frame(1, 0, 0),
        MonarchTelemetry(seq=2, ts=2.0, system_state=1,
                         settings=cs, limited_settings=wrong),
    ]
    rep = compare_stream(frames, Report())
    assert rep.limited_divergences
    paths = [p for p, _, _ in rep.limited_divergences[0]["diffs"]]
    assert "ign_enable" in paths


def test_nan_leaves_compare_equal():
    # LabVIEW emits NaN for some live refs; NaN==NaN must not count as divergence
    cs = ControlSettings()
    cs.pid_control_references.ng.wf_oa_002_ref = float("nan")
    lim = limit_settings(cs, 0)
    frames = [frame(1, 0, 0),
              MonarchTelemetry(seq=2, ts=2.0, system_state=0,
                               settings=cs, limited_settings=lim)]
    rep = compare_stream(frames, Report())
    assert rep.limited_matches == 1 and not rep.limited_divergences


def test_heartbeat_bits_ignored_in_limited_diff():
    # pc_hb toggles between LabVIEW's two cluster reads; not a limiter field
    cs = ControlSettings()
    lim = limit_settings(cs, 0)
    lim.pid_control_references.pc_hb = True  # differs from requested (False)
    frames = [frame(1, 0, 0),
              MonarchTelemetry(seq=2, ts=2.0, system_state=0,
                               settings=cs, limited_settings=lim)]
    rep = compare_stream(frames, Report())
    assert rep.limited_matches == 1 and not rep.limited_divergences


def test_extras_used_when_present():
    # warnings_limit=1 must cap the prediction (and mark extras_seen)
    frames = [frame(1, 0, 0, warnings=3), frame(2, 1, 3, warnings=1)]
    rep = compare_stream(frames, Report())
    assert rep.extras_seen
    assert rep.state_matches == 1  # min(3, 1, 0+1) == 1 == labview
