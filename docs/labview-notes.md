# LabVIEW Gateway Implementation Notes (LabVIEW 2020 SP1, Windows)

What to build on the LabVIEW side to implement the gateway half of
[the ICD](icd.md). The Python fake gateway (`python -m supervisory.simserver`,
source in `supervisory/simserver.py`) is the executable reference for this
behavior — when in doubt, match it.

## Placement

Build the gateway as its own module (QMH or your house pattern) with its own
loop, separate from the existing control logic. It talks to the rest of the
application through whatever queues/FGVs/user events the existing supervisory
code already uses — the gateway replaces the *decision-maker*, not the
plumbing under it. Nothing about the cRIO links (Network Streams, shared
variables, FPGA interface) changes.

## TCP server

- `TCP Create Listener` on port 5020 (make it a config item), `TCP Wait on
  Listener` for the single Python client. If a second client connects while
  one is active, close the new connection immediately.
- Read with `TCP Read` in **CRLF mode** — the Python client terminates every
  message with `\r\n`. Use a short timeout (~100 ms) so the same loop can
  interleave reads with the 1 Hz telemetry sends and the watchdog check.
- Write telemetry/acks as one JSON line terminated with `\r\n` (Python
  tolerates bare `\n` too).
- Treat TCP errors (56 timeout excepted) as disconnection: enter safe hold,
  close the connection, go back to waiting on the listener.

## JSON

- Recommended: **JSONtext** (free on VIPM). It tolerates unknown/extra fields
  and supports lookup by path, which matches the ICD's forward-compatibility
  rules. The built-in `Flatten To JSON` / `Unflatten From JSON` primitives
  work for fixed clusters but are strict about shape.
- The `channels` and `flags` objects are name→value maps. With JSONtext,
  build them from arrays of name/value pairs so adding a tag is a data
  change, not a diagram change.

## Session loop sketch

Per connection:

1. Reset the telemetry `seq` counter and the heartbeat-age timer.
2. Loop:
   - `TCP Read` (CRLF mode, 100 ms timeout). On a line: parse; route
     `command` to validation, `heartbeat` to the watchdog timer reset. Log
     and discard anything malformed or unknown — do not drop the connection
     for it.
   - Every 1 s: gather the current snapshot (mode, channels, interlock
     flags), increment `seq`, send `telemetry`.
   - Watchdog: if ms-since-last-heartbeat > 5000, trigger the existing safe
     fallback and report `mode: "SAFE_HOLD"` in telemetry. Same on
     disconnect.

## Command handling

- Validation is the existing LabVIEW logic's job; the gateway only parses and
  routes. Every command gets a `command_ack` within 500 ms — send the ack
  from the validation result, *not* from command completion (completion shows
  up in telemetry).
- Never block the session loop on a slow command: hand the command to the
  executing module by queue and ack as soon as validation decides.
- Reject anything that arrives while in safe hold (except whatever explicit
  reset/recovery commands you define).

## Bring-up checklist

- [ ] Confirm the cRIO RT targets already watchdog their link to the Windows
      host (Windows now hosts Python too, so a Windows failure takes both —
      the cRIOs must fail safe on their own).
- [ ] Gateway telemetry visible with `python - <<'EOF'` client or the real
      supervisor pointed at the LabVIEW port.
- [ ] Heartbeat watchdog: kill the Python process, confirm safe hold within
      5 s and `mode: "SAFE_HOLD"` in telemetry.
- [ ] Reconnect: restart Python, confirm a fresh session (seq restarts are
      fine — Python does not assume continuity) and that safe hold is NOT
      cleared by the mere reconnection.
- [ ] NACK path: send a command that violates an interlock, confirm
      `accepted: false` with a useful `reason`.
