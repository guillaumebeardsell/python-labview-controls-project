"""The 9049_ControlSettings contract — the 9049-side command/state echo.

Written by `APC_9049_ControlSettingsRaster.vi` on cRIO-9049 and published to
the PC and 9056 (network shared variable `9049_ControlSettings`). This is the
engine-synchronous side's view of state + spark/injection commands — needed by
Phase C at the latest for observing what the 9049 is actually acting on.

STATUS: **wire layout confirmed** from the full-res block-diagram print of the
Raster VI (original-labview-codebase/APC_9049_ControlSettingsRaster/,
2026-07-07). The shared variable is a flat **SGL array of 8 elements** built in
this order (booleans encoded 1/0 via the VI's `?1:0` converters):

    [0] 9049 STATE (U8)          -> system_state
    [1] InjectionEnable (TF)     -> inj_enable
    [2] MainEnable (TF)          -> main_enable      (from PlsGen_Time_Config_In)
    [3] MainDuration (msec)      -> main_duration_ms (from PlsGen_Time_Config_In)
    [4] MainSOI (DBTDC)          -> main_soi_cadbtdc (from PlsGen_Time_Config_In)
    [5] SparkEnable (TF)         -> spark_enable
    [6] SparkTiming (DBTDC) loc  -> spark_timing_cadbtdc
    [7] Speed (RPM)              -> engine_speed_rpm

No timestamp and only one injection flag are on the wire — the extra
`InjectionState_b`/`TimeStamp*` columns in the Data Logging doc are logging
additions, not part of this shared variable. Still pending: confirmation
against a live capture once the 9049 runs (values/scaling).
"""

from __future__ import annotations

from pydantic import BaseModel

from .control_settings import SystemState


class Settings9049(BaseModel):
    """9049_ControlSettings: state + injection/ignition command echo."""

    system_state: SystemState = SystemState.STAND_BY  # [0] "9049 STATE"
    inj_enable: bool = False  # [1] "InjectionEnable"
    main_enable: bool = False  # [2] "MainEnable"
    main_duration_ms: float = 0.0  # [3] "MainDuration (msec)"
    main_soi_cadbtdc: float = 0.0  # [4] "MainSOI (DBTDC)"
    spark_enable: bool = False  # [5] "SparkEnable"
    spark_timing_cadbtdc: float = 0.0  # [6] "SparkTiming (DBTDC) loc"
    engine_speed_rpm: float = 0.0  # [7] "Speed (RPM)"

    @classmethod
    def from_array(cls, values: list[float]) -> "Settings9049":
        """Decode the raw 8-element SGL array as published on the wire."""
        if len(values) < 8:
            raise ValueError(f"9049_ControlSettings needs 8 elements, got {len(values)}")
        return cls(
            system_state=SystemState(int(values[0])),
            inj_enable=values[1] != 0,
            main_enable=values[2] != 0,
            main_duration_ms=values[3],
            main_soi_cadbtdc=values[4],
            spark_enable=values[5] != 0,
            spark_timing_cadbtdc=values[6],
            engine_speed_rpm=values[7],
        )

    def to_array(self) -> list[float]:
        """Encode back to the wire layout (inverse of from_array)."""
        return [
            float(int(self.system_state)),
            1.0 if self.inj_enable else 0.0,
            1.0 if self.main_enable else 0.0,
            self.main_duration_ms,
            self.main_soi_cadbtdc,
            1.0 if self.spark_enable else 0.0,
            self.spark_timing_cadbtdc,
            self.engine_speed_rpm,
        ]

    def consistent_with_state(self) -> bool:
        """The 9049 enable gate (overview p.18): spark/injection may only be
        enabled when SYSTEMSTATE >= 2. Useful as a shadow cross-check."""
        if int(self.system_state) < 2:
            return not (self.spark_enable or self.inj_enable or self.main_enable)
        return True
