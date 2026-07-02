"""End-to-end smoke test of the real transport: TcpPlantLink against the
simserver session loop over an actual socket, at a fast tick rate."""

import socket
import threading
import time

from supervisory.link import TcpPlantLink
from supervisory.messages import Command, CommandAck, Telemetry
from supervisory.sim import SimPlant
from supervisory.simserver import serve_client


def test_tcp_roundtrip():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    plant = SimPlant()
    plant.HEARTBEAT_TIMEOUT_S = 1e9  # this test doesn't send heartbeats

    def server():
        conn, _ = listener.accept()
        with conn:
            try:
                serve_client(conn, plant, period_s=0.05)
            except (ConnectionError, OSError):
                pass

    threading.Thread(target=server, daemon=True).start()

    link = TcpPlantLink(host="127.0.0.1", port=port, reconnect_min_s=0.05)
    try:
        received = []
        sent_cmd = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            received.extend(link.poll())
            if not sent_cmd and any(isinstance(m, Telemetry) for m in received):
                assert link.send(Command(id=1, name="start"))
                sent_cmd = True
            if any(isinstance(m, CommandAck) for m in received):
                break
            time.sleep(0.02)

        assert any(isinstance(m, Telemetry) for m in received)
        acks = [m for m in received if isinstance(m, CommandAck)]
        assert acks and acks[0].id == 1 and acks[0].accepted
        assert plant.mode == "RUNNING"
    finally:
        link.close()
        listener.close()
