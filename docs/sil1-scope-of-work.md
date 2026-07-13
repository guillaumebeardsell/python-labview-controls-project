# SIL-1 — Scope of Work (click-level)

**What SIL-1 is:** run the **real 9049** (`APC_9049_RT_main.vi`) on a bench with a
**virtual crankshaft** from the EPT internal pattern simulator — **HV and fuel physically
absent**. It proves, on-target, the whole chain the desktop SIL-0 harness can't touch:
crank **sync**, **CAS acquisition**, the `Pcyl_Diag → CombCluster2Array →
9049_Global_CylPressError` **latch/veto**, **state-gated spark/DI scheduling**, and the
operational **drills** (watchdog, sync-loss, state-gate, clear-warnings, echo, recording).

**What SIL-1 is NOT:**
- **Not** the encoder input path — the sim injects *at the EPT input*, so the NI-9401
  wiring, deglitch filters, and ½-Z synthetic-cam logic are **not** exercised → that's **SIL-2**.
- **Not** real actuation — spark coils / DI drivers into real loads is **SIL-3**.
- **Not** a fueled run — F1/F5 provisions (`Override`, `SimEnable`, `UsePcylDatabase`) are
  **used** here but must be **OFF** before fuel (pre-fuel checklist, audit §8).

**Depends on SIL-0:** the **motoring** `9049_WarningLevels` profile must already be derived
and loaded on the 9049 (`docs/sil0-scope-of-work.md` Step 3). SIL-1 validates that profile
on-target and resolves the open questions SIL-0 couldn't (Trig0-follows-sim, echo bitmask F4,
watchdog recovery).

Derived from `docs/9049-openloop-audit.md` §7 (SIL-1) + §4 (F1–F9) + §8 (pre-fuel checklist).
Signal/gate detail lives there; this doc is the click-level procedure.

---

## ⚠ Safety preconditions (verify before every SIL-1 session)

- **HV supply OFF and locked out; no fuel; injectors and coils disconnected** (or into
  dummy loads only — energizing real actuation is SIL-3). Spark/DI *scheduling* is exercised
  here, so treat the Mod4/5/6 connector outputs as **electrically live** — scope/dummy only.
- **Key interlock:** the NI-9751 drivers must be powered+enabled for *any* spark to appear;
  keep them **de-energized** unless a specific scope step needs them, and decode `Fault1=126`
  first (F9).
- **E-stop reachable** and the e-stop path itself is a drill item (Step 5f).
- **Override is a bench aid, not a shortcut (F1):** `Override PC settings = TRUE` bypasses
  **both** the `SYSTEMSTATE ≥ 2` and `¬CylPressError` gates. Use it only for isolated
  bench steps, log every use, and confirm it is **FALSE** at session end.

---

## Step 0 — Bench + tooling setup

1. cRIO-9049 on the bench, powered, on the control network; note its IP (`10.1.10.171`).
2. Dev PC with `MONARCH.lvproj` open; connect to the 9049 RT target.
3. Confirm the **motoring warning XML** is on the target (`docs/crio-file-access.md` →
   `cat /home/lvuser/natinst/bin/CylWarningLevels.xml`). If absent, do SIL-0 Step 3 first.
4. Python command path ready (for the SA/SOI sweep in Step 4): gateway with `source=PYTHON`,
   `examples/monarch_operate.py` / `tools/send_command.py` — see `docs/command-path-asbuilt.md`.
5. Open, ready to watch: **`APC_9049_RT_main.vi`** (top level), and the **`TS10ms_loop`** and
   **`CAS_loop`** sub-panels (SimEnable/SimPeriod/Override live on `TS10ms_loop`; `Enque?`,
   `Cycles to measure` on `CAS_loop`).

*Accept:* target reachable; motoring XML present; command path answers a no-op.

---

## Step 1 — Start RT_main + virtual crankshaft, confirm sync

1. Run **`APC_9049_RT_main.vi`** interactively from the dev environment (or a bench build).
2. On the **`TS10ms_loop`** panel: set **`EPTControl.SimEnable = TRUE`** and
   **`SimPeriod`** for the target rpm — `SimPeriod = 60·4e7 / (rpm·3600)` → **741 ≈ 900 rpm**,
   **370 ≈ 1800 rpm** (or use the vendor `speed2ticks.vi`).
3. Confirm the sim is producing signals: `SimCrankSig` / `SimCamSig` indicators toggling
   (scope-checkable).

*Accept (sync acquired):* `CrankStalled` and `SyncStopped` **clear**; `CrankCount` /
`CurrentPosition` **rolling**; `Speed(RPM)` matches the `SimPeriod` you set.

---

## Step 2 — Does Trig0 follow the sim? (CAS acquisition) — *open question, bench-decides*

The FPGA export shows `cRIO_Trig0` wired from `CrankSigOut` (which carries the simulated
signals in sim mode), so CAS acquisition **should** clock. Confirm on hardware:
1. Watch **`CAS_loop`**: it should **stop timing out** (no more ~1 Hz idle retry) and start
   delivering **7200-sample cycles** (of whatever the 9222 terminals float at).

*Accept:* CAS_loop delivers full 7200-sample cycles at the simulated cycle rate. **Record
the answer** to the Trig0-in-sim open question (audit §9). If it does *not* clock, SIL-1
acquisition testing needs SIL-2's real encoder — note and escalate.

---

## Step 3 — Verify the motoring profile on-target: CLEAR → `CylPressError = FALSE` (F3)

The pressure inputs are floating 9222 terminals, so the diagnostics may false-trip on
startup garbage (first-cycle zero-pad, motored-CA50 noise, Expected-IMEP-0 trap — F3).
1. With the motoring XML loaded, let CAS run a few cycles.
2. From the PC UI, fire **CLEAR WARNINGS** (`APC_PC_UI_Errors`) → `APC_MASTER_ClearWarnings`
   → 9049 relay `APC_SLAVE_ClearWarnings`.
3. Observe `9049_Global_CylPressError`.

*Accept:* after CLEAR, `CylPressError = FALSE` and **stays** false under steady sim motoring
(no floating-input latch). If it re-latches immediately, the motoring thresholds are too
tight for the floating inputs — widen per SIL-0 Step 3 (or drive the channels, Step 6).

---

## Step 4 — State-gated spark/DI scheduling

Per-cylinder enable is `¬CylPressError ∧ ActivateCylinder ∧ UI-enable ∧ (SYSTEMSTATE ≥ 2)`,
spark and DI separately. Drive the state gate and scope the outputs.
1. **Satisfy the state gate** — get `9049_Global_SYSTEMSTATE ≥ 2` by one of: running the 9056
   (real relay), shared-variable injection, or — **bench-only** — `Override` mode (log F1).
2. Enable cylinders via `PC_ControlSettings` (the real command path).
3. Observe **`NumberOfActiveIGN_DI` = 12** (6 spark + 6 DI).
4. **Scope** the **Mod4 spark** and **Mod5/6 DI** outputs (dummy loads / probes only).
5. **Sweep SA / SOI** from the **Python command path** (`monarch_operate.py`) and watch
   `dT inj` / `SparkOut` move accordingly.

*Accept:* outputs appear **only** with the state gate satisfied and `CylPressError` false;
SA/SOI commands from Python move the scheduled edges as expected.

---

## Step 5 — Drills (the operational proof, and F-hazard resolution)

Run each, record pass/fail + observed behaviour in the commissioning book:

- **5a — Watchdog.** Stop the RT loop (abort / breakpoint) → FPGA `WatchdogIn` stops toggling
  → **outputs die**. Resume → **document the recovery behaviour** (auto-resume vs latched —
  audit §9 open question).
- **5b — Sync-loss.** Inject a sync loss (stop the sim / glitch `SimPeriod`) → `SyncStopped`
  TRUE, `CrankCount`/`CurrentPosition` → 0 (does **not** latch) → outputs gate off; restore →
  re-sync.
- **5c — State-gate walk.** Step `SYSTEMSTATE` below 2 → spark/DI provably **dead**; ≥ 2 →
  enabled. Prove it from the **real command path**, not Override.
- **5d — `CylPressError` veto + clear.** Force a trip (overrange a channel past `MaxPCylMax`
  via a function generator, Step 6) → `CylPressError` latches → spark/DI gated off → **CLEAR
  WARNINGS** releases it → gating restored.
- **5e — Echo live-capture (F4).** Drive **all six cylinders enabled**, capture
  `9049_ControlSettings`, and read whether **[1] InjectionEnable / [5] SparkEnable** are
  **1 or 63** (bitmask), and that **[0] is PFI0-mode, not system state**. Reconcile, then
  **fix `supervisory/monarch/settings_9049.py`** to match reality.
- **5f — E-stop.** Exercise the e-stop path end-to-end with the 9049 in the loop.
- **5g — Recording (F6).** Set **`Enque? = TRUE`**, run a **REC** drill → confirm readable
  **TDMS** files appear; record the intended compiled-default of `Enque?`.

*Accept:* all drills pass; F4 echo reconciled and `settings_9049.py` updated; watchdog and
sync-loss recovery behaviours documented.

---

## Step 6 — False-trip / latch matrix (needs a pressure source)

The full combustion-fault matrix (misfire / knock / first-cycle) can't be driven from a
floating 9222. Pick a pressure-injection method:
- **Function generator / AO on 1–2 channels** — enough for the `MaxPCylMax` (overrange) and
  crude `MAPO` trips (5d).
- **Seam-A sim-read** (optional build) — wrap CAS_loop's DAQmx Read in a sim case that reads
  `cycle_*.csv` + waits one cycle period; lets you replay the **SIL-0 fault traces**
  (`--misfire`, `--knock`, first-cycle zero-pad) through the real diagnostic chain. Most
  faithful, most LabVIEW surgery.
- **`UsePcylDatabase`** (canned data) — fastest but it's an F5 hazard flag and its render was
  ambiguous; if used, VERIFY it's returned to FALSE afterwards.

For each injected fault, confirm the **mapped Error** (F3 table: misfire-from-IMEP /
self-reg / cyl-to-cyl / knock / late-combustion / max-pressure) **trips and latches**
`CylPressError`, and that **CLEAR WARNINGS** clears it. Produce the **false-trip matrix**
(which fault trips which metric at the loaded limits) for the commissioning book.

---

## SIL-1 exit criteria / deliverables

- [ ] Sync acquired on-target at ≥1 rpm setpoint; `Speed(RPM)` correct.
- [ ] **Trig0-follows-sim answered** (audit §9); CAS delivers 7200-sample cycles.
- [ ] Motoring profile validated on-target: CLEAR → `CylPressError=FALSE` holds under motoring.
- [ ] State-gated spark/DI scheduling scoped; SA/SOI sweep from Python confirmed.
- [ ] Drills 5a–5g passed and documented; **watchdog recovery** + **sync-loss** behaviours recorded.
- [ ] **F4 echo reconciled** → `supervisory/monarch/settings_9049.py` corrected.
- [ ] False-trip / latch matrix produced (method noted; Seam-A replay if built).
- [ ] Pre-fuel checklist items 7–10 (audit §8) provably satisfiable from this bench.
- [ ] **Session close-out:** `Override = FALSE`, `SimEnable = FALSE`, `UsePcylDatabase = FALSE`
      verified on the deployed build before it can ever see fuel (F1/F5).

## Then → SIL-2 / SIL-3

- **SIL-2** — real A(+B)+Z(+cam) TTL into Mod3 DIO0–3 (Arduino emulator or a µC); covers the
  9401 input path, deglitch, synthetic-cam, quadrature, and speed transients the internal sim
  can't. (1800 rpm = 108 kHz A / 30 Hz Z, phase-locked.)
- **SIL-3** — actuation dry tests: coils on bench plugs, DI into dummy loads; Key interlock;
  decode `Fault1=126` (F9). This is where the team's commissioning plan takes over.
