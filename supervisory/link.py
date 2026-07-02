"""Transport layer: the PlantLink protocol and the real TCP client.

The engine only ever sees PlantLink, so the real TcpPlantLink and the
socket-free SimPlantLink (sim.py) are interchangeable — that swap is what
makes the supervisory logic unit-testable without LabVIEW or hardware.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
from typing import Protocol

from pydantic import ValidationError

from .messages import Message, dump, parse

log = logging.getLogger(__name__)

# ICD section 5: repeated garbage may drop the connection.
MAX_CONSECUTIVE_BAD_MESSAGES = 10


class PlantLink(Protocol):
    """What the engine needs from a transport."""

    @property
    def connected(self) -> bool: ...

    def poll(self) -> list[Message]:
        """Drain and return all messages received since the last call. Non-blocking."""
        ...

    def send(self, msg: Message) -> bool:
        """Try to send. Returns False (after logging) if the link is down."""
        ...

    def close(self) -> None: ...


class TcpPlantLink:
    """TCP client for the LabVIEW gateway (ICD section 2).

    A background thread owns the connection: it connects, reads LF-terminated
    JSON lines into an inbox, and reconnects with backoff after any failure.
    The engine notices an outage as `connected` going False and telemetry
    going stale; a reconnect is a fresh session (ICD section 5).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5020,
        reconnect_min_s: float = 1.0,
        reconnect_max_s: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._reconnect_min_s = reconnect_min_s
        self._reconnect_max_s = reconnect_max_s
        self._inbox: queue.Queue[Message] = queue.Queue()
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread = threading.Thread(target=self._run, name="plantlink", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def poll(self) -> list[Message]:
        out: list[Message] = []
        while True:
            try:
                out.append(self._inbox.get_nowait())
            except queue.Empty:
                return out

    def send(self, msg: Message) -> bool:
        sock = self._sock
        if sock is None:
            log.warning("send dropped, link down: %s", msg.type)
            return False
        try:
            with self._send_lock:
                # CRLF so the LabVIEW side can use TCP Read in CRLF mode (ICD section 2).
                sock.sendall((dump(msg) + "\r\n").encode("utf-8"))
            return True
        except OSError as exc:
            log.warning("send failed (%s), message dropped: %s", exc, msg.type)
            return False

    def close(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        backoff = self._reconnect_min_s
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self._host, self._port), timeout=5.0)
            except OSError as exc:
                log.debug("connect to %s:%d failed: %s", self._host, self._port, exc)
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, self._reconnect_max_s)
                continue
            backoff = self._reconnect_min_s
            sock.settimeout(0.5)
            self._sock = sock
            self._connected.set()
            log.info("connected to gateway at %s:%d", self._host, self._port)
            try:
                self._read_lines(sock)
            finally:
                self._connected.clear()
                self._sock = None
                try:
                    sock.close()
                except OSError:
                    pass
                if not self._stop.is_set():
                    log.warning("gateway link down, reconnecting")

    def _read_lines(self, sock: socket.socket) -> None:
        buf = b""
        bad = 0
        while not self._stop.is_set():
            try:
                data = sock.recv(4096)
            except TimeoutError:
                continue  # periodic wakeup so close() is honored
            except OSError:
                return
            if not data:
                return  # peer closed
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    self._inbox.put(parse(line))
                    bad = 0
                except ValidationError:
                    bad += 1
                    log.warning("discarding malformed message (%d consecutive): %.200s", bad, line)
                    if bad >= MAX_CONSECUTIVE_BAD_MESSAGES:
                        log.error("too many malformed messages, dropping connection")
                        return
