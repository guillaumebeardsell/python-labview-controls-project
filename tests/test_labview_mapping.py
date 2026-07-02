"""Tests for the LabVIEW label<->model mapping and the structural diff tool.

The self-test synthesizes a LabVIEW-style capture from the model itself, so we
can verify compare_flatten() reports "agree" on a faithful capture and flags
each class of discrepancy on a mutated one — before it's ever run on real data.
"""

from supervisory.monarch.control_settings import ControlSettings
from supervisory.monarch.labview_mapping import (
    LABEL_TO_PATH,
    compare_flatten,
    flatten_leaves,
    model_leaves,
)


def test_mapping_covers_exactly_the_model_leaves():
    # Every model leaf has a label, and no label points to a nonexistent leaf.
    assert set(LABEL_TO_PATH.values()) == set(model_leaves().keys())


def test_labels_are_unique():
    assert len(LABEL_TO_PATH) == len(set(LABEL_TO_PATH))


def _faithful_labview_capture() -> dict:
    """A flat {label: value} object equivalent to what LabVIEW would flatten —
    compare_flatten keys on the innermost label, so flatness is fine."""
    path_to_label = {v: k for k, v in LABEL_TO_PATH.items()}
    capture: dict = {}
    for dotted, leaf in model_leaves().items():
        label = path_to_label[dotted]
        if leaf["kind"] == "array":
            value: object = [0] * leaf["length"]
        elif leaf["kind"] == "bool":
            value = False
        elif leaf["kind"] == "number":
            value = 0
        else:
            value = ""
        # A parent-qualified mapping key ("parent/label") is nested, exercising
        # resolve_label's qualified lookup; bare labels sit at the top level.
        if "/" in label:
            parent, leaf_label = label.split("/", 1)
            capture.setdefault(parent, {})[leaf_label] = value
        else:
            capture[label] = value
    return capture


def test_faithful_capture_agrees():
    rep = compare_flatten(_faithful_labview_capture())
    assert rep.ok
    assert not rep.unmapped and not rep.missing
    assert not rep.type_mismatch and not rep.array_mismatch


def test_detects_extra_field():
    cap = _faithful_labview_capture()
    cap["Some New LabVIEW Field"] = 1.0
    rep = compare_flatten(cap)
    assert any(label == "Some New LabVIEW Field" for label, *_ in rep.unmapped)
    assert not rep.ok


def test_detects_missing_field():
    cap = _faithful_labview_capture()
    del cap["Speed ref"]
    rep = compare_flatten(cap)
    assert "speed_ref" in rep.missing
    assert not rep.ok


def test_detects_type_mismatch():
    cap = _faithful_labview_capture()
    cap["EMERGENCY STOP"] = 0  # number where the model expects a bool
    rep = compare_flatten(cap)
    assert any(p == "emergency_stop" for _, p, *_ in rep.type_mismatch)
    assert not rep.ok


def test_detects_array_length_mismatch():
    cap = _faithful_labview_capture()
    # look the label up (it contains an embedded newline) rather than hardcode it
    label = next(k for k, v in LABEL_TO_PATH.items() if v == "activate_cylinder")
    cap[label] = [False] * 4  # model expects 6
    rep = compare_flatten(cap)
    assert any(p == "activate_cylinder" for _, p, *_ in rep.array_mismatch)
    assert not rep.ok


def test_reports_booleans_and_arrays_for_review():
    rep = compare_flatten(_faithful_labview_capture())
    # vents show up in the boolean review list, arrays in the array list
    assert any(label == "Intake vent" for label, *_ in rep.booleans)
    assert any(label == "MTR modbus floats" for label, *_ in rep.arrays)


def test_handles_nested_capture():
    # Even if LabVIEW nests the PID references as a sub-object, leaf-label
    # matching still works.
    cap = {"IGN enable": True, "PID control references": {"NG": False, "MTR HB": True}}
    rep = compare_flatten(cap)
    # these three are known labels -> not unmapped
    unmapped_labels = {label for label, *_ in rep.unmapped}
    assert "IGN enable" not in unmapped_labels
    assert "NG" not in unmapped_labels
    assert "MTR HB" not in unmapped_labels
