"""Capture one raw telemetry line from the gateway and diagnose it.

Use when the observer reports "malformed message" — the observer's own log
truncates to 200 chars, so it can't show where the JSON actually breaks. This
grabs one complete line, writes it verbatim to a file, and pinpoints the parse
error (position + surrounding context) so a Format-Into-String envelope slip is
obvious.

    python tools/capture_line.py                 # 127.0.0.1:5020 -> raw_telemetry_line.txt
    python tools/capture_line.py --host H --port P --out FILE
"""

import argparse
import json
import socket
import sys


def grab_line(host: str, port: int, timeout: float = 10.0) -> bytes:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    buf = b""
    try:
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    finally:
        sock.close()
    return buf


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture + diagnose one telemetry line")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--out", default="raw_telemetry_line.txt")
    args = ap.parse_args()

    raw = grab_line(args.host, args.port)
    if b"\n" not in raw:
        print(f"no complete line received ({len(raw)} bytes, no LF) — connection closed or "
              f"the message never terminates. Bytes:\n{raw[:400]!r}")
        return 2

    line = raw.split(b"\n", 1)[0].rstrip(b"\r")
    with open(args.out, "wb") as fh:
        fh.write(line)

    lit_lf = raw.count(b"\n") - 1  # terminator excluded
    lit_cr = raw.count(b"\r") - (1 if raw.count(b"\r") else 0)
    print(f"captured {len(line)} bytes -> {args.out}")
    print(f"stray newlines inside the message: LF={lit_lf}  CR={lit_cr}"
          + ("   <-- these break LF framing!" if lit_lf or lit_cr else "   (framing ok)"))

    text = line.decode("utf-8", errors="replace")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        pos = e.pos
        lo, hi = max(0, pos - 45), min(len(text), pos + 45)
        print(f"\nINVALID JSON: {e.msg} at position {pos} of {len(text)}")
        print(f"  ...{text[lo:pos]}  <<<HERE>>>  {text[pos:hi]}...")
        # a common tell: the char just before the break
        if pos < len(text):
            print(f"  offending char: {text[pos]!r}; preceding: {text[max(0,pos-1):pos]!r}")
        print("\nLikely causes: missing ',' between two fields, a '%s' arg that isn't valid "
              "JSON (empty/wrong wire), or a truncated message (error near the very end).")
        if "NaN" in text or "Infinity" in text:
            print("Found NaN/Infinity in the line — LabVIEW Flatten To JSON emits these for "
                  "uninitialized/invalid floats (e.g. an unwritten Limited_ControlSettings "
                  "shared variable); they are not valid JSON.")
        return 1

    print("\nJSON parses OK. Trying the MONARCH decoder...")
    try:
        sys.path.insert(0, ".")
        from supervisory.monarch import parse_monarch_telemetry
        msg = parse_monarch_telemetry(obj)
        extras = [k for k in ("warnings_limit", "manual_state", "force_state",
                              "limited_settings", "command_source")
                  if getattr(msg, k) is not None]
        print(f"decoded: seq={msg.seq} state={msg.system_state.name} "
              f"extras_present={extras} unmapped={list(msg.unmapped)}")
    except Exception as e:  # noqa: BLE001 - diagnostic
        print(f"decoder error ({type(e).__name__}): {e}")
        print("top-level keys:", sorted(obj.keys()))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
