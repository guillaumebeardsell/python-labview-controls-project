"""JSONL traffic recorder.

Records every message in and out with a wall-clock timestamp, one JSON object
per line. The recording is the raw material for offline replay: re-running a
state machine against recorded telemetry to reproduce a field issue.
"""

from __future__ import annotations

import json
import time

from pydantic import BaseModel


class Recorder:
    """Appends {"t": <wall ts>, "dir": "rx"|"tx", "msg": {...}} per message."""

    def __init__(self, path: str) -> None:
        self._fh = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered

    def record(self, direction: str, msg: BaseModel) -> None:
        self._fh.write(
            json.dumps({"t": time.time(), "dir": direction, "msg": msg.model_dump()}) + "\n"
        )

    def close(self) -> None:
        self._fh.close()


class NullRecorder:
    """Recorder stand-in used when recording is disabled."""

    def record(self, direction: str, msg: BaseModel) -> None:
        pass

    def close(self) -> None:
        pass
