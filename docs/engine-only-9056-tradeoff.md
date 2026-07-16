# Engine-only operation: with or without the cRIO-9056?

*Decision memo, 2026-07-16. Context: open-loop engine commissioning — engine breathing
air, only spark + DI actuate. Question: does the 9056 RT app need to run, or can the
bench be 9049 + PC only?*

## The facts that frame the decision

- There is **one global `SYSTEM STATE`** for engine and plant; the state machine that
  produces it (`APC_9056_StateMachine`) runs **on the 9056**.
- The 9049 spark/DI hard gate is `¬CylPressError ∧ Activate ∧ Enable ∧ (SYSTEMSTATE ≥ 2)`;
  `9049_Global_SYSTEMSTATE` is the CAS_loop's **relay of the 9056's output**. 9056 dark
  ⇒ gate never opens ⇒ engine inert (fail-safe, but no run).
- `APC_SharedVars.lvlib` is **hosted on the 9049** — PC ⇄ 9049 comms are alive without
  the 9056. Spark/DI timing values flow PC → 9049 directly (`PC_ControlSettings`).
- With the 9056 running but the plant disconnected, its floating analog channels feed
  `WarningIntegration` and its `STATE LIMITATION FROM WARNINGS` output goes red — **but
  as-built that output is never consumed** (gap W5, `docs/9056-warning-policy-asbuilt.md`:
  only the watchdog clamp is wired into the StateMachine). So today floating plant
  channels do **not** block spark/DI. The catch: W5 is a *defect to fix*, and the moment
  it is fixed, Option A false-clamps on floating channels unless the 9056 plant warning
  limits are opened for engine-only running — i.e. A is workable now only by leaning on
  a safety gap, and inherits the limit-opening custody hazard as soon as the gap closes.
- The state machine ran on the 9049 `TS10ms_loop` in the 2023 design (banner still says
  so) — moving a minimal version back is a return, not an invention.
- `MTRnotResponding` is **not** in the SAFE-clamp OR — the membrane PLC being absent is
  fine in every option.

## Options

**A — run the 9056 headless** (plant unconnected, plant loops commanded to mode 0).
**B — 9049 + PC only**, with a small 9049 modification: local
`SYSTEMSTATE = min(requested, limit)` in TS10ms + a `PC_HB` stall watchdog feeding the
limit, CAS_loop echo repointed to the local value.

## Pros / cons

| | A — 9056 headless | B — 9049 + PC only (modified) |
|---|---|---|
| Architecture | ✅ As-built, unchanged; no surgery near the gate | ⚠️ LabVIEW changes inside TS10ms, adjacent to the spark/DI gate |
| Evidence carry-over | ✅ Matrix + watchdog drills stay valid as-is | ⚠️ Regression owed: re-run false-trip matrix + gate drills on the new build |
| Plant-warning clamp | ⚠️ Inert today (W5: clamp output unconsumed) — but once W5 is fixed, floating raster channels clamp the shared state and the 9056 plant limits must be opened: a custody hazard on the safety chassis | ✅ Problem eliminated — no plant warnings exist |
| Loss-of-PC SAFE clamp | ✅ Exists today (`TS_loop`, armed both modes, drilled) | ⚠️ Must be built — but it is the documented roadmap gap owed before Python command authority anyway |
| Bench complexity | ❌ Second chassis to boot/maintain; reboot-order dependency; must verify 9056 RT_main tolerates missing modules | ✅ Fewer moving parts; matches the hardware actually on the bench |
| Config custody | ✅ One configuration for engine-only and full-plant | ❌ A fork: must be labeled and reconciled before full-plant ops |
| Commissioning logic | ⚠️ First fire on a config with masked plant warnings | ✅ Commission the configuration you will actually fire on |

## Safety-function coverage

| Function | A (9056 on) | 9056 off, 9049 unmodified | B (9049 modified) |
|---|---|---|---|
| State arbitration + limiter | ✅ full StateMachine | ❌ state stuck low — engine inert | ✅ local `min(requested, limit)` |
| Loss-of-PC → SAFE | ✅ `WatchDog` → `TS_loop` clamp | ❌ none | ✅ new `PC_HB` stall counter on 9049 |
| Warning → state clamp (plant) | ⚠️ computed but unconsumed as-built (W5); false-trips on floating channels once fixed | — (no plant) | — (no plant) |
| `CylPressError` spark/DI veto | ✅ 9049-local, unaffected | ✅ | ✅ |
| FPGA watchdog (>4 Hz kill) | ✅ 9049-local, unaffected | ✅ | ✅ |
| E-stop | ✅ enters via 9056 SM + hardware | ⚠️ hardware path only — verify | ⚠️ re-run drill 5f in this config |

## Work required

| A — 9056 headless | B — 9049 + PC only |
|---|---|
| Open/mask 9056 plant warning limits once W5 is fixed (document + restore discipline); until then A runs only by leaning on the W5 gap | TS10ms: local state `Select(−1:3)` → `Min` logic |
| Verify 9056 RT_main starts clean with plant modules missing (−200088-class) | `PC_HB` stall watchdog (≈ the `APC_9056_WatchDog` pattern, one channel) |
| Confirm plant loops hold mode 0 across states | Repoint `9049_Global_SYSTEMSTATE` echo to the local value |
| — | Verify stale `9056_MeasAndCalc` reads are harmless downstream |
| — | E-stop drill (5f) in this configuration |
| — | **Regression gate: re-run the 7-set false-trip matrix + state-gate drills** |
| — | Fork custody: label the build; reconciliation plan for full-plant return |

## Recommendation

**Option B**, provided first fire is planned on the same engine-only configuration —
commission the architecture you will actually run. The deciding asymmetries: B's largest
work item (the cRIO-side stale-command→SAFE watchdog) is already owed on the migration
roadmap, while A's mitigation (opening plant warning limits on the safety chassis)
creates risk without retiring any. Choose A instead if full-plant integration is
imminent or if LabVIEW changes near the spark/DI gate are off the table right now.

Non-negotiables if B proceeds: the regression gate (matrix + drills re-run after any
TS10ms change) and fork custody (the engine-only build must never silently serve a
full-plant session).
