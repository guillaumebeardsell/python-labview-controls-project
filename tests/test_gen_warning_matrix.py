"""Expected-trip computation for tools/gen_warning_matrix.py — the manifest's
ERROR/WARNING/clean calls must follow the confirmed Pcyl_Diag metric definitions
(F3 map in docs/9049-openloop-audit.md), or the bench drill compares against
nonsense."""

import xml.etree.ElementTree as ET

from tools.gen_warning_matrix import (
    FLAG_FIELD,
    drill_thresholds,
    expected_trips,
    render_drill_xml,
)

THR = {
    "MaxPCylMax": (200.0, 220.0),
    "MaxIMEPstd": (0.2, 0.3),
    "MaxDevFromAvg": (0.5, 0.8),
    "MaxDevFromSelfAvg": (0.5, 0.8),
    "MaxDevFromExpectedIMEP": (10.0, 15.0),
    "MAPOmax": (0.75, 1.25),
    "CA50max": (18.0, 23.0),
}


def _truth(cycles):
    """Build a truth dict from {cycle: {cyl: (imep_g, imep_n, pmax, ca50|None)}}."""
    out = {"cycles": {}}
    for cyc, cyls in cycles.items():
        rec = {}
        for cyl, (g, n, p, ca) in cyls.items():
            d = {"fired": ca is not None, "imep_g_bar": g, "imep_n_bar": n, "pmax_bar": p}
            if ca is not None:
                d["ca50_atdc"] = ca
            rec[str(cyl)] = d
        out["cycles"][str(cyc)] = {"cylinders": rec}
    return out


def uniform(g, n, p, ca, ncyc=5):
    return _truth({c: {k: (g, n, p, ca) for k in range(1, 7)} for c in range(1, ncyc + 1)})


def test_motored_control_is_all_clean_and_ca50_observe():
    exp = expected_trips(uniform(-1.15, -1.21, 150.9, None), THR, 20, {}, motored=True)
    assert exp["late combustion"] == "observe"  # motored CA50 = noise, not asserted
    assert exp["knock"] == "clean"
    assert all(v == "clean" for f, v in exp.items() if f not in ("late combustion",))


def test_fired_is_clean_because_misfire_checks_are_one_sided():
    """F3d: with Expected IMEP = 0 the misfire-from-IMEP check is one-sided
    LOW-side (IMEP <= 0 - thr) -> healthy firing (+25.8) can never trip it."""
    exp = expected_trips(uniform(26.0, 25.8, 178.0, 12.9), THR, 20, {}, motored=False)
    assert exp["misfire from IMEP"] == "clean"  # high IMEP is invisible to it
    assert exp["maximum pressure"] == "clean" and exp["late combustion"] == "clean"
    assert exp["misfire cyl-to-cyl"] == "clean" and exp["cyclic variability"] == "clean"


def test_misfire_from_imep_trips_only_below_reference():
    # IMEPn = -20: (0 - (-20)) = 20 > 15 -> ERROR (the only way this check fires)
    exp = expected_trips(uniform(-19.0, -20.0, 150.0, None), THR, 20, {}, motored=True)
    assert exp["misfire from IMEP"] == "ERROR"


def test_levels_overpressure_and_warning_band():
    assert expected_trips(uniform(26, 25.8, 230.0, 12.9), THR, 20, {}, False)[
        "maximum pressure"] == "ERROR"          # > 220
    assert expected_trips(uniform(26, 25.8, 210.0, 12.9), THR, 20, {}, False)[
        "maximum pressure"] == "WARNING"        # 200 < p <= 220


def test_misfire_trips_both_deviations_and_variability():
    cycles = {c: {k: (26.0, 25.8, 178.0, 12.9) for k in range(1, 7)} for c in range(1, 6)}
    cycles[3][4] = (-1.15, -1.21, 150.9, None)  # cyl 4 dead in cycle 3
    exp = expected_trips(_truth(cycles), THR, 20, {}, motored=False)
    assert exp["misfire cyl-to-cyl"] == "ERROR"    # dev from cycle mean >> 0.8
    assert exp["misfire self reg"] == "ERROR"      # dev from own running mean
    assert exp["cyclic variability"] == "ERROR"    # running std jumps
    assert exp["late combustion"] == "clean"       # surviving CA50s are on time


def test_knock_asserted_from_injection_spec():
    t = uniform(26.0, 25.8, 178.0, 12.9)
    assert expected_trips(t, THR, 20, {2: 2.5}, False)["knock"] == "ERROR"   # 2.5 > 1.25
    assert expected_trips(t, THR, 20, {2: 1.0}, False)["knock"] == "WARNING"  # 0.75..1.25
    assert expected_trips(t, THR, 20, {}, False)["knock"] == "observe"


def test_drill_thresholds_derive_from_fired_truth():
    thr = drill_thresholds(uniform(26.0, 25.8, 178.0, 12.9))
    assert thr["MaxPCylMax"] == (213.6, 231.4)     # peak*1.2 / *1.3
    assert thr["CA50max"] == (17.9, 22.9)          # max+5 / +10
    assert thr["MaxDevFromExpectedIMEP"] == (10.32, 15.48)  # mean*0.4 / *0.6
    assert thr["MaxIMEPstd"] == (0.2, 0.3)         # floors


def test_render_drill_xml_arms_every_field(tmp_path):
    template = open("parameter-files/CylWarningLevels.xml", encoding="utf-8").read()
    xml = render_drill_xml(template, THR, window=20)
    root = ET.fromstring(xml)
    ns = "{http://www.ni.com/LVData}"
    vals = {e.find(f"{ns}Name").text: e.find(f"{ns}Val").text
            for e in root.iter() if e.tag in (f"{ns}DBL", f"{ns}I32")}
    assert vals["samples for running IMEP std"] == "20"
    assert float(vals["CA50maxError [CADATDC]"]) == 23.0     # armed, not 1e6
    assert float(vals["MAPOmaxWarning [bar/CAD]"]) == 0.75
    assert len(vals) == 15 and all(float(v) < 1e6 for v in vals.values())
