"""MONARCH-specific message payloads (Argon Power Cycle engine).

The generic transport/engine in the parent `supervisory` package knows nothing
about MONARCH; project-specific data contracts live here. This keeps the
framework reusable and the engine testable without engine-domain types.

Currently: the `ControlSettings` cluster (docs/monarch-control-settings.md),
transcribed from the LabVIEW typedefs APC_ControlSettings.ctl and
APC_PIDcontrolSettings.ctl.
"""

from .control_settings import (
    ArChannel,
    ControlSettings,
    DynoChannel,
    MembraneChannel,
    NgChannel,
    O2Channel,
    PidControlReferences,
    SystemState,
    TcoolantChannel,
    TexhChannel,
    ToilChannel,
)

__all__ = [
    "ArChannel",
    "ControlSettings",
    "DynoChannel",
    "MembraneChannel",
    "NgChannel",
    "O2Channel",
    "PidControlReferences",
    "SystemState",
    "TcoolantChannel",
    "TexhChannel",
    "ToilChannel",
]
