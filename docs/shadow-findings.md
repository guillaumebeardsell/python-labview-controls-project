# Shadow-Compare Findings Log

Dispositions for divergences reported by `tools/shadow_compare.py` (Phase A2).
A divergence is a finding, not automatically a Python bug — the LabVIEW logic is
unvalidated. Every entry needs a disposition before Phase A's exit gate.

## 2026-07-06 — first replay of `monarch.jsonl` (347 frames, 7 sessions)

**Result: 291/340 agree (85.6%).** Per-session:

| Session | Kind | Agreement | Disposition |
|---|---|---|---|
| 1 (248 frames) | sim gateway | **247/247 (100%)** | Port reproduces the sim's state walk exactly. |
| 2–5 (28 frames) | real gateway, Part A/B bring-up | 12/24 | **Not StateMachine output** — `system_state` was the hand-set shared variable (user set 3/FIRING manually while `requested_mode` sat at 0). Divergences expected; no port defect. |
| 6–7 (71 frames) | real gateway, live Part B | 32/69 | Same: `requested_mode` toggled 0→1 in the UI but `system_state` stayed 0 — the 9056 StateMachine was **not running/wired to the shared variable** during these captures. Divergences expected; no port defect. |

**Net:** zero divergences attributable to the port. The real-session divergences
carry a useful lesson for Phase A's exit: **bench sweeps only count as
shadow-compare evidence when the 9056 StateMachine is actually running and
writing the `SystemState` shared variable.** Until then, real-gateway captures
validate the pipeline, not the state logic.

Also noted in these captures: coverage is reduced (shadow extras not yet
pre-wired), so warnings/force/manual inputs are assumed inactive.

## Open question — is `STATE LIMITATION FROM WARNINGS` actually wired? (2026-07-07)

Raised by the user: the StateMachine's `STATE LIMITATION FROM WARNINGS` may be
running on its **front-panel default** rather than a live `WarningIntegration`
output — which, given the WatchDog/heartbeat precedents, is plausible. It is a
**subVI input terminal**, so the answer lives at the caller (`APC_9056_TS_loop`),
not inside the StateMachine. From the TS_loop export the StateMachine has several
inputs wired and a `DIAG` VI adjacent that appears to feed it, so it looks
*plausibly* wired — but the specific terminal can't be resolved from the export.

- **To confirm (LabVIEW):** on the StateMachine node in `TS_loop`, follow the
  `STATE LIMITATION FROM WARNINGS` input wire (Find → Wire Source). Live if it
  comes from `WarningIntegration`/`DIAG`; dead if the terminal is empty.
- **Self-answering via telemetry:** the A2.1 pre-wire should publish **both**
  (a) the value on the StateMachine's warnings input and (b) WarningIntegration's
  output. Same wire ⇒ one variable; different ⇒ telemetry proves the clamp is
  disconnected, and shadow compare will show LabVIEW ignoring warnings while the
  port honors them.
- **Port impact: none.** The port consumes `warnings_limit` as designed; this is
  an as-built LabVIEW fact for shadow mode to surface.

## Standing observations for the team (from the port itself)

- **`ForceState` overrides EMERGENCY STOP** (wired directly to the SYSTEM STATE
  indicator, after the MIN). If e-stop-always-wins is the intent, the VI needs a
  guard — flagged for review; the port reproduces the as-built behavior.
- **`DisregardWarnings` bypasses the entire MAX-LEVEL limiter**, not just the
  warnings clamp (misleading name). Whatever sets it disables per-state caps.
- **NG-feed FIRING cap = 6** in the table (levels elsewhere are 0–2) — suspected
  typo for 2; ported as-is.
- **More detection-without-response** (2026-07-06, from `WarningIntegration`):
  the VI stall-detects the **9049** and **9056-FPGA** heartbeats (counter vs
  threshold 10), but the resulting "not responding" booleans drive front-panel
  indicators only — they do not feed `STATE LIMITATION FROM WARNINGS`. Same
  pattern as the unwired PC watchdog: loss of the 9049 (the engine-synchronous
  controller!) produces no supervisory reaction. Recommend wiring these into
  the warnings max alongside the B0 `PCnotResponding` fix.
