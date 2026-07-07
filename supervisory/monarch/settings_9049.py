"""The 9049_ControlSettings contract — the 9049-side command/state echo.

Written by `APC_9049_ControlSettingsRaster.vi` on cRIO-9049 and published to
the PC and 9056 (network shared variable `9049_ControlSettings`). Field list
from the Data Logging doc's CRIO9049 command table + the architecture overview
(p.27); this is the engine-synchronous side's view of state + spark/injection
commands — needed by Phase C at the latest for observing what the 9049 is
actually acting on.

STATUS: transcribed from documentation, **not yet confirmed against a live
flatten** (the ControlSettings workflow applies: when the gateway starts
forwarding this variable, capture one flatten and extend
tools/compare_flatten.py's approach — the field labels here are the doc's
variable names and may differ from the cluster's real labels).
"""

from __future__ import annotations

from pydantic import BaseModel

from .control_settings import SystemState


class Settings9049(BaseModel):
    """9049_ControlSettings: state + injection/ignition command echo."""

    system_state: SystemState = SystemState.STAND_BY  # "SystemState_i8"
    injection_state: bool = False  # "InjectionState_b"
    inj_enable: bool = False  # "InjEnable_b"
    main_enable: bool = False  # "MainEnable_b"
    main_duration_ms: float = 0.0  # "MainDuration_ms"
    main_soi_cadbtdc: float = 0.0  # "MainSOI_CADBTDC"
    spark_enable: bool = False  # "SparkEnable_b"
    spark_timing_cadbtdc: float = 0.0  # "SparkTiming_CADBTDC"
    engine_speed_rpm: float = 0.0  # "Speed(RPM)" per the overview p.27
    ts: float = 0.0  # timestamp (doc lists timestamps; exact label TBD)

    def consistent_with_state(self) -> bool:
        """The 9049 enable gate (overview p.18): spark/injection may only be
        enabled when SYSTEMSTATE >= 2. Useful as a shadow cross-check."""
        if int(self.system_state) < 2:
            return not (self.spark_enable or self.inj_enable or self.main_enable)
        return True
