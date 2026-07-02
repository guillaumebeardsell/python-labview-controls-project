"""Python supervisory layer for the LabVIEW-based controls stack.

LabVIEW permanently owns hardware access, hard safety interlocks, command
validation, and safe fallback behavior. This package owns supervisory state
machines and decision logic, and talks to the LabVIEW gateway over the
localhost TCP link defined in docs/icd.md. Every command it sends is a
request that LabVIEW is free to reject.
"""

from .engine import CommandRequest, PlantView, StateMachine, Supervisor
from .link import PlantLink, TcpPlantLink
from .messages import Command, CommandAck, Heartbeat, Message, Telemetry, dump, parse
from .recorder import NullRecorder, Recorder
from .sim import SimPlant, SimPlantLink

__all__ = [
    "Command",
    "CommandAck",
    "CommandRequest",
    "Heartbeat",
    "Message",
    "NullRecorder",
    "PlantLink",
    "PlantView",
    "Recorder",
    "SimPlant",
    "SimPlantLink",
    "StateMachine",
    "Supervisor",
    "TcpPlantLink",
    "Telemetry",
    "dump",
    "parse",
]
