# MONARCH ControlSettings — Data Contract v0

The `ControlSettings` cluster is the payload the supervisory layer works in:
the UI sends `PC_ControlSettings`, and `APC_9056_StateMachine` emits a limited
form as `Limited_ControlSettings`. This is the contract for the first real
state-machine port.

- **Source of truth:** LabVIEW typedefs `APC_ControlSettings.ctl` and (embedded)
  `APC_PIDcontrolSettings.ctl`, both last modified 2025-12-18, exported under
  `original-labview-codebase/`.
- **Python model:** `supervisory/monarch/control_settings.py`.
- **Tests:** `tests/test_control_settings.py` (round trip, nesting, enum encoding,
  forward-compat).

## Conventions

- **JSON keys are clean snake_case** defined by the Python model, not LabVIEW's
  raw field labels. Every field carries its LabVIEW label in a code comment; the
  gateway VI maps cluster elements to these keys (JSONtext makes this a data
  step, not a diagram change). Keeping the keys language-neutral avoids baking
  LabVIEW's spaces/units/brackets into the wire format.
- **Types:** LabVIEW DBL and SGL both become JSON numbers → Python `float`
  (width is irrelevant over JSON). Modes and the state enum are I8 → `int`.
  Arrays → lists. The one nested cluster (`pid_control_references`) → a nested
  object.
- **Unknown keys are ignored** on parse (ICD §3, forward compatibility).

## State enum (`SystemState`)

Shared by `CURRENT SYSTEM STATE`, `SYSTEM STATE`, and `Requested mode`
(LabVIEW I8):

| Value | Name |
|---|---|
| −1 | SAFE |
| 0 | STAND_BY (default) |
| 1 | MOTORING |
| 2 | IDLING |
| 3 | FIRING |

## Per-actuator control mode

`*_control_mode` fields are plain `int`, not a fixed enum. Base legend:
`0 = safe`, `1 = open-loop` (or the alternate state for binary actuators),
`2 = closed-loop`. The MAX-LEVEL-OF-CONTROL table caps some actuators higher
(temps to 3, NG feed to 6 in FIRING), so the field must represent 0..6.

## Structure

Top-level `ControlSettings`: engine setpoints (spark/DI/PFI/IMEP/speed…),
enables (IGN/DI, closed-loop PFI, per-cylinder activation), mode requests
(`requested_mode`, force idling/motoring, ETP resync), `lambda_ref`, the nested
`pid_control_references`, and the CA50/knock/emergency-stop fields.

Nested `PidControlReferences`: feed/vent valve commands, per-actuator channels
(NG, Ar, O2, Tcoolant, Texh, Toil, Dyno, Membrane) each with a `mode` plus named
plant-tag reference values, the MTR Modbus float/u16 arrays, and MTR/PC
heartbeats plus `EMERGENCY STOP & VENT`.

## Confirmed against a live capture (2026-07-02)

A real LabVIEW `Flatten To JSON` capture
(`original-labview-codebase/control_settings_flatten.txt`) was diffed against the
model with `tools/compare_flatten.py` → **RESULT: AGREE**. All 64 leaf fields
match on name, type, and structure. What the capture resolved:

1. **Array lengths — pinned.** `activate_cylinder` = 6, `mtr_modbus_floats` = 19,
   `mtr_modbus_u16` = **7** (was modeled as 6; corrected).
2. **`Requested mode`** flattens as a **number** (−1..3), matching the model's
   `int`/`SystemState`. No string-enum handling needed.
3. **Reference grouping.** LabVIEW nests `PID control references` as a sub-object
   but keeps each actuator's `*_control_mode` and its `*-REF` values as **flat
   siblings** (not per-channel sub-clusters). The model groups them into channel
   objects; the diff tool matches by innermost label, and the mapping bridges the
   two, so this is purely a gateway-side mapping detail.
4. **`PFI advance`** confirmed absent — the current cluster has only
   `PFI duration [ms]`, as modeled.

### LabVIEW label quirks absorbed by the mapping

The real field labels contain oddities that `LABEL_TO_PATH` now matches exactly,
so the clean snake_case wire keys are unaffected:

- Embedded newlines: `"CL PFI\n lambda"`, `"CL PFI\nIMEP"`, `"Activate\ncylinder"`.
- Stray spaces: `"DI duration [ms] "` (trailing), `"Tcoolant control  mode"` (double).
- `"l ref"` (LabVIEW renders `λ` as `l`).
- The nested e-stop field flattens as label `"EMERGENCY STOP"` (Boolean text
  "EMERGENCY STOP & VENT"), colliding with the top-level `"EMERGENCY STOP"`;
  disambiguated by a parent-qualified mapping key.

### Boolean polarity

The capture was taken with `Requested mode = SAFE` and all valve booleans
`false`. Per the MAX-LEVEL-OF-CONTROL table the SAFE column is vents *open*,
feeds *closed*, so **`false` = the safe position** for both: vents `false = open`
(consistent with the diagram's `1 = closed`), feed valves `false = closed`
(hence `true = open`). This matches the model defaults (all `false`). Worth a
second capture in an active state (e.g. FIRING, vents commanded closed) to
remove any doubt before the limiting logic relies on it — polarity affects the
limiter port (Phase A1 of `docs/migration-plan.md`), not the contract structure.
