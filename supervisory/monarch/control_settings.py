"""The MONARCH ControlSettings data contract.

Transcribed from two LabVIEW typedefs (both last modified 2025-12-18):
  - APC_ControlSettings.ctl      -> ControlSettings (top-level)
  - APC_PIDcontrolSettings.ctl   -> PidControlReferences (embedded cluster)

This is the `PC_ControlSettings` the UI sends and, in limited form, the
`Limited_ControlSettings` the StateMachine emits. It's the payload the first
real state-machine port (APC_9056_StateMachine) reads and writes.

Contract conventions:
  * JSON keys are clean snake_case defined here, NOT LabVIEW's raw field labels.
    Each field's originating LabVIEW label is given in a trailing comment so the
    gateway VI can map cluster elements to these keys (e.g. with JSONtext).
  * LabVIEW DBL and SGL both serialize to JSON number -> Python `float`; the
    exact float width is irrelevant over JSON. Modes/enums are I8 -> `int`.
  * Unknown JSON keys are ignored (pydantic default), matching ICD section 3
    forward-compatibility.

INFERENCES TO CONFIRM against a live LabVIEW `Flatten To JSON` of the cluster:
  * Boolean polarity. The diagram note states venting valves use 1=closed,
    0=open; NG/Ar/O2 feed-valve polarity is not yet confirmed. Defaults below
    are provisional and must be checked before Python has any authority.
  * Whether each actuator's reference values are a LabVIEW sub-cluster (modeled
    here as a per-channel object) or flat siblings of its `*_control_mode`.
  * Array lengths (activate_cylinder, mtr_modbus_floats, mtr_modbus_u16) are
    taken from the panel and validated loosely, not pinned.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field


class SystemState(IntEnum):
    """The system state / requested-mode enum (LabVIEW I8), shared by
    CURRENT SYSTEM STATE, SYSTEM STATE, and Requested mode. Values from the
    StateMachine's MODES legend."""

    SAFE = -1
    STAND_BY = 0  # default
    MOTORING = 1
    IDLING = 2
    FIRING = 3


# Per-actuator "control mode" is a plain int, not a fixed enum: the base legend
# is 0=safe, 1=open-loop (or alternate for binary actuators), 2=closed-loop, but
# the MAX-LEVEL-OF-CONTROL table caps some actuators higher (temps to 3, NG feed
# to 6 in FIRING). Modeling as int keeps every valid cap representable.


class NgChannel(BaseModel):
    """Natural-gas feed control channel."""

    mode: int = 0  # "NG control mode"
    ng_fc_001_ref: float = 0.0  # "NG-FC-001-REF"
    wf_oa_002_ref: float = 0.0  # "WF-OA-002-REF"
    imep_ref: float = 0.0  # "IMEP-REF"
    nm_ref: float = 0.0  # "Nm-REF"


class ArChannel(BaseModel):
    """Argon feed control channel."""

    mode: int = 0  # "Ar control mode"
    ar_pc_002_ref: float = 0.0  # "AR-PC-002-REF"
    wf_pt_004_ref: float = 0.0  # "WF-PT-004-REF"


class O2Channel(BaseModel):
    """Oxygen feed control channel."""

    mode: int = 0  # "O2 control mode"
    o2_fc_001_ref: float = 0.0  # "O2-FC-001-REF"
    wf_oa_001_ref: float = 0.0  # "WF-OA-001-REF"


class TcoolantChannel(BaseModel):
    """Coolant temperature control channel."""

    mode: int = 0  # "Tcoolant control mode"
    ec_fc_001_ref: float = 0.0  # "EC-FC-001-REF"
    ec_tt_001_ref: float = 0.0  # "EC-TT-001-REF"


class TexhChannel(BaseModel):
    """Exhaust temperature control channel."""

    mode: int = 0  # "Texh control mode"
    sw_fc_004_ref: float = 0.0  # "SW-FC-004-REF"
    sw_ft_002_ref: float = 0.0  # "SW-FT-002-REF"
    wf_tt_004_ref: float = 0.0  # "WF-TT-004-REF"


class ToilChannel(BaseModel):
    """Oil temperature control channel."""

    mode: int = 0  # "Toil control mode"
    sw_fc_009_ref: float = 0.0  # "SW-FC-009-REF"
    sw_ft_004_ref: float = 0.0  # "SW-FT-004-REF"
    eo_tt_001_ref: float = 0.0  # "EO-TT-001-REF"
    aic201_co2_conc_target: float = 0.0  # "AIC201_CO2_ConcTarget"


class DynoChannel(BaseModel):
    """Dynamometer control channel (no reference values listed in the typedef)."""

    mode: int = 0  # "Dyno control mode"


class MembraneChannel(BaseModel):
    """O2-separation membrane control channel."""

    mode: int = 0  # "Membrane control mode"
    ar_ft_001_ref: float = 0.0  # "AR-FT-001-REF"


class PidControlReferences(BaseModel):
    """The embedded "PID control references" cluster (APC_PIDcontrolSettings.ctl):
    the gas/thermal/plant-side control targets and MTR (Modbus) I/O."""

    # Feed and vent valve commands. Polarity provisional (see module docstring);
    # the diagram states vents use 1=closed, 0=open.
    ng_valve: bool = False  # "NG"
    ar_valve: bool = False  # "Ar"
    o2_valve: bool = False  # "O2"
    intake_vent: bool = False  # "Intake vent"  (False = open)
    cross_vent: bool = False  # "Cross vent"
    exhaust_vent: bool = False  # "Exhaust vent"

    ng: NgChannel = Field(default_factory=NgChannel)
    ar: ArChannel = Field(default_factory=ArChannel)
    o2: O2Channel = Field(default_factory=O2Channel)
    tcoolant: TcoolantChannel = Field(default_factory=TcoolantChannel)
    texh: TexhChannel = Field(default_factory=TexhChannel)
    toil: ToilChannel = Field(default_factory=ToilChannel)

    o2_ff_ng: bool = False  # "O2_FF_NG" (feed-forward O2 from NG)
    dyno: DynoChannel = Field(default_factory=DynoChannel)
    membrane: MembraneChannel = Field(default_factory=MembraneChannel)

    mtr_modbus_floats: list[float] = Field(default_factory=lambda: [0.0] * 19)  # "MTR modbus floats"
    mtr_modbus_u16: list[int] = Field(default_factory=lambda: [0] * 7)  # "MTR modbus u16" (confirmed 7 from live capture)

    mtr_hb: bool = False  # "MTR HB" (MTR heartbeat)
    pc_hb: bool = False  # "PC_HB" (PC heartbeat)
    emergency_stop_and_vent: bool = False  # "EMERGENCY STOP & VENT"


class ControlSettings(BaseModel):
    """The full APC_ControlSettings cluster: engine control setpoints/enables,
    the embedded PID references, and the CA50/knock/emergency-stop fields."""

    # --- Engine control setpoints (floats) ---
    spark_advance_cadbtdc: float = 0.0  # "Spark advance [CADBTDC]"
    p_ref: float = 0.0  # "Pref"
    o2_ref: float = 0.0  # "O2ref"
    di_advance_cadbtdc: float = 0.0  # "DI advance [CADBTDC]"
    di_duration_ms: float = 0.0  # "DI duration [ms]"
    co2_ref: float = 0.0  # "CO2ref"
    pfi_duration_ms: float = 0.0  # "PFI duration [ms]"
    imep_ref: float = 0.0  # "IMEP ref"
    speed_ref: float = 1800.0  # "Speed ref"

    # --- Enables and mode requests ---
    ign_enable: bool = False  # "IGN enable"
    di_enable: bool = False  # "DI enable"
    cl_pfi_lambda: bool = False  # "CL PFI lambda" (closed-loop PFI on lambda)
    cl_pfi_imep: bool = False  # "CL PFI IMEP" (closed-loop PFI on IMEP)
    activate_cylinder: list[bool] = Field(default_factory=lambda: [False] * 6)  # "Activate cylinder"
    force_idling: bool = False  # "Force idling" (FORCE IDLING (CUT PFI))
    force_motoring: bool = False  # "Force motoring" (FORCE MOTORING (CUT PFI, DI and IGN))
    force_etp_resync: bool = False  # "ETP resync" (FORCE ETP RESYNCH)
    requested_mode: SystemState = SystemState.STAND_BY  # "Requested mode"
    clear_sync_errors: bool = False  # "Clear Sync Errors"
    toggle_tdc: bool = False  # "toggle TDC"
    lambda_ref: float = 0.0  # "λ ref"

    # --- Embedded gas/thermal/plant references ---
    pid_control_references: PidControlReferences = Field(default_factory=PidControlReferences)

    # --- Combustion-phasing control and emergency stop ---
    ca50_setpoint_cadatdc: float = 0.0  # "CA50setpoint [CADATDC]"
    ca50_control: bool = False  # "CA50 control"
    knock_control: bool = False  # "Knock control"
    clear_emergency_stop: bool = False  # "CLEAR EMERGENCY STOP"
    emergency_stop: bool = False  # "EMERGENCY STOP"
