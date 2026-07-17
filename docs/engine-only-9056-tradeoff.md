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
  `WarningIntegration` — and **the warnings→state clamp is LIVE in the running build**
  (~~gap W5~~ **refuted on the bench 2026-07-16**: a latched severity-3 warning drove
  `warn_lim=1` and pinned the state at MOTORING in both UI and PYTHON modes until CLEAR
  WARNINGS; see `docs/9056-warning-policy-asbuilt.md`). So plant-side warnings CAN block
  spark/DI **today**: the 9056 plant warning limits/masks must be managed for engine-only
  running (opened/masked, documented, restored — the custody discipline), and raster
  severities max-latch, so a single transient trip persists until cleared.
- The state machine ran on the 9049 `TS10ms_loop` in the 2023 design (banner still says
  so) — moving a minimal version back is a return, not an invention.
- `MTRnotResponding` is **not** in the SAFE-clamp OR — the membrane PLC being absent is
  fine in every option.
- **The dyno is commanded from the 9056** (`APC_9056_DynoControl` → `DYNO-REF`, a 9056
  analog output). An open-loop engine must be *spun* by the dyno, so a dark 9056 means
  no motoring at all unless the dyno drive is operated manually at its own cabinet.
- **All slow engine-health instrumentation lives on the 9056's four AI cards** (see the
  signal table below) — oil pressure/temperature, coolant and exhaust temperatures,
  torque, fuel flows and pressures, lambda. The 9049 measures only what is
  crank-synchronous (the 9222 fast pressures + rpm + combustion metrics).

## Options

**A — run the 9056 headless** (plant unconnected, plant loops commanded to mode 0).
**B — 9049 + PC only**, with a small 9049 modification: local
`SYSTEMSTATE = min(requested, limit)` in TS10ms + a `PC_HB` stall watchdog feeding the
limit, CAS_loop echo repointed to the local value.
**Hybrid (B + 9056 as instrument)** — the B modifications make the 9049 independent of
the 9056's state; the 9056 also runs, purely to supply reads + dyno command. Decoupling
bonus: a 9056 crash mid-run leaves the engine governed by the 9049's own state logic
instead of a frozen relay.

## Engine signals read through the 9056 (lost if it is dark)

| Function | Signals | 9056 card | When it matters |
|---|---|---|---|
| Lubrication | `EO-PT` oil pressure; `EO-TT` oil temperature | NI9205 (r1); NI9214-2 (r4) | **From the first crank** |
| Cooling | `EC-TT` coolant temps; `SW-FT-001–004` service-water flows; `SW-TT` temps | NI9214-1/2; NI9208 | Sustained motoring, any firing |
| Exhaust temps | exhaust-side thermocouples (`WF`/`SW-TT`, Texh-loop feedback) | NI9214-1/2 | First fire |
| Load / torque | `TORQUE` (dyno shaft) | NI9205 | Motoring friction check; only independent cross-check on IMEP once fired |
| Fuel system | `NG`/`NGDI` flows + supply/rail pressures; line temps | NI9208; NI9214-1 | DI rail pressure critical the day fuel arrives |
| Air/charge path | `WF-PT-004/014/016` slow absolute pressures; `WF-TT` intake temps | NI9208; NI9214-1 | Manifold conditions, pegging sanity |
| Lambda | `WF-OA-001/002` O₂ analyzers | NI9205 | AFR sanity at first fire |

The 9049 keeps, regardless: Pcyl1–6 + `Ppre`/`Psyst`/`Pexh` (fast, crank-synchronous),
rpm, and every combustion metric. So Option B keeps the *combustion* picture intact but
loses the *engine-health* picture entirely — and because of W5, what is lost is
monitoring/logging, not automatic protection (plant warnings never actuated anything
as-built). Rewiring EO-PT/EO-TT/EC-TT onto the 9049 is not practical: its spare fast
±10 V channels are the wrong hardware for thermocouples. Display note: `VariableMapping`
prefers 9056 values on name collisions, so a dark 9056 leaves stale/empty rows on the
UI screens.

## Pros / cons

| | A — 9056 headless | B — 9049 + PC only (modified) |
|---|---|---|
| Architecture | ✅ As-built, unchanged; no surgery near the gate | ⚠️ LabVIEW changes inside TS10ms, adjacent to the spark/DI gate |
| Evidence carry-over | ✅ Matrix + watchdog drills stay valid as-is | ⚠️ Regression owed: re-run false-trip matrix + gate drills on the new build |
| Plant-warning clamp | ❌ **LIVE** (W5 refuted on the bench 2026-07-16): latched warnings clamp the shared state — the 9056 plant limits/masks must be managed for engine-only running: a custody hazard on the safety chassis | ✅ Problem eliminated — no plant warnings exist |
| Loss-of-PC SAFE clamp | ✅ Exists today (`TS_loop`, armed both modes, drilled) | ⚠️ Must be built — but it is the documented roadmap gap owed before Python command authority anyway |
| Bench complexity | ❌ Second chassis to boot/maintain; reboot-order dependency; must verify 9056 RT_main tolerates missing modules | ✅ Fewer moving parts; matches the hardware actually on the bench |
| Config custody | ✅ One configuration for engine-only and full-plant | ❌ A fork: must be labeled and reconciled before full-plant ops |
| Commissioning logic | ⚠️ First fire on a config with masked plant warnings | ✅ Commission the configuration you will actually fire on |
| **Engine instrumentation** | ✅ Oil P/T, coolant, exhaust temps, torque, fuel, lambda all available | ❌ **All engine-health reads dark** (see signal table) — monitoring by eye impossible |
| **Dyno (motoring the engine)** | ✅ `DynoControl` → `DYNO-REF` available | ❌ **No dyno command** — engine cannot be spun except by manual/local dyno drive control |

## Safety-function coverage

| Function | A (9056 on) | 9056 off, 9049 unmodified | B (9049 modified) |
|---|---|---|---|
| State arbitration + limiter | ✅ full StateMachine | ❌ state stuck low — engine inert | ✅ local `min(requested, limit)` |
| Loss-of-PC → SAFE | ✅ `WatchDog` → `TS_loop` clamp | ❌ none | ✅ new `PC_HB` stall counter on 9049 |
| Warning → state clamp (plant) | ✅ **LIVE — verified 2026-07-16** (severity 3 → clamp MOTORING, both modes); ⚠ false-trips on floating/disconnected channels — manage limits/masks | — (no plant) | — (no plant) |
| `CylPressError` spark/DI veto | ✅ 9049-local, unaffected | ✅ | ✅ |
| FPGA watchdog (>4 Hz kill) | ✅ 9049-local, unaffected | ✅ | ✅ |
| E-stop | ✅ enters via 9056 SM + hardware | ⚠️ hardware path only — verify | ⚠️ re-run drill 5f in this config |

## Work required

| A — 9056 headless | B — 9049 + PC only |
|---|---|
| Open/mask 9056 plant warning limits for engine-only running — **due now, the clamp is live** (document + restore discipline) | TS10ms: local state `Select(−1:3)` → `Min` logic |
| Verify 9056 RT_main starts clean with plant modules missing (−200088-class) | `PC_HB` stall watchdog (≈ the `APC_9056_WatchDog` pattern, one channel) |
| Confirm plant loops hold mode 0 across states | Repoint `9049_Global_SYSTEMSTATE` echo to the local value |
| — | Verify stale `9056_MeasAndCalc` reads are harmless downstream |
| — | E-stop drill (5f) in this configuration |
| — | **Regression gate: re-run the 7-set false-trip matrix + state-gate drills** |
| — | Fork custody: label the build; reconciliation plan for full-plant return |

## Decision (2026-07-16)

**Run the 9056 alongside the 9049 for engine-only testing.** Pure Option B is not
viable: the dyno — without which the engine cannot be motored at all — is commanded
through a 9056 analog output, and every engine-health read (oil pressure/temperature,
coolant and exhaust temperatures, torque, fuel-system pressures) arrives on the 9056's
AI cards. Duplicating that I/O on the 9049 is the wrong hardware and real wiring work;
running the chassis that already owns it is not.

What survives from the B analysis:

- The **9049-side `PC_HB` stale-command→SAFE watchdog** stays on the roadmap — it is
  owed before Python holds command authority regardless of this decision.
- The **hybrid decoupling** (9049 no longer depending on the 9056's state relay) remains
  an attractive hardening step, to be weighed against the regression cost of touching
  TS10ms; it is *optional* for engine-only testing, not a precondition.

Conditions attached to running the 9056 on the engine-only bench:

1. Verify 9056 RT_main starts clean with plant modules missing/disconnected
   (−200088-class startup races — same fix pattern as the 9049 DAQ retry).
2. Plant loops commanded to mode 0; confirm they hold 0 across all states.
3. **The warnings→state clamp is live (W5 refuted 2026-07-16)** — a latched severity-3
   warning pinned the bench at MOTORING in both modes. Manage the 9056 plant warning
   limits/masks at every engine-only session (opened/masked, documented, restored: the
   custody discipline). When the state won't rise, check `warn_lim` in the CLI `status`
   first; photograph `UI_Errors` before clearing.
4. E-stop and loss-of-PC drills (5a/5b/5f) run on this exact two-chassis configuration.
