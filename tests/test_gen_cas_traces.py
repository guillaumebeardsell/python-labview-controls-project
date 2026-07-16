"""Physics/shape sanity for tools/gen_cas_traces.py — the synthetic CAS data
must honor the frame conventions the LabVIEW 9049 chain assumes (see
docs/9049-openloop-audit.md) or the SIL comparisons are meaningless."""

import math
import random

from tools.gen_cas_traces import (
    CYL_OFFSETS,
    IMEPG_WINDOW,
    N_SAMPLES,
    PEGGING_WINDOW,
    ROWS,
    TDC_INDEX,
    Geometry,
    add_knock,
    build_cycle,
    ca50_truth,
    cylinder_trace,
    metrics,
    volume_curve,
    wiebe_mfb,
)

GEOM = Geometry()
VOLS = volume_curve(GEOM)


def motored(**kw):
    return cylinder_trace(VOLS, 2.9, 3.0, 1.55, 1.62, **kw)


def fired(**kw):
    return cylinder_trace(VOLS, 2.9, 3.0, 1.55, 1.62, fired=True, q_fired_j=3000.0, **kw)


# --- volume model ---------------------------------------------------------


def test_volume_minimum_at_tdc_and_cr():
    # V is 360-periodic: TDC volume recurs at samples 0 (-360) and 3600 (0)
    assert math.isclose(VOLS[TDC_INDEX], min(VOLS), rel_tol=1e-12)
    vd = max(VOLS) - min(VOLS)
    assert math.isclose(vd / min(VOLS), GEOM.compression_ratio - 1.0, rel_tol=1e-9)


def test_volume_symmetric_without_pin_offset():
    # V(-theta) == V(+theta) when e=0
    for d in (100, 1000, 3000):
        assert math.isclose(VOLS[TDC_INDEX - d], VOLS[TDC_INDEX + d], rel_tol=1e-9)


# --- motored trace --------------------------------------------------------


def test_motored_peak_at_tdc_matches_polytropic():
    p = motored()
    expected = 2.9 * (VOLS[1800] / VOLS[TDC_INDEX]) ** 1.55
    assert p.index(max(p)) == TDC_INDEX
    assert math.isclose(max(p), expected, rel_tol=1e-6)


def test_motored_pegging_window_sits_on_exhaust_level():
    p = motored()
    lo, hi = PEGGING_WINDOW
    assert all(abs(v - 3.0) < 0.02 for v in p[lo:hi])


def test_motored_wraps_continuously():
    # exhaust end (sample 7199) must meet intake start (sample 0) level
    p = motored()
    assert abs(p[-1] - p[0]) < 0.02


def test_motored_imep_signs():
    m = metrics(motored(), VOLS)
    assert m["imep_g_bar"] < 0  # kappa_exp > kappa_comp = heat-loss loop
    assert m["imep_n_bar"] < 0
    assert abs(m["imep_n_bar"]) < 3.0  # motored magnitudes stay small


# --- fired trace ----------------------------------------------------------


def test_fired_beats_motored_and_truth_is_positive():
    mf = metrics(fired(), VOLS)
    # compare against the same-kappa motored anchor, not the motored trace
    # (motored uses different polytropic exponents)
    same_kappa_peak = 2.9 * (VOLS[1800] / VOLS[TDC_INDEX]) ** 1.45
    assert mf["pmax_bar"] > same_kappa_peak * 1.05
    assert mf["imep_g_bar"] > 2.0
    assert 0 <= mf["pmax_atdc"] < 45  # peak at/after TDC once burn is on


def test_ca50_truth_is_wiebe_half_point():
    ca50 = ca50_truth(-8.0, 45.0)
    assert math.isclose(wiebe_mfb(ca50, -8.0, 45.0), 0.5, abs_tol=1e-9)
    assert -8.0 < ca50 < 37.0


# --- knock ----------------------------------------------------------------


def test_knock_superposition_amplitude_and_location():
    base = fired()
    knocked = add_knock(base, 2.0, rpm=900.0)
    diff = [k - b for k, b in zip(knocked, base)]
    assert max(abs(d) for d in diff) <= 2.0 + 1e-9
    first = next(i for i, d in enumerate(diff) if d != 0.0)
    assert first >= TDC_INDEX + int(5.0 / 0.1)  # onset at +5 CADATDC


# --- raw block assembly ---------------------------------------------------


def test_build_cycle_shape_and_phasing():
    rng = random.Random(1)
    raw, truth, phased = build_cycle(
        VOLS, 900.0, 2.9, 3.0, 1.58, 1.52, fired_cyls=set(), knock={},
        q_fired_j=0.0, soc_atdc=-8.0, burn_dur_cad=45.0, kappa_fired=1.45,
        noise_bar=0.0, drift_ramps=[(0.0, 0.0)] * 6, rng=rng,
    )
    assert len(raw) == len(ROWS) == 9
    assert all(len(r) == N_SAMPLES for r in raw)
    # each cylinder's raw peak lands at (TDC + offset) % 7200
    for cyl in range(1, 7):
        row = raw[cyl - 1]
        assert row.index(max(row)) == (TDC_INDEX + CYL_OFFSETS[cyl - 1]) % N_SAMPLES
    assert set(truth["cylinders"]) == {str(c) for c in range(1, 7)}
    # phased frames: 6 cylinders, each with its firing TDC at sample 3600
    assert len(phased) == 6 and all(len(p) == N_SAMPLES for p in phased)
    for p in phased:
        assert p.index(max(p)) == TDC_INDEX


def test_firing_order_is_1_5_3_6_2_4():
    # cyclic order of TDC positions in the raw frame, rotated to start at cyl 1
    order = sorted(range(1, 7), key=lambda c: (TDC_INDEX + CYL_OFFSETS[c - 1]) % N_SAMPLES)
    i1 = order.index(1)
    assert order[i1:] + order[:i1] == [1, 5, 3, 6, 2, 4]


def test_imepg_window_matches_hrl_convention():
    assert IMEPG_WINDOW == (1800, 5400)  # CAD 180..540 = -180..+180 ATDC


# --- --q-jitter (CLI, cyclic-variability fault) ----------------------------


def _run_cli(tmp_path, name, *extra):
    import subprocess, sys, json
    out = tmp_path / name
    subprocess.run(
        [sys.executable, "tools/gen_cas_traces.py", str(out), "--cycles", "4",
         "--mode", "fired", "--noise", "0", "--drift", "0", "--seed", "7", *extra],
        check=True, capture_output=True)
    return json.loads((out / "truth.json").read_text())


def test_q_jitter_default_off_is_deterministic_and_uniform(tmp_path):
    a = _run_cli(tmp_path, "a")
    b = _run_cli(tmp_path, "b")
    assert a["cycles"] == b["cycles"]  # same seed, jitter off -> identical
    qs = [a["cycles"][str(c)]["q_fired_j"] for c in range(1, 5)]
    assert qs == [3000.0] * 4  # constant q, recorded per cycle
    imeps = [a["cycles"][str(c)]["cylinders"]["1"]["imep_g_bar"] for c in range(1, 5)]
    assert max(imeps) - min(imeps) < 1e-9  # identical cycles


def test_q_jitter_varies_imep_cycle_to_cycle_but_not_cyl_to_cyl(tmp_path):
    t = _run_cli(tmp_path, "j", "--q-jitter", "0.2")
    qs = [t["cycles"][str(c)]["q_fired_j"] for c in range(1, 5)]
    assert len(set(qs)) > 1 and all(2400.0 <= q <= 3600.0 for q in qs)  # ±20%
    # cycle-to-cycle IMEP spread appears (the MaxIMEPstd fault)...
    imeps = [t["cycles"][str(c)]["cylinders"]["1"]["imep_g_bar"] for c in range(1, 5)]
    assert max(imeps) - min(imeps) > 0.5
    # ...but within a cycle all 6 cylinders stay equal (cyl-to-cyl dev clean)
    for c in range(1, 5):
        cyls = t["cycles"][str(c)]["cylinders"]
        vals = [cyls[str(k)]["imep_g_bar"] for k in range(1, 7)]
        assert max(vals) - min(vals) < 1e-9


def test_drift_is_continuous_across_cycle_files(tmp_path):
    """The piezo-drift offset must not step at a file boundary: the two-cycle
    stitch in PPhaseCorrection turns a step into a fake heat-release spike
    (live false late-combustion trips on cyls 3/5, 2026-07-14)."""
    import subprocess, sys, csv
    out = tmp_path / "d"
    subprocess.run(
        [sys.executable, "tools/gen_cas_traces.py", str(out), "--cycles", "3",
         "--mode", "motored", "--noise", "0", "--drift", "0.2", "--seed", "3"],
        check=True, capture_output=True)
    blocks = []
    for n in (1, 2, 3):
        blocks.append([[float(x) for x in r]
                       for r in csv.reader(open(out / f"cycle_{n:04d}.csv"))])
    for cyl in range(6):
        for b in range(3):
            # boundary continuity: last sample of block b -> first of block
            # (b+1) mod N — including the WRAP (the sim player loops the set)
            step = abs(blocks[(b + 1) % 3][cyl][0] - blocks[b][cyl][-1])
            # the waveform itself moves < 0.01 bar/sample here; a drift step
            # would add up to 0.4 bar
            assert step < 0.05, f"cyl {cyl+1} block {b}: boundary step {step:.3f} bar"
