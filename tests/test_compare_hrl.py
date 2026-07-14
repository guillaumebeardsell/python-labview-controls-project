"""Tests for tools/compare_hrl.py — the SIL-0 regression gate's CSV loader.

`load_labview()` must (a) match columns **by name** when a header is present, so
the harness can add `mapo`/`imepstd`/`pmax_atdc` in any order and one file feeds
both `compare_hrl` and `tune_thresholds`; and (b) fall back to the positional
6-/7-column layout when there's no header. Regression guarded here: an 8-column
header'd file must NOT be read positionally (which misread `mapo` as `ca50`).
"""

import csv

from tools.compare_hrl import _header_map, _norm, load_labview


def _write(path, rows):
    with path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path


def test_header_matched_reads_by_name(tmp_path):
    p = _write(tmp_path / "m.csv", [
        ["cycle", "cylinder", "imep_g", "imep_n", "pmax", "ca50", "mapo", "imepstd"],
        [1, 1, -1.1, -1.2, 150.9, -23.0, 0.5, 0.1],
        [1, 2, -1.0, -1.1, 149.0, -22.0, 0.4, 0.2],
    ])
    got = load_labview(p)
    assert got[(1, 1)] == {"imep_g": -1.1, "imep_n": -1.2, "pmax": 150.9, "ca50": -23.0}
    # unknown columns (mapo/imepstd) are ignored, not stored
    assert "mapo" not in got[(1, 1)] and "imepstd" not in got[(1, 1)]
    assert got[(1, 2)]["ca50"] == -22.0


def test_8col_header_does_not_misread_ca50_as_mapo(tmp_path):
    """The bug the header-match fixes: a positional parse of an 8-col file put
    `mapo` where `ca50` belongs. Assert `ca50` is the real ca50 value."""
    p = _write(tmp_path / "m.csv", [
        ["cycle", "cylinder", "imep_g", "imep_n", "pmax", "ca50", "mapo", "imepstd"],
        [3, 4, -1.1, -1.2, 150.9, -23.0, 999.0, 0.1],  # mapo deliberately absurd
    ])
    assert load_labview(p)[(3, 4)]["ca50"] == -23.0


def test_positional_6col_no_header(tmp_path):
    p = _write(tmp_path / "m.csv", [[1, 1, -1.1, -1.2, 150.9, -23.0]])
    got = load_labview(p)[(1, 1)]
    assert got == {"imep_g": -1.1, "imep_n": -1.2, "pmax": 150.9, "ca50": -23.0}
    assert "pmax_atdc" not in got


def test_positional_7col_no_header(tmp_path):
    # cycle,cyl,imep_g,imep_n,pmax,pmax_atdc,ca50  — pmax_atdc=5.0 before ca50
    p = _write(tmp_path / "m.csv", [[1, 1, -1.1, -1.2, 150.9, 5.0, -23.0]])
    got = load_labview(p)[(1, 1)]
    assert got["pmax_atdc"] == 5.0
    assert got["ca50"] == -23.0


def test_scrambled_header_order(tmp_path):
    p = _write(tmp_path / "m.csv", [
        ["cycle", "cylinder", "mapo", "ca50", "imep_g", "pmax", "imepstd", "imep_n"],
        [1, 1, 0.5, -23.0, -1.1, 150.9, 0.1, -1.2],
    ])
    assert load_labview(p)[(1, 1)] == {
        "imep_g": -1.1, "imep_n": -1.2, "pmax": 150.9, "ca50": -23.0}


def test_header_with_cluster_unit_labels(tmp_path):
    """LabVIEW cluster field labels (units/brackets) normalize to canonical names."""
    p = _write(tmp_path / "m.csv", [
        ["cycle", "cylinder", "IMEPg [bar]", "IMEPn [bar]", "Pmax [bar]", "CA50 [CADATDC]"],
        [1, 1, -1.1, -1.2, 150.9, -23.0],
    ])
    got = load_labview(p)[(1, 1)]
    assert got["imep_g"] == -1.1 and got["ca50"] == -23.0


def test_norm_and_header_map():
    assert _norm("MAPO [bar/CAD]") == "mapobarcad"
    assert _norm("IMEPg [bar]") == "imepgbar"
    assert _header_map(["cycle", "cylinder", "IMEPg [bar]", "pmax"]) == {
        "cycle": 0, "cylinder": 1, "imep_g": 2, "pmax": 3}
    assert _header_map(["foo", "bar", "baz"]) is None
