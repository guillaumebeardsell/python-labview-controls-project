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
5. **Run `APC_9049_RT_main.vi`** — its *own* panel is just the title screen; the live
   controls/indicators are on its parallel **loop sub-VIs**. Open each one's front panel to
   interact (double-click the subVI in the RT_main block diagram while it runs, or open it from
   the project). Where things live:
   - **`APC_9049_TS10ms_loop.vi`** — the **`EPTControl`** cluster (`SimEnable`, `SimPeriod`,
     `SyncEnable`, `WatchdogIn`, `NumberOfCrankTeeth`, `MissedCrankFlagClr`/`MissedCamFlagClr`),
     the **`EPTData`** indicator cluster (`CrankStalled`, `SyncStopped`, `MissedCrankFlag`,
     `MissedCamFlag`, `CrankCount`, `CurrentPosition`, `Period`, `CrankSigOS`), top-level
     **`Speed (RPM)`**, `Override PC settings` + `manual spark/injection enable` + `manual SA`,
     the `InjectionEnable`/`SparkEnable` 6-LED arrays, `Manual Clear Sync Errors`,
     `Must Use Cam & Z` / `1/2 Z pulse`, `PFI0 mode`, and the `DIControl` / `DI_Data_Mod5/6`
     clusters.
   - **`APC_9049_CAS_loop.vi`** — the **`Graph time`** cycle chart (0…7200), **`rpm from DAQ`**,
     **`Enque?`**, **`ForceReSync`**, `error in` / `CAS DAQmx error`.
   - **`APC_9049_FPGA_IGNDI_supervisor.vi`** — **`NumberOfActiveIGN_DI`**, `SI1–6`/`DI1–6` LEDs,
     `Number of inactive sparks/injections`.
   *(Deployed/headless, none of these panels are visible and controls take their compiled
   defaults — F6; interactive SIL-1 is the only place you drive them by hand.)*

*Accept:* target reachable; motoring XML present; command path answers a no-op.

---

## Step 1 — Start RT_main + virtual crankshaft, confirm sync

1. **Run `APC_9049_RT_main.vi`** (dev environment, or a bench build). Open the
   **`APC_9049_TS10ms_loop.vi`** panel.
2. On that panel, expand the **`EPTControl`** cluster and set **`SimEnable = TRUE`**;
   set **`SimPeriod`** for the target rpm — `SimPeriod = 60·4e7 / (rpm·3600)` → **741 ≈ 900 rpm**,
   **370 ≈ 1800 rpm** (saved default is 500 ≈ 1333 rpm; or use the vendor `speed2ticks.vi`).
   Leave **`SyncEnable = TRUE`** and **`NumberOfCrankTeeth = 3600`**. Confirm
   `Must Use Cam & Z` / `1/2 Z pulse` match the engine's actual sensor set (F6).
3. **Confirm the sim is alive:** in **`EPTData`**, `CrankSigOS` shows activity and the sync
   fields below start moving. *Caveat:* the raw crank is a **3600-line encoder →
   54 kHz A @ 900 rpm** (108 kHz @ 1800), far above panel-eyeball rate, so an indicator only
   tells you alive-vs-dead — read the real **pass** off the sync fields, not a "toggle."

*Accept (sync acquired) — in `EPTData` + top-level `Speed (RPM)`:* `CrankStalled` **OFF**,
`SyncStopped` **OFF**, `MissedCrankFlag`/`MissedCamFlag` **OFF**; `CrankCount` and
`CurrentPosition` **incrementing/rolling**; `Speed (RPM)` ≈ the rpm you dialed. If
`SyncStopped` stays TRUE, click **`Manual Clear Sync Errors`** (and `MissedCrankFlagClr` +
`MissedCamFlagClr`) once and re-check — persistent = cam/Z config mismatch (chase before Step 2).

> **Scoping the sim (optional raw check — replaces the earlier "missing-tooth" description,
> which does not apply: this is an incremental encoder, no missing tooth).** In sim mode the
> physical encoder inputs are internally replaced, so the sim crank/cam live *inside the FPGA*
> — scopeable only if the bitfile routes them to a module pin (check the FPGA I/O node /
> [EPT-UM] for a monitor terminal). If routed: scope (or better, a logic analyzer for the
> encoder rate) DC-coupled, 0–5 V, timebase ~2 µs/div to resolve 54 kHz **A**; **trigger on the
> Z index** (once/rev) to stabilize, and confirm one **cam** pulse per two revs. Verify the
> A-rate tracks rpm. If it isn't routed out, don't chase it — the `EPTData` sync fields are the
> real proof, and raw-encoder scoping is properly a **SIL-2** task (there you generate A/B/Z/cam
> yourself and scope them at the source).

---

## Step 2 — Does Trig0 follow the sim? (CAS acquisition) — *open question, bench-decides*

The FPGA export shows the CAS sample clock `cRIO_Trig0` wired from EPT's `CrankSigOut`, which
carries the simulated signal in sim mode — so with sync acquired (Step 1) CAS **should** clock.
Confirm on the CAS panel:
1. Open the **`APC_9049_CAS_loop.vi`** front panel.
2. Watch the **`Graph time`** chart (X = 0…7200 samples): with sync it should **fill with a
   full 7200-sample trace once per engine cycle**; before sync it's flat/stale and the loop
   sits in its ~1 Hz DAQ-timeout retry.
3. Read **`rpm from DAQ`** — it should be ≈ your dialed rpm. Because it's derived from the
   Trig0/encoder clock, a correct value **is** the confirmation that Trig0 follows the sim.
   Cross-check against `Speed (RPM)` on the TS10ms panel.
4. Confirm **no DAQ error** — `error in` and `CAS DAQmx error` clusters read code **0**.
5. If it won't clock, click **`ForceReSync`** once and re-check.

*Accept:* `Graph time` delivers full 7200-sample cycles at the simulated cycle rate (**133 ms
@ 900 rpm**), `rpm from DAQ` ≈ setpoint, DAQ error 0. **Record the answer** to the Trig0-in-sim
open question (audit §9). If it never clocks, Trig0 does **not** follow the sim → CAS-acquisition
testing needs SIL-2's real encoder into Mod3 DIO0–3 — note and escalate.

> **Result (2026-07-14): ✅ Step 2 CLOSED — Trig0 follows the sim.** `rpm from DAQ` = the rpm set
> on TS10ms, `Graph time` delivers full 7200-sample cycles, and the DAQ error clusters read 0.
> CAS acquisition clocks in sim mode on the real 9049; **no SIL-2 encoder needed for acquisition
> testing**, and the CAS → analytics → `Pcyl_Diag` chain is now exercisable in sim (Steps 3–6).

---

## Step 3 — Verify the motoring profile on-target: CLEAR → `CylPressError = FALSE` (F3)

Pressure inputs are floating 9222 terminals, so the diagnostics can false-trip on startup
garbage (first-cycle zero-pad, motored-CA50 noise, Expected-IMEP-0 trap — F3).
1. With sync + CAS running (Steps 1–2) and the motoring XML loaded, let CAS deliver a few
   cycles (watch `Graph time` fill).
2. On the PC, open **`APC_PC_UI_Errors.vi`** → **SIGNAL WARNINGS / CYLINDER** area → click
   **CLEAR WARNINGS** (drives `APC_MASTER_ClearWarnings` → 9049 relay `APC_SLAVE_ClearWarnings`,
   which resets the per-category **Error** feedback-latches).
3. Read **`9049_Global_CylPressError`** — in NI **Distributed System Manager** (`10.1.10.171`
   → `APC_SharedVars` → `9049_Global_CylPressError`), or via the UI's error LEDs.

*Accept:* after CLEAR, `CylPressError = FALSE` and **stays** FALSE under steady sim motoring.
If it re-latches, note *which* category tripped from the harness `PcylDiagWarningsAndErrors`
flags (max-pressure / cyclic-variability / misfire-from-IMEP / self-reg / cyl-to-cyl / knock /
late-combustion) and widen that one threshold per SIL-0 Step 3 — or drive the channel (Step 6).
This is the on-hardware version of the SIL-0 CLEAR gate.

---

## Step 4 — State-gated spark/DI scheduling

Per-cylinder enable = `¬CylPressError ∧ ActivateCylinder ∧ UI-enable ∧ (SYSTEMSTATE ≥ 2)`,
spark and DI separately (the confirmed TS10ms gate). Drive the gate, watch the counts, scope
the outputs.
1. **(Only if scoping DI)** on TS10ms `DIControl`, set `ModuleEnable` / `HVEnable` /
   `InjectEnable` per the bench plan and check `DI_Data_Mod5/6.ModulePresent` — but first
   **decode `Fault1 = 126`** (F9) before trusting DI health. Keep the NI-9751 Key de-energized
   otherwise.
2. **Satisfy the state gate** — get `9049_Global_SYSTEMSTATE ≥ 2` by: running the 9056 (real
   relay), injecting the SV in DSM, or — **bench-only** — TS10ms `Override PC settings = TRUE`
   + `manual spark/injection enable` LEDs (log F1). Override *bypasses* the gate, so use it only
   to prove output wiring, never to conclude the gate works (that's step-5c).
3. **Enable cylinders via the real command path** — from Python (`monarch_operate.py`), set
   InjectionEnable/SparkEnable; the `InjectionEnable` / `SparkEnable` 6-LED arrays on TS10ms
   should light.
4. On **`FPGA_IGNDI_supervisor`**: confirm **`NumberOfActiveIGN_DI` = 12**, `SI1–6` + `DI1–6`
   LEDs on, `Number of inactive sparks/injections` = 0.
5. **Scope the outputs** — spark on **Mod4** (DIO), DI on **Mod5/6**. Sync your scope with the
   DI module's built-in trigger via TS10ms `DIControl → DI Scope Trigger Event` (e.g. INJECTION
   PULSE). Dummy loads / probes only.
6. **Sweep SA / SOI from Python** — change spark advance and injection SOI via the command
   path; watch the scheduled edges move on the scope and the on-panel `SA [CADBTDC]` /
   injection-window values update.

*Accept:* outputs appear **only** with `SYSTEMSTATE ≥ 2` and `CylPressError` FALSE;
`NumberOfActiveIGN_DI` = 12; Python SA/SOI moves the scheduled edges. Override-forced outputs
(step 2) prove wiring only — the gate test is step-5c.

---

## Step 5 — Drills (the operational proof, and F-hazard resolution)

Run each, record pass/fail + observed behaviour in the commissioning book:

- **5a — Watchdog.** On TS10ms, `EPTControl.WatchdogIn` toggles each 10 ms tick and
  `FPGA Heartbeat` blinks. Stop the RT loop (abort `RT_main`, or breakpoint TS10ms) → WatchdogIn
  stops → the FPGA kills spark/DI (IGNDI `SI/DI` LEDs off, `NumberOfActiveIGN_DI` → 0). Restart →
  **document whether sync + outputs auto-recover or need a manual re-arm** (audit §9).
- **5b — Sync-loss.** Set `EPTControl.SimEnable = FALSE` (or perturb `SimPeriod`) → `EPTData.SyncStopped`
  TRUE, `MissedCrankFlag`/`MissedCamFlag` may set, `CrankCount`/`CurrentPosition` → 0 (does **not**
  latch a stop) → outputs gate off. Restore `SimEnable = TRUE` → click `Manual Clear Sync Errors`
  (+ `MissedCrankFlagClr`/`MissedCamFlagClr`) → confirm re-sync (Step 1 accept).
- **5c — State-gate walk.** From the **real command path** step `SYSTEMSTATE` 0→1→2→3: IGNDI
  `SI/DI` LEDs and `NumberOfActiveIGN_DI` must be **0 below state 2** and 12 at ≥ 2. Do this with
  `Override PC settings = FALSE` — Override masks the gate.
- **5d — `CylPressError` veto + clear.** Force a trip (Step 6 — overrange a Pcyl channel past its
  `MaxPCylMax` with a function generator) → `9049_Global_CylPressError` latches → IGNDI `SI/DI`
  LEDs off / `NumberOfActiveIGN_DI` drops → PC **CLEAR WARNINGS** → gating restored.
- **5e — Echo live-capture (F4).** Enable all six cylinders; capture `9049_ControlSettings`
  (DSM or the Python telemetry). Read whether **[1] InjectionEnable / [5] SparkEnable** are
  **1 or 63** (Boolean-array-to-number bitmask), and that **[0] = the `PFI0 mode` control, not
  system state**. Reconcile → **fix `supervisory/monarch/settings_9049.py`**.
- **5f — E-stop.** Trip the physical e-stop with the 9049 in the loop → outputs die → confirm
  the recovery path. End-to-end, not simulated.
- **5g — Recording (F6).** On CAS_loop set **`Enque? = TRUE`**, run a REC drill (the SAVE loop) →
  confirm readable **TDMS** files land (pull them per `docs/crio-file-access.md`) → record the
  intended compiled-default of `Enque?`.

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

For each injected fault, watch the harness **`PcylDiagWarningsAndErrors`** flags and
`9049_Global_CylPressError` (DSM on `10.1.10.171`) and confirm the **mapped Error** (F3 table:
misfire-from-IMEP / self-reg / cyl-to-cyl / knock / late-combustion / max-pressure) **trips and
latches**, IGNDI `NumberOfActiveIGN_DI` drops, and PC **CLEAR WARNINGS** clears it. Produce the
**false-trip matrix** (which fault trips which metric at the loaded limits) for the commissioning
book.

---

## SIL-1 exit criteria / deliverables

- [ ] Sync acquired on-target at ≥1 rpm setpoint; `Speed(RPM)` correct.
- [x] **Trig0-follows-sim = YES — Step 2 closed** (2026-07-14 bench: `rpm from DAQ` = set rpm,
      `Graph time` full 7200-sample cycles, DAQ error 0).
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
