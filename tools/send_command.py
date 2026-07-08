"""Send one raw command to the gateway and print the reply — the B3.d/B4
NACK-ladder probe. Works on Windows CMD and anything else:

    python tools\\send_command.py valid            # full cluster -> "source is UI" (or ACK under PYTHON)
    python tools\\send_command.py unknown          # wrong name   -> unknown command 'bogus'
    python tools\\send_command.py rate             # 7 fast sends -> "rate" on the 6th+
    python tools\\send_command.py parse            # settings=42  -> "parse"
    python tools\\send_command.py range            # speed 99999  -> "range: Speed ref ..."
    python tools\\send_command.py estop-clear      # clear bit    -> "operator only"
    python tools\\send_command.py garbage          # trash bytes, then a valid command:
                                                   #   session must survive (drill B4-4)

Which rungs answer what depends on CommandSource (the gateway checks source
BEFORE parse/range/estop, same order as the sim):
  * source = UI      -> unknown / rate / garbage show their reasons;
                        valid / parse / range / estop-clear all answer "source is UI".
  * source = PYTHON  -> parse / range / estop-clear show their reasons and
                        `valid` gets a real ACK — but with no commander running
                        the plant will clamp to SAFE after ~5 s (the watchdog;
                        expected on the bench, step-up recovery on flip-back).
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time

sys.path.insert(0, ".")
from supervisory.monarch.control_settings import ControlSettings  # noqa: E402
from supervisory.monarch.labview_mapping import control_settings_to_labview  # noqa: E402


def full_settings(**overrides) -> dict:
    cs = ControlSettings()
    for key, value in overrides.items():
        setattr(cs, key, value)
    return control_settings_to_labview(cs)


def command(cid: int, name: str = "set_control_settings", settings=None) -> bytes:
    cmd = {"type": "command", "id": cid, "name": name,
           "params": {"settings": settings if settings is not None else full_settings()}}
    # \r\n: the gateway's TCP Read runs in CRLF mode — a bare \n never
    # terminates a line there. Compact separators: the gateway's Match
    # Pattern gate looks for the literal "type":"command", so a space after
    # the colon (json.dumps default) makes the line silently ignored. The
    # real commander (pydantic dump) is compact already; the sim tolerates
    # both.
    return (json.dumps(cmd, separators=(",", ":")) + "\r\n").encode()


def read_acks(sock: socket.socket, want: int, timeout: float = 6.0) -> list[str]:
    """Collect `want` command_ack lines (telemetry lines are skipped)."""
    sock.settimeout(0.5)
    deadline = time.monotonic() + timeout
    buf, acks = b"", []
    while len(acks) < want and time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.strip(b"\r").decode(errors="replace")
            if '"command_ack"' in text:
                acks.append(text)
    return acks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rung", choices=["valid", "unknown", "rate", "parse",
                                     "range", "estop-clear", "garbage"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    args = ap.parse_args()

    s = socket.create_connection((args.host, args.port), timeout=5)
    print(f"connected to {args.host}:{args.port} — rung: {args.rung}")

    if args.rung == "valid":
        s.sendall(command(1))
        expect, want = "ACK (PYTHON) or 'source is UI'", 1
    elif args.rung == "unknown":
        s.sendall(command(2, name="bogus"))
        expect, want = "unknown command 'bogus'", 1
    elif args.rung == "parse":
        s.sendall(command(3, settings=42))
        expect, want = "parse", 1
    elif args.rung == "range":
        s.sendall(command(4, settings=full_settings(speed_ref=99999.0)))
        expect, want = "range: Speed ref ...", 1
    elif args.rung == "estop-clear":
        s.sendall(command(5, settings=full_settings(clear_emergency_stop=True)))
        expect, want = "operator only", 1
    elif args.rung == "rate":
        for i in range(7):
            s.sendall(command(10 + i))
        expect, want = "first 5 pass the rate rung, 6th+ answer 'rate'", 7
    elif args.rung == "garbage":
        s.sendall(b'{"type":"command", THIS IS NOT JSON @@@\r\n')
        time.sleep(0.5)
        s.sendall(command(99))
        expect, want = ("garbage: discarded or id -1; then id=99 answered "
                        "-> session survived (drill B4-4)"), 2

    print(f"expected: {expect}")
    acks = read_acks(s, want)
    if not acks:
        print("NO REPLY within timeout — for 'garbage' with a silent-discard "
              "gateway that may be half-expected; anything else = a problem.")
        return 1
    for a in acks:
        print("reply:", a)
    s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
