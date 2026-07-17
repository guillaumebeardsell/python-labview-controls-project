# Heartbeat hardening — click-level build instructions

*Created 2026-07-17. Closes the holes found by the 2026-07-16 kill-9056 test
(`docs/command-path-asbuilt.md` §6a) and the inert-mirror suspicion. Three tasks on
three targets, independent of each other — do A first (protection), then B
(observability), then C (mirror). Heartbeat-map recap: the 9056 watches everyone
(including itself); the 9049 watches nobody cross-chassis; the PC computes nothing.*

**Stop the running system before any edit (you cannot edit a running VI); log
build/deploy times in the commissioning book. Every task ends with its own
verification — do not skip them.**

---

## Task A — 9049 staleness→SAFE clamp on the state relay (`APC_9049_CAS_loop.vi`)

**Closes:** 9056 dies at state ≥ 2 → `9049_Global_SYSTEMSTATE` freezes → spark/DI gate
stays open on stale state (observed live 2026-07-16).

1. In the project (RT target context) open **`APC_9049_CAS_loop.vi`** → block diagram.
2. Find the **`APC_9049_9056SharedVarPolling`** subVI call (it returns the 9056 IO
   array + **timestamp** + `SystemState`) and follow the `SystemState` wire to where
   the loop **writes `9049_Global_SYSTEMSTATE`**.
3. Build the staleness detector — **time-based, not cycle-based** (CAS iterates once
   per engine cycle, so a cycle counter would scale with rpm; ms don't):
   a. Drop a **Tick Count (ms)** primitive in the loop.
   b. Wire the polling VI's **timestamp** into a **Feedback Node**; compare current vs
      previous (**Not Equal?**).
   c. **Select** node: timestamp changed → store the current Tick Count ("last-fresh
      time", second Feedback Node); unchanged → keep the stored value.
   d. **Subtract**: now − last-fresh → **> 5000** (ms, diagram constant with a comment:
      "9056 staleness threshold — matches the WatchDog ~5 s convention").
4. Feed the resulting `9056 stale?` boolean into a **Select** on the state wire:
   TRUE → **I8 constant −1**, FALSE → the relayed `SystemState` → into the
   `9049_Global_SYSTEMSTATE` write.
5. Surface the boolean: front-panel indicator **`9056 stale (relay clamped)`** on
   CAS_loop, so interactive sessions can see the clamp acting.
6. Save. **This is a state-path change, not display-only** — regression required
   (below). Rebuild **both** rtexe specs (`APC_9049_RT` and `APC_9049_RT SIM`) when
   done; log both on the deployment sheet.

*Verify:* interactive, sim crank + sim pressure, state = 2, gate LEDs lit → **kill the
9056** → within ~5 s: `9056 stale` TRUE, `9049_Global_SYSTEMSTATE` = −1 (DSM), **gate
LEDs dark, `NumberOfActiveIGN_DI` collapses**. Restart the 9056 (reboot-order rules)
→ relay resumes, state recoverable. *Regression:* re-run the state-gate checks
(4d LEDs on/off with state) and drill 5i; the warnings matrix is untouched by this
edit — no matrix re-run needed.

*Known residual (pre-existing, unchanged):* if CAS_loop itself dies, the echo freezes
— TS10ms still gates on the last value. The FPGA watchdog covers a full RT stall;
a CAS-only death remains uncovered (documented gotcha #5 in the codebase README).

---

## Task B — PC-computed watchdog LEDs (`APC_PC_UI_Main.vi`)

**Closes:** the UI's liveness LEDs are relayed 9056 verdicts that freeze green when
the 9056 dies (operator decision 2026-07-16: compute liveness on the PC).

1. Open **`APC_PC_UI_Main.vi`** → block diagram; find the main polling loop (the one
   that reads shared variables for display) and note its **loop period** (needed for
   the threshold; if it's ~100 ms, the 5 s threshold = 50 iterations — but prefer the
   same Tick-Count-ms pattern as Task A, immune to period changes).
2. Add SV reads of **`9049_HeartBeat`** and **`9056_HeartBeat`** (they live in the
   9049-hosted `APC_SharedVars` — no new deployment needed).
3. Per channel, the stall detector (same as Task A steps 3–4): Feedback Node on the
   value → changed? → refresh last-fresh Tick Count → (now − last-fresh) > 5000 ms →
   boolean → new front-panel LED. Labels: **`9049 not responding (PC view)`**,
   **`9056 not responding (PC view)`**.
4. **MTR LED from first-hand knowledge:** the PC is the Modbus master — in the Modbus
   loop, the comms-loss branch (the wait-5 s-and-retry case) sets a boolean → LED
   **`MTR link down (PC view)`**. (Alternative: stall-count the MTR HB register with
   the same pattern.)
5. **Keep** the existing `9056_PCnotResponding` LED, relabeled **`PC HB fault (9056
   view)`** — it is the only external check on the PC's own heartbeat path. Remove or
   demote the old relayed `9056_9049notResponding` / `9056_MTRnotResponding` LEDs to
   avoid two sources of truth on one panel. Group the new LEDs under a header:
   **"LIVENESS (computed on this PC)"**.
6. Save; **rebuild the PC EXE** (PC apps run as EXEs only — deployed-bringup rule #1);
   log the build.

*Verify:* run everything → kill the 9056 → `9056 not responding (PC view)` red within
~5 s **while the old-style relayed values freeze** (photograph: this is the drill-5i
before/after evidence). Restart; repeat once for the 9049 (expect the 9049 LED red +
UI SVs stale — the SV host is the 9049, so much of the panel dies with it; note what
the LED adds anyway: an explicit verdict instead of quietly frozen numbers).

---

## Task C — gateway `operator_requests` (make the safety mirror real)

**Closes:** the Python safety-only mirror is inert if telemetry lacks
`operator_requests` (the mirror returns early on `None`) — panel FORCE buttons then
have **no** Python-mode path. The Python side is already built: `monarch_parser` maps
an `operator_requests` flatten via `control_settings_from_labview` — the gateway just
has to send it.

0. **Verify it's actually missing first** (2 min): open `operate_traffic.jsonl` on the
   control PC → any telemetry line → is there an `"operator_requests"` key? If present
   and non-null, Task C is already done — skip to Verify.
1. Open **`APC_PC_PythonGateway.vi`** → the 1000 ms telemetry frame section (where
   `settings` / `limited_settings` are built from `Flatten To JSON` of
   `PC_ControlSettings` + the `Limited_ControlSettings` tap).
2. Add an SV read of **`PC_OperatorRequests`** → **Flatten To JSON** (same instance
   pattern as `PC_ControlSettings`) → insert into the telemetry JSON as field
   **`operator_requests`** (exact key, snake_case).
3. Save; rebuild/redeploy the gateway EXE; log it.

*Verify (the mirror test, PYTHON mode + `--safety-only-mirror`):*
1. `operate_traffic.jsonl` now shows `operator_requests` populated each second.
2. Press **FORCE MOTORING** on the panel → state clamps to ≤1 within a tick or two →
   release → ladder climbs again. That is the panel-force safety floor working through
   Python for the first time. Record in the book (it upgrades the 4c e-stop-only
   verification to the full safety floor).

---

## Order, custody, and where this reports

- Recommended order: **A → B → C**; re-run **drill 5i** after A+B for the
  before/after evidence page.
- Builds touched: 9049 rtexe ×2 specs (A), PC UI EXE (B), gateway EXE (C) — one
  deployment-sheet line each, SIM/safe-defaults distinction maintained.
- On completion update: `docs/command-path-asbuilt.md` §6a (mark tasks built),
  the heartbeat-map holes list, and `docs/session-handoff-2026-07-11.md`.
