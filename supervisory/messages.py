"""Message models for the Python <-> LabVIEW gateway link.

One class per ICD message type (docs/icd.md section 4). Pydantic gives us
validation on parse, so a malformed or unknown message raises ValidationError
at the link layer instead of propagating garbage into the engine. Unknown
fields are ignored (ICD section 3, forward compatibility).
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

ParamValue = Union[float, int, bool, str]


class Telemetry(BaseModel):
    """LabVIEW -> Python plant snapshot, 1 Hz. Doubles as LabVIEW's heartbeat."""

    type: Literal["telemetry"] = "telemetry"
    seq: int
    ts: float
    mode: str
    channels: dict[str, float] = Field(default_factory=dict)
    flags: dict[str, bool] = Field(default_factory=dict)


class Command(BaseModel):
    """Python -> LabVIEW request. LabVIEW validates and may reject it."""

    type: Literal["command"] = "command"
    id: int
    name: str
    params: dict[str, ParamValue] = Field(default_factory=dict)


class CommandAck(BaseModel):
    """LabVIEW -> Python validation result. Not confirmation of effect —
    effects are confirmed by observing telemetry."""

    type: Literal["command_ack"] = "command_ack"
    id: int
    accepted: bool
    reason: str = ""


class Heartbeat(BaseModel):
    """Python -> LabVIEW liveness, 1 Hz. LabVIEW safe-holds when it lapses."""

    type: Literal["heartbeat"] = "heartbeat"
    seq: int
    ts: float


Message = Annotated[
    Union[Telemetry, Command, CommandAck, Heartbeat],
    Field(discriminator="type"),
]

_adapter: TypeAdapter[Message] = TypeAdapter(Message)


def parse(line: bytes | str) -> Message:
    """Parse one JSON message. Raises pydantic.ValidationError on malformed
    input or unknown message type."""
    return _adapter.validate_json(line)


def dump(msg: BaseModel) -> str:
    """Serialize a message to a single JSON line (terminator not included)."""
    return msg.model_dump_json()
