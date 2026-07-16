# 9056 Warning Policy — As-Built (from the 2026-07-14 VI prints)

The ground truth for **Phase A3** (port the warning→state policy). Everything below is read
off the block-diagram exports under `original-labview-codebase/` — folder + page cited per
claim. Companion to `docs/command-path-asbuilt.md` (same method, different subsystem).

**Evidence set (printed 2026-07-14):** `APC_9056_ErrorMask`, `APC_9056_MaskErrors`,
`APC_9056_MergeCylErrors`, `APC_9056_ClearSoftWarning`, `APC_ClearErrorButton`,
`APC_9049_checkAI`, `APC_9049_CycleAvgSignals`, `APC_9056_FPGA_main`, plus the existing
`APC_9056_WarningIntegration` print re-read page-by-page. Still not printed:
`APC_9056_LoadINI` (requested, not yet delivered).

---

## The chain

```
                      (TS_loop, ~20 ms control loop)
                                   │
                    APC_9056_WarningIntegration.vi          ── the ONE call site
                    ┌──────────────┴───────────────────────────────┐
   analog rasters   │  ErrorMask ── per-state arming masks         │  9049 cylinder flags
   NI9205 → r1      │  MaskErrors ── DEAD (Disabled frame, d9)     │  CylPresWarnings/Errors
   NI9208 → r2      │  ClearSoftWarning ── zero severity-1 slots   │  → "DECODE ERRORS"
   NI9214 → r3+r4   │  MergeCylErrors ── W/E pairs → 1/3, 5 groups │  → MergeCylErrors
   SYSTEM SIG → r5  └──────────────┬───────────────────────────────┘
                                   ▼
       Raster1..5_Warnings, Cylinder_Warnings (SVs, severity arrays 0..4)
       9049notResponding / 9056FPGAnotResponding (heartbeat stall flags)
       STATE LIMITATION FROM WARNINGS (I8)   ← the A3 output; NOT wired into the
                                               StateMachine as-built (docs/shadow-findings.md)
PC side: APC_ClearErrorButton.vi → APC_MASTER_ClearWarnings SV → WI handshake.
```

## APC_9056_WarningIntegration.vi — the integrator

Inputs: `CURRENT SYSTEM STATE` (I8), raster arrays `NI9205`/`NI9208`/`NI9214`/`SYSTEM
SIGNALS` (DBL, mean'd then forced to 16 elements), `WarningLimits` cluster, `LoadIni?`,
and `input cluster` (tagged plant signals — AR-FT-001, O2-FC-001, …, IMEPn6, TORQUE,
NG-FT-001, **EngineSpeed_rpm** — plus `CylPresWarnings`/`CylPresErrors` per-cylinder
numeric arrays from the 9049). Output: `STATE LIMITATION FROM WARNINGS`. (panel + html)

### Raster (analog) warning path  *(main d page)*

- **Five rasters:** NI9205→raster1, NI9208→raster2, NI9214 split \[0..16)/\[16..32)→
  raster3/raster4, SYSTEM SIGNALS→raster5. 16 slots each.
- **Four severity tiers.** `WarningLimits.RasterN_limits` are **2D (4 tiers × 16 slots)**;
  `RasterN_Sign` is 1D (per-slot sign, so one comparator serves min- and max-type limits:
  trip = `sign×value > sign×limit`, i.e. sign +1 warns above, −1 warns below — operand
  order per the 2026-07-06 wire-level transcription in `warning_policy.py`; bench-verify
  the direction once during the SIL-1 drills). A For loop (N=4) evaluates tier i and scores
  a tripped slot **severity i+1**; a slot's severity is the max tier tripped. Severity
  legend (diagram comment): **0 none · 1 soft warning (self-cleared) · 2 send to idle ·
  3 send to motoring · 4 send to safe and vent.**
- **State arming:** each raster's trip is AND-gated with `ErrorMask`'s rasterNmask bit
  *before* scoring — see the decoded tables below.
- **Latching:** per-slot severities max-latch through feedback registers (a severity never
  decreases on its own). Two clears exist:
  - **soft self-clear:** `ClearSoftWarning` zeroes stored severity-**1** entries each pass,
    so tier-1 warnings track the live condition (hence "self cleared");
  - **operator clear:** `APC_MASTER_ClearWarnings` TRUE → all latched severities zeroed
    (still-active conditions re-trip next tick) **and** the handshake fires: WI writes
    MASTER:=FALSE and `APC_SLAVE_ClearWarnings`:=TRUE (the 9049 consumes SLAVE for its
    own CylPress latch clear).
- **Clamp:** all five raster arrays + the merged cylinder array → Build Array → **Array Max**
  → case structure → `STATE LIMITATION FROM WARNINGS`. Observed: default(0/1)→**3**
  (FIRING allowed); per the legend the other frames map 2→2 (IDLING), 3→1 (MOTORING),
  4→−1 (SAFE) — only the default frame is directly visible in the export, the rest are
  inferred from the legend (bench-confirm during the SIL-1 warning drills).
- **Publications:** `Raster1..5_Warnings` + `Cylinder_Warnings` SVs (post-clear severity
  arrays — what the UI warning screens render).
- **Heartbeat monitors** *(main d, bottom)*: `9049_HeartBeat` and `9056_HeartBeat` SVs each
  feed an unchanged-value counter; ≥10 ticks stalled → `9049 not responding` /
  `9056 FPGA not responding`. (These are WI-local indicators — distinct from
  `APC_9056_WatchDog.vi`, which watches PC_HB/MTR_HB for the loss-of-PC clamp.)
- **Limits configuration** *(d10)*: on `9056_SetWarningLimits` SV TRUE, WI reads
  `Raster1..5_WarningLevels` + `Raster1..5_WarningSign` SVs, reshapes levels **4×16**, and
  rebuilds the local `WarningLimits` (then answers `9056_RetrieveWarningLimits` for the UI
  read-back). So the live limit values are **runtime state loaded over SVs from the PC UI**
  — the front-panel defaults in the export are NOT the operating values. `LoadIni?` (d1)
  triggers a load pass and resets itself.

### Cylinder (9049) warning path  *(main d + MergeCylErrors pages)*

`input cluster.CylPresWarnings/CylPresErrors` (numeric, per-cylinder packed flags from the
9049) → a small **"DECODE ERRORS"** subVI (unpacks to 2D boolean flag×cylinder matrices;
its VI name is not identifiable from the print — no `Decode*.vi` exists in the lvproj, so
it's one of the small helpers; functionally it is just bit-unpack) → **MergeCylErrors**:

- Row layout of the 7-flag matrices as-built: **[0] MaxPressure · [1..3] the three misfire
  variants (cyl-to-cyl, self-reg, from-IMEP) · [4] CyclicVar · [5] Knock · [6] LateComb.**
- Per element: `error ? 3 : (warning ? 1 : 0)` *(d1: warning→1, d2: error→3)* — i.e. a 9049
  cylinder **ERROR scores severity 3 = "send to motoring"**, not SAFE. Max is taken across
  cylinders and across the merged misfire rows → five scalars (MaxPress, Misfire, CyclicVar,
  Knock, LateComb) → `MergedCylinderErrors` → `Cylinder_Warnings` SV → into the same
  Array-Max clamp.
- Combustion is still cut on a cylinder error by **two independent paths**: the 9049's own
  IGNDI supervisor disarms spark/DI off the latched `CylPressError` global (FLOOR), and the
  9056 clamp (if wired, see gap W5) forces ≤ MOTORING where IGN/DI are deactivated per the
  MAX-LEVEL-OF-CONTROL table.

## APC_9056_ErrorMask.vi — the per-state arming masks

One connector input: `SYSTEM STATE`. Outputs `raster1..5mask` + `CylinderMask`. Two case
structures select boolean tables saved as front-panel defaults. **Decoded cell-by-cell from
the panel export** (bright yellow = TRUE/armed, dull = FALSE):

| table | SAFE (−1) | STAND_BY (0) | MOTORING (1) | IDLING (2) | FIRING (3) |
|---|---|---|---|---|---|
| raster masks (5×16) | all OFF | all OFF | all ON | all ON | all ON |

| CylinderMask row | SAFE | STAND_BY | MOTORING | IDLING | FIRING |
|---|---|---|---|---|---|
| MaxPressure | – | – | – | ✓ | ✓ |
| Misfire | – | – | – | – | – |
| Cyclic variability | – | – | – | – | – |
| Knock | – | – | – | ✓ | ✓ |
| Late combustion | – | – | – | – | – |

- The raster arming is **binary by state**: nothing armed in SAFE/STAND_BY, everything armed
  from MOTORING up. No per-slot nuance as-built.
- A second "ACTIVE ERRORS FOR LOW SPEED" table is ANDed in when
  `EngineSpeed < MinEngineSpeedforMask` — but **`EngineSpeed` is not on the connector pane**
  (unwired; always default 0 vs threshold 1000 ⇒ the branch is permanently "low speed"), and
  the low-speed table is **all-TRUE** anyway ⇒ double no-op. The plumbing for speed-dependent
  arming exists but is inert; note `EngineSpeed_rpm` is already available in WI's input
  cluster if it's ever wired.
- The per-cylinder table encodes exactly the motoring-vs-fired **disarm** intent (only
  MaxPressure + Knock armed, and only in IDLING/FIRING) — **but see gap W2: its consumer
  appears to be disabled.**

## APC_9056_MaskErrors.vi — DEAD CODE as-built

Function: elementwise `mask ? warning : 0` over a U8 severity array. **All six call sites
(5 rasters + cylinder, plus a second ErrorMask instance) sit inside a Diagram Disable
Structure "Disabled" frame** (WI print page d9) — the superseded post-hoc masking design.
The live design gates trips inline inside the tier loop instead.

## APC_9056_ClearSoftWarning.vi

Elementwise: `element == 1 ? 0 : element` ("Warning vector 0 to 4"). Clears soft warnings
only; severities ≥2 stay latched until the operator MASTER clear.

## APC_ClearErrorButton.vi (PC)

OK/Cancel dialog loop; OK → writes `APC_MASTER_ClearWarnings` := TRUE (100 ms poll). The
single operator entry point of the clear chain: PC button → MASTER SV → WI zero-latches +
SLAVE handshake → 9049 CylPress latch clear.

## Findings / gaps (W-series)

- **W1 — Raster arming is binary by state.** All-or-nothing per state (off below MOTORING).
  Any per-slot, per-state policy (e.g. arm coolant-temp warnings in STAND_BY) is new work.
- **W2 — The per-cylinder arming table is (very likely) inert.** `CylinderMask` +
  `MaskErrors` live only in the Disabled frame (d9); the live cylinder path
  (decode → merge → clamp) shows no mask join on the visible pages. Consequence as-built:
  cylinder diagnostics are effectively **armed in every state incl. MOTORING** on the 9056
  side, mirroring the 9049's own no-state-input latch (audit F3/F3a — same class of
  false-trip risk, now confirmed at both layers). **Bench check** (fold into the SIL-1
  warning-matrix drills): inject overpressure in MOTORING; if `Cylinder_Warnings` scores
  it, W2 is confirmed inert.
- **W3 — Speed-dependent arming is unwired scaffolding** (see ErrorMask above).
- **W4 — A cylinder ERROR clamps to MOTORING (3), not SAFE.** Deliberate-looking (motoring
  keeps the engine controlled while combustion stops) but a policy decision Python's A3 port
  must consciously adopt or change — the team should confirm intent.
- **W5 — The clamp output is computed but not consumed** (pre-existing finding,
  `docs/shadow-findings.md`): `STATE LIMITATION FROM WARNINGS` is not wired into the
  StateMachine; only the B0 watchdog clamp (`PCnotResponding OR 9049notResponding →
  Select(−1:3) → Min`) reaches the SM input today. Wiring WI's output into that same Min
  is the standing prerequisite for A3 parity (phase-A doc).
- **W6 — No temporal rules.** Trip scoring is instantaneous max-latch: no debounce, no
  persistence windows, no hysteresis, no escalation-over-time. (The 4 tiers are *level*
  tiers, not time tiers.) The "author the temporal rules" A3 task in
  `docs/migration-seam.md` remains fully greenfield.
- **W7 — Two severity dialects share one scale.** Raster severities span 1..4 by tier;
  cylinder severities only ever take {0, 1, 3}. Fine under Array-Max, but a port must keep
  the shared meaning of 0..4 straight (and 2/"send to idle" is unreachable from cylinders).

## Diff against the existing Python port (`supervisory/monarch/warning_policy.py`)

The A3 port already exists (built 2026-07-06 from the WarningIntegration export). Checked
against these prints, it **matches** on: 4 thresholds/channel + sign, severity legend and
{0,1:3, 2:2, 3:1, 4:−1} mapping, max-latch ratchet, soft-1 self-clear, operator
clear-as-zero, heartbeat stall detectors kept indicator-only. **Deltas the prints expose:**

1. **No state-dependent arming.** The port's `ChannelLimits.enabled` is a static per-level
   tuple; as-built, `ErrorMask` disarms *everything* in SAFE/STAND_BY and arms everything
   from MOTORING up. In a shadow comparison the port would raise warnings in SAFE/STAND_BY
   where LabVIEW stays silent. Either extend the port with a per-state arming input
   (faithful) or record the deviation as a deliberate improvement (per W1) — decide, don't
   drift.
2. **The cylinder merge is now specified.** The port takes pre-merged `extra_levels`;
   the producer contract is documented above (row layout, `error?3:(warning?1:0)`, max
   across cylinders) for when the 9049 bitfield decode gets modeled.
3. **Live limit values are SV-loaded at runtime** (`Raster*_WarningLevels/_WarningSign`),
   so a faithful shadow needs those values captured from the running system, not the
   panel defaults in the export.

Unit-test against the decoded tables above; treat W1–W7 as documented deviations a
redesign may fix (with team sign-off), not silently.

---

## Side findings from the same print batch

- **`APC_9056_FPGA_main.vi` — the 9056 FPGA has its own RT-stall safe-hold.** An
  `RT watchdog` boolean toggled by the RT side is edge-checked on a 10 ms clock;
  `Counter max` (default **100** ⇒ 1 s) overflow → "RT counter overflow: setting SAFE mode"
  → the DI/DO interface case writes **all AOs (NI9264×16, NI9266×8) = 0 and all DOs
  (NI9375×16) = FALSE** — diagram comment: *"SAFE state is applied if RT watchdog is not
  alive"* (d2). With the 9049 FPGA spark/DI watchdog, **both cRIOs now have a confirmed
  below-RT hardware safe fallback**; the safe-hold invariant does not depend on the 9056 RT
  loop surviving. Caveats: the actual `Counter max` written by RT at init is unconfirmed
  (default 1 s), and AO=0/DO=FALSE is only safe if actuators are fail-safe de-energized
  (vents are 0=open per the MAX-LEVEL table note — consistent). Panel warns "low level FPGA
  interface only — RT configures". Also on board: a 0.5 s `FPGA Hearbeat` (mirrored to the
  `9056_HeartBeat` SV that WI monitors), chassis temp raw, and a **`cRIO_Trig7`
  toggle-period decoder** ("Ticks per toggle" 13-entry table, margin 250 → `Detected mode`)
  whose producer/consumer is unidentified — open question.
- **`APC_9049_checkAI.vi`**: one-liner — `size(AIdata) == 7200` → bool ("Makes sure that
  the AI got the complete cycle"). The programmatic form of the SIL-1 Step-2 full-cycle
  check.
- **`APC_9049_CycleAvgSignals.vi`**: builds the `CRIo9049_CycleAvgSignals` **name array**
  (TimeStamp + ControlSettingsRaster + CycleRaster name lists concatenated) — the signal-name
  registry the pollers/mapping use to label `9049_MeasAndCalc` (confirms the README's
  inference). **Not** related to `MaxDevFromAvg` averaging (that lives in the
  already-printed analytics chain).
