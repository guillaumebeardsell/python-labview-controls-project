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
    """One decoded 1 Hz telemetry frame."""

    type: str = "telemetry"
    seq: int
    ts: float
    system_state: SystemState
    settings: ControlSettings
    unmapped: tuple[str, ...] = ()  # LabVIEW labels with no model field (should be empty)


def parse_monarch_telemetry(obj: dict) -> MonarchTelemetry:
    """Build a MonarchTelemetry from a decoded telemetry envelope dict."""
    settings, unmapped = control_settings_from_labview(obj.get("settings", {}))
    return MonarchTelemetry(
        seq=obj["seq"],
        ts=obj["ts"],
        system_state=obj["system_state"],
        settings=settings,
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
