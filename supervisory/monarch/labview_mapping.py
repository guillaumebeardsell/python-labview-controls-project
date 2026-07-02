"""LabVIEW cluster-label -> Python model-path mapping, and a structural diff.

`Flatten To JSON` on the LabVIEW `APC_ControlSettings` cluster emits keys equal
to the cluster's field *labels* (e.g. "Spark advance [CADBTDC]"), whereas the
Python model (control_settings.py) uses clean snake_case dotted paths (e.g.
"spark_advance_cadbtdc"). `LABEL_TO_PATH` is the bridge, keyed on each field's
innermost LabVIEW label so it works regardless of how LabVIEW nests the cluster.

`compare_flatten()` walks a real LabVIEW capture against the model and reports
what disagrees. This is what tools/compare_flatten.py runs; it's also the
canonical mapping the gateway VI will use to build/parse the wire JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .control_settings import ControlSettings

_PCR = "pid_control_references."

# LabVIEW innermost field label -> model dotted path.
LABEL_TO_PATH: dict[str, str] = {
    # --- ControlSettings top level ---
    "Spark advance [CADBTDC]": "spark_advance_cadbtdc",
    "Pref": "p_ref",
    "O2ref": "o2_ref",
    "DI advance [CADBTDC]": "di_advance_cadbtdc",
    "DI duration [ms] ": "di_duration_ms",  # NB: trailing space in the LabVIEW label
    "CO2ref": "co2_ref",
    "PFI duration [ms]": "pfi_duration_ms",
    "IMEP ref": "imep_ref",
    "Speed ref": "speed_ref",
    "IGN enable": "ign_enable",
    "DI enable": "di_enable",
    "CL PFI\n lambda": "cl_pfi_lambda",  # NB: embedded newline in the LabVIEW label
    "CL PFI\nIMEP": "cl_pfi_imep",  # NB: embedded newline
    "Activate\ncylinder": "activate_cylinder",  # NB: embedded newline
    "Force idling": "force_idling",
    "Force motoring": "force_motoring",
    "ETP resync": "force_etp_resync",
    "Requested mode": "requested_mode",
    "Clear Sync Errors": "clear_sync_errors",
    "toggle TDC": "toggle_tdc",
    "l ref": "lambda_ref",  # LabVIEW renders the "λ ref" label as "l ref"
    "CA50setpoint [CADATDC]": "ca50_setpoint_cadatdc",
    "CA50 control": "ca50_control",
    "Knock control": "knock_control",
    "CLEAR EMERGENCY STOP": "clear_emergency_stop",
    "EMERGENCY STOP": "emergency_stop",
    # --- PID control references: valves ---
    "NG": _PCR + "ng_valve",
    "Ar": _PCR + "ar_valve",
    "O2": _PCR + "o2_valve",
    "Intake vent": _PCR + "intake_vent",
    "Cross vent": _PCR + "cross_vent",
    "Exhaust vent": _PCR + "exhaust_vent",
    # --- NG channel ---
    "NG control mode": _PCR + "ng.mode",
    "NG-FC-001-REF": _PCR + "ng.ng_fc_001_ref",
    "WF-OA-002-REF": _PCR + "ng.wf_oa_002_ref",
    "IMEP-REF": _PCR + "ng.imep_ref",
    "Nm-REF": _PCR + "ng.nm_ref",
    # --- Ar channel ---
    "Ar control mode": _PCR + "ar.mode",
    "AR-PC-002-REF": _PCR + "ar.ar_pc_002_ref",
    "WF-PT-004-REF": _PCR + "ar.wf_pt_004_ref",
    # --- O2 channel ---
    "O2 control mode": _PCR + "o2.mode",
    "O2-FC-001-REF": _PCR + "o2.o2_fc_001_ref",
    "WF-OA-001-REF": _PCR + "o2.wf_oa_001_ref",
    # --- Tcoolant channel ---
    "Tcoolant control  mode": _PCR + "tcoolant.mode",  # NB: double space in the LabVIEW label
    "EC-FC-001-REF": _PCR + "tcoolant.ec_fc_001_ref",
    "EC-TT-001-REF": _PCR + "tcoolant.ec_tt_001_ref",
    # --- Texh channel ---
    "Texh control mode": _PCR + "texh.mode",
    "SW-FC-004-REF": _PCR + "texh.sw_fc_004_ref",
    "SW-FT-002-REF": _PCR + "texh.sw_ft_002_ref",
    "WF-TT-004-REF": _PCR + "texh.wf_tt_004_ref",
    # --- Toil channel ---
    "Toil control mode": _PCR + "toil.mode",
    "SW-FC-009-REF": _PCR + "toil.sw_fc_009_ref",
    "SW-FT-004-REF": _PCR + "toil.sw_ft_004_ref",
    "EO-TT-001-REF": _PCR + "toil.eo_tt_001_ref",
    "AIC201_CO2_ConcTarget": _PCR + "toil.aic201_co2_conc_target",
    # --- misc references ---
    "O2_FF_NG": _PCR + "o2_ff_ng",
    "Dyno control mode": _PCR + "dyno.mode",
    "Membrane control mode": _PCR + "membrane.mode",
    "AR-FT-001-REF": _PCR + "membrane.ar_ft_001_ref",
    "MTR modbus floats": _PCR + "mtr_modbus_floats",
    "MTR modbus u16": _PCR + "mtr_modbus_u16",
    "MTR HB": _PCR + "mtr_hb",
    "PC_HB": _PCR + "pc_hb",
    # This nested field flattens with label "EMERGENCY STOP" (its Boolean text is
    # "EMERGENCY STOP & VENT"), colliding with the top-level "EMERGENCY STOP".
    # A parent-qualified key ("parent/label") disambiguates; see compare_flatten.
    "PID control references/EMERGENCY STOP": _PCR + "emergency_stop_and_vent",
}


def _kind(value) -> str:
    if isinstance(value, bool):  # bool is a subclass of int — check first
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "string"
    return "other"


def flatten_leaves(obj, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], dict]:
    """Flatten a JSON-ish object to {path_tuple: leaf}. A list is one leaf
    (kind 'array', with length + element kind); scalars are leaves by kind.
    Nesting depth is irrelevant to callers that key on the innermost label."""
    out: dict[tuple[str, ...], dict] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten_leaves(v, prefix + (str(k),)))
    elif isinstance(obj, list):
        out[prefix] = {
            "kind": "array",
            "length": len(obj),
            "elem": _kind(obj[0]) if obj else None,
        }
    else:
        out[prefix] = {"kind": _kind(obj), "value": obj}
    return out


def model_leaves() -> dict[str, dict]:
    """Leaves of a default ControlSettings, keyed by dotted path."""
    dump = ControlSettings().model_dump(mode="json")
    return {".".join(p): leaf for p, leaf in flatten_leaves(dump).items()}


def resolve_label(path: tuple[str, ...]) -> str | None:
    """Model dotted path for a LabVIEW leaf at `path`. Tries a parent-qualified
    key ("parent/label") first — to disambiguate labels that repeat in different
    clusters (e.g. "EMERGENCY STOP") — then the bare innermost label."""
    if not path:
        return None
    label = path[-1]
    if len(path) >= 2:
        qualified = LABEL_TO_PATH.get(f"{path[-2]}/{label}")
        if qualified is not None:
            return qualified
    return LABEL_TO_PATH.get(label)


@dataclass
class Report:
    unmapped: list[tuple] = field(default_factory=list)       # (label, lv_path, kind) — LabVIEW has, model doesn't
    missing: list[str] = field(default_factory=list)          # dotted path — model has, capture didn't
    type_mismatch: list[tuple] = field(default_factory=list)  # (label, path, lv_kind, model_kind)
    array_mismatch: list[tuple] = field(default_factory=list) # (label, path, lv_len, model_len)
    booleans: list[tuple] = field(default_factory=list)       # (label, lv_path, value) — to resolve polarity
    arrays: list[tuple] = field(default_factory=list)         # (label, lv_path, length)

    @property
    def ok(self) -> bool:
        return not (self.unmapped or self.missing or self.type_mismatch or self.array_mismatch)


def compare_flatten(lv_obj) -> Report:
    """Diff a LabVIEW `Flatten To JSON` capture against the model contract."""
    model = model_leaves()
    rep = Report()
    covered: set[str] = set()

    for path, leaf in flatten_leaves(lv_obj).items():
        if not path:
            continue
        label = path[-1]
        lv_path = ".".join(path)
        if leaf["kind"] == "bool":
            rep.booleans.append((label, lv_path, leaf["value"]))
        if leaf["kind"] == "array":
            rep.arrays.append((label, lv_path, leaf["length"]))

        model_path = resolve_label(path)
        if model_path is None or model_path not in model:
            rep.unmapped.append((label, lv_path, leaf["kind"]))
            continue
        covered.add(model_path)
        m = model[model_path]
        if leaf["kind"] != m["kind"]:
            rep.type_mismatch.append((label, model_path, leaf["kind"], m["kind"]))
        elif leaf["kind"] == "array" and leaf.get("length") != m.get("length"):
            rep.array_mismatch.append((label, model_path, leaf.get("length"), m.get("length")))

    rep.missing = sorted(p for p in model if p not in covered)
    return rep
