# Phase C — Python in Command on the Bench (detailed instructions)

**Objective:** Python is the acting supervisor for bench operation — real
authority over mode requests and setpoints against the real cRIOs — with the
LabVIEW StateMachine limiter and all FLOOR mechanisms untouched beneath it.

**Authority level:** modes + setpoints via the B command path, always behind
the LabVIEW limiter. No engine (hardware not commissioned); "bench" =
controllers and plant I/O as available, actuators safe/disconnected as the
team dictates.

**Entry criteria (hard gate):** Phase B exit passed (all drills 3/3, B0
statement true, ICD v0.2 published). A2 shadow compare available.

---

## C1 — Operator surface (minimal, CLI first)

*Owner: Claude.*

`examples/monarch_operate.py` — a deliberately small REPL/CLI over
`MonarchCommander`:
- `status` (state, source, last ack, staleness, divergence alarm state),
- `mode <safe|standby|motoring|idling|firing>` (sets `requested_mode`),
- `set <field.path> <value>` (e.g. `set pid_control_references.tcoolant.ec_tt_001_ref 60`),
- `force idling|motoring on|off`, `estop` (set only — clear is operator/HMI),
- every command echoes the resulting ACK/NACK and the next telemetry effect.
No autonomous behavior in this phase: the CLI is a human pushing intents
through Python's plumbing. Sequences come in Phase D.

Guardrails baked in: refuse to send while telemetry is stale; refuse
`clear_emergency_stop`; log every intent + outcome to `operate.jsonl`.

## C2 — Reverse shadow compare (divergence alarm)

*Owner: Claude.*

Extend `tools/shadow_compare.py --live --alarm`: while Python commands, the A1
port predicts `limited_settings`/`system_state` for each frame; any mismatch
between prediction and LabVIEW's actual output raises an audible/console alarm
and freezes context (frame + intent) to disk. This is the canary that the two
brains still agree while one of them is driving.

## C3 — Handover procedure (write down, then follow every time)

1. Python running, telemetry fresh, `status` clean; Python intent initialized
   from telemetry (automatic).
2. Operator flips `CommandSource` UI→PYTHON on the HMI.
3. Confirm telemetry `command_source=PYTHON` and first Python frame produced
   **zero setpoint deltas** (bumpless check — the CLI prints it).
4. Work session.
5. Handback: operator flips to UI; confirm UI writes resume; Python drops to
   observe-only automatically (its writes NACK).
Abort rule: anything unexpected → operator flips to UI (or e-stop). That path
is drill-proven from B4-7/8.

## C4 — Scripted acceptance session (the exit test)

One sitting, scripted, recorded end to end:
1. Handover per C3.
2. Mode walk STAND_BY → MOTORING → IDLING → FIRING → back down (respecting
   step-by-1; observe limiter behavior at each step).
3. Setpoint changes on ≥3 MIDDLE loops (a thermal ref, a gas ref, dyno ref) —
   verify effect in `limited_settings` and loop-mode telemetry.
4. Force idling + force motoring engage/release; verify clamps.
5. Provoke a synthetic warning → verify warnings clamp propagates and Python's
   prediction agrees.
6. E-stop from HMI mid-FIRING-request → SAFE; operator clear; recover.
7. Kill Python mid-session (repeat drill B4-1 under authority) → safe hold →
   restart → re-handover.
8. Handback per C3.

Pass = zero unsafe outcomes, zero unexplained divergence alarms, every ACK/
NACK/effect as predicted.

## C5 — Soak

*Owner: joint (start it, leave it).*

≥8 h continuous: Python in command holding a benign intent set, chaos script
injecting a random B4 drill every 20–40 min (skip e-stop), shadow alarm armed.
Pass = no drift (memory/handles stable), no missed reconnects, no alarms, log
review clean.

---

## Phase exit gate

- C4 acceptance session passed and archived (recordings + operate.jsonl).
- C5 soak passed.
- Handover procedure (C3) documented and rehearsed by ≥2 operators.

**Artifacts:** `monarch_operate.py`, `--alarm` mode, C3 procedure text,
acceptance + soak recordings.
