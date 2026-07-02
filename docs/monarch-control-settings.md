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

## Open questions — confirm against a live `Flatten To JSON`

These do not affect the serialization mechanism (tests pass), but must be
resolved before Python has any authority:

1. **Boolean polarity.** The diagram states venting valves use `1 = closed,
   0 = open`. NG/Ar/O2 feed-valve polarity is unconfirmed. Model defaults are
   provisional.
2. **Reference grouping.** Whether each actuator's reference values are a true
   LabVIEW sub-cluster (modeled here as a per-channel object) or flat siblings
   of the `*_control_mode` element. Affects only how the gateway maps them.
3. **Array lengths.** `activate_cylinder` (6), `mtr_modbus_floats` (19),
   `mtr_modbus_u16` (6) are read off the panel, not pinned.
4. **`PFI advance`.** An older StateMachine panel listed a `PFI advance`
   field; the current typedef has only `PFI duration [ms]`. Modeled per the
   current typedef.

The cleanest way to close all four at once: on the gateway, `Flatten To JSON`
the real cluster once and diff its output against `ControlSettings().model_dump_json()`.
