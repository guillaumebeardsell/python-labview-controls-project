"""MONARCH telemetry envelope: the real 1 Hz payload from the LabVIEW gateway.

Stage 1 streams the actual control-settings cluster plus the system state, so
Python ingests fully-decoded engine telemetry read-only. The gateway sends:

    {"type":"telemetry","seq":N,"ts":T,"system_state":S,"settings":{<flatten>}}

where `settings` is a raw LabVIEW `Flatten To JSON` of the ControlSettings
cluster (quirky field labels and all). Python maps it to the ControlSettings
model via labview_mapping — so the gateway VI just flattens and sends, no
key-renaming on the LabVIEW side.

`monarch_parser` is the drop-in parser for TcpPlantLink: telemetry lines become
MonarchTelemetry; other message types fall back to the generic messages.parse
(so heartbeats/acks still work on the same link).
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from ..messages import Message
from ..messages import parse as parse_generic
from .control_settings import ControlSettings, SystemState
from .labview_mapping import control_settings_from_labview


class MonarchTelemetry(BaseModel):
    """One decoded 1 Hz telemetry frame.

    `system_state` and `settings` (PC_ControlSettings) are always present. The
    remaining fields are the rest of the StateMachine I/O that lives *outside*
    the cluster; they're optional so a Stage-1 gateway (which sends only
    system_state + settings) still decodes, and they start populating the moment
    the gateway pre-wires them for Stage-2 shadow mode.
    """

    type: str = "telemetry"
    seq: int
    ts: float
    system_state: SystemState
    settings: ControlSettings  # PC_ControlSettings (what was requested)

    # Shadow-mode extras (StateMachine I/O not in the cluster; optional):
    warnings_limit: int | None = None  # STATE LIMITATION FROM WARNINGS (max state warnings allow)
    manual_state: int | None = None  # ManualState override input
    force_state: bool | None = None  # ForceState override input
    limited_settings: ControlSettings | None = None  # Limited_ControlSettings (what was allowed)
    command_source: str | None = None  # "UI" | "PYTHON" — who writes PC_ControlSettings (ICD v0.2)

    unmapped: tuple[str, ...] = ()  # LabVIEW labels with no model field (should be empty)


def parse_monarch_telemetry(obj: dict) -> MonarchTelemetry:
    """Build a MonarchTelemetry from a decoded telemetry envelope dict."""
    settings, unmapped = control_settings_from_labview(obj.get("settings", {}))
    limited = None
    if obj.get("limited_settings") is not None:
        limited, lim_unmapped = control_settings_from_labview(obj["limited_settings"])
        unmapped = unmapped + ["limited_settings/" + u for u in lim_unmapped]
    return MonarchTelemetry(
        seq=obj["seq"],
        ts=obj["ts"],
        system_state=obj["system_state"],
        settings=settings,
        warnings_limit=obj.get("warnings_limit"),
        manual_state=obj.get("manual_state"),
        force_state=obj.get("force_state"),
        limited_settings=limited,
        command_source=obj.get("command_source"),
        unmapped=tuple(unmapped),
    )


def monarch_parser(line: bytes | str) -> Message | MonarchTelemetry:
    """Parser for TcpPlantLink: MONARCH telemetry -> MonarchTelemetry, everything
    else -> the generic message types. Raises on malformed input (the link
    treats that as a discardable bad line)."""
    obj = json.loads(line)
    if isinstance(obj, dict) and obj.get("type") == "telemetry":
        return parse_monarch_telemetry(obj)
    return parse_generic(line)
