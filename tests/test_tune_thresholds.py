"""Sanity for tools/tune_thresholds.py — the motoring warning-limit recommender
must (a) put MaxPCylMax above the observed peak with margin, (b) disarm the
motored false-trippers, and (c) respect the hardware pressure ceiling."""

import csv

from tools.tune_thresholds import cyl_to_cyl_spread, load, running_imep_std


def _write(tmp_path, rows):
    p = tmp_path / "m.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    return p


def test_load_and_stats(tmp_path):
    # 2 cycles, 3 cyls; cyl-to-cyl spread 0.2 in cycle 1; per-cyl IMEPn varies by cycle
    rows = [
        [1, 1, -1.0, -1.1, 150.0, 0], [1, 2, -1.1, -1.2, 150.0, 0], [1, 3, -1.2, -1.3, 150.0, 0],
        [2, 1, -1.0, -1.3, 152.0, 0], [2, 2, -1.1, -1.2, 152.0, 0], [2, 3, -1.2, -1.1, 152.0, 0],
    ]
    got = load(_write(tmp_path, rows))
    assert len(got) == 6
    assert abs(cyl_to_cyl_spread(got) - 0.2) < 1e-9      # |-1.0 - -1.2| within a cycle
    assert running_imep_std(got) > 0                      # IMEPn changes cycle to cycle


def test_motored_recommendation(tmp_path, capsys):
    from tools.tune_thresholds import main
    import sys
    rows = [[c, cyl, -1.15, -1.21, 150.9, 0] for c in range(1, 6) for cyl in range(1, 7)]
    p = _write(tmp_path, rows)
    argv = sys.argv
    sys.argv = ["tune", str(p), "--mode", "motored", "--pmax-hard-limit", "200"]
    try:
        assert main() == 0
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "DISARM" in out                    # CA50max + MaxDevFromExpectedIMEP disarmed
    assert "CA50max" in out and "MaxDevFromExpectedIMEP" in out
    # MaxPCylMax error limit is above the observed 150.9 peak and under the 200 ceiling
    line = next(l for l in out.splitlines() if l.startswith("MaxPCylMax"))
    err = float(line.split()[2])
    assert 150.9 < err <= 200.0


def test_pmax_hard_limit_caps(tmp_path, capsys):
    """A low hardware ceiling must clamp the error limit even if margin wants more."""
    from tools.tune_thresholds import main
    import sys
    rows = [[c, cyl, -1.0, -1.1, 150.0, 0] for c in range(1, 4) for cyl in range(1, 7)]
    p = _write(tmp_path, rows)
    argv = sys.argv
    sys.argv = ["tune", str(p), "--mode", "motored", "--pmax-hard-limit", "160"]
    try:
        main()
    finally:
        sys.argv = argv
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("MaxPCylMax"))
    assert float(line.split()[2]) == 160.0    # 150*1.3=195 clamped to the 160 ceiling


def test_header_aware_load_captures_mapo_imepstd(tmp_path):
    """A named header lets the loader pick up mapo/imepstd in any column order."""
    header = ["cycle", "cylinder", "imep_g", "imep_n", "Pmax", "MAPO [bar/CAD]", "CA50", "IMEPstd"]
    rows = [header] + [[c, cyl, 6.0, 5.5, 95.0, 0.4, 8.0, 0.12]
                       for c in range(1, 4) for cyl in range(1, 7)]
    got = load(_write(tmp_path, rows))
    assert len(got) == 18
    assert got[0]["mapo"] == 0.4 and got[0]["imepstd"] == 0.12 and got[0]["ca50"] == 8.0


def test_fired_mapo_column_tunes_knock(tmp_path, capsys):
    """With a MAPO column present, fired mode auto-tunes MAPOmax instead of leaving it hand-set."""
    from tools.tune_thresholds import main
    import sys
    header = ["cycle", "cylinder", "imep_g", "imep_n", "pmax", "mapo", "ca50", "imepstd"]
    rows = [header] + [[c, cyl, 6.0, 5.5, 95.0, 0.5, 8.0, 0.10]
                       for c in range(1, 5) for cyl in range(1, 7)]
    p = _write(tmp_path, rows)
    argv = sys.argv
    sys.argv = ["tune", str(p), "--mode", "fired"]
    try:
        assert main() == 0
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("MAPOmax"))
    assert "DISARM" not in line                       # tuned from the column, not disarmed
    assert float(line.split()[2]) == 1.5              # 0.5*3 = 1.5 error limit
    assert "analytics IMEPstd column" in out          # used the real std, not the computed one
    assert "NOT auto-tuned" not in out                # the hand-set footnote is suppressed
