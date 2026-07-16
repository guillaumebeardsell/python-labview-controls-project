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
spark and DI separately (the confirmed TS10ms gate — README "TS10ms section C", Deck p.12).
Step 4 proves three things at once: the FPGA scheduler produces edges at the commanded crank
angles, Python moves them over the **real command path**, and the observables (LED arrays,
`NumberOfActiveIGN_DI`, scope) that drills 5c/5d depend on all work.

### 4a — Bench footprint + the state-relay chain (read before wiring anything)

> **Pending architecture decision:** `docs/engine-only-9056-tradeoff.md` (2026-07-16)
> weighs running engine-only **without** the 9056 (Option B: a local state limiter + PC_HB
> watchdog on the 9049). This step is written for the **as-built** chain below (Option A /
> status quo). If Option B is adopted, 4c and drill 5c/5h re-target the local limiter and
> the whole matrix + gate drills re-run on the modified build (the memo's regression gate).

The gate input `9049_Global_SYSTEMSTATE` is **not a knob you can set on the 9049** — it is
the tail of a relay chain, so this is the first SIL-1 step that needs **all three tiers
running simultaneously**:

```
mode request (HMI or Python) ─► PC_ControlSettings ─► 9056 TS_loop StateMachine
  ─► Min(requested, watchdog clamp: notResponding? −1 : 3) ─► SYSTEM STATE
  ─► 9056_MeasAndCalc (SV) ─► 9049 CAS_loop polls + echoes ─► 9049_Global_SYSTEMSTATE
  ─► TS10ms gate C
```

Running config for all of Step 4 (and Step 5):
1. **9049**: `RT_main` with sim crank + CAS delivering cycles (Steps 1–3 green). Best: keep
   the 6a sim branch playing **`baseline_motored`** — real finite traces hold
   `CylPressError = FALSE` (the drill XML must NOT be loaded; motoring profile only).
2. **9056**: its RT app running (the real relay — no shortcut; see below).
3. **PC**: `UI_System` + `UI_Main` (+ the gateway if commanding from Python). The PC **must
   stay alive**: a frozen `PC_HB` trips `PCnotResponding` → the loss-of-PC clamp Selects −1
   → SAFE, in either mode (`docs/command-path-asbuilt.md` §5).

As-built facts that matter here:
- **The only state limiter actually wired is the watchdog clamp** —
  `PCnotResponding ∨ 9049notResponding ∨ 9056notResponding → Select(−1 : 3)`. The
  warnings-derived limit is computed but **not consumed** (gap W5,
  `docs/9056-warning-policy-asbuilt.md`). So floating 9056 plant sensors **cannot** hold the
  state down on this bench; if the state won't rise, look at the three `*notResponding` LEDs
  on `UI_Main`, not at warnings.
- **DSM injection of `9049_Global_SYSTEMSTATE` is a trap**: CAS_loop re-writes it from the
  polled 9056 value every cycle (~133 ms @ 900 rpm), so a hand-written value is clobbered
  almost immediately (watch it snap back in DSM). Use the real chain.
- `Override PC settings = TRUE` + `manual spark/injection enable` + `manual SA` (TS10ms)
  bypasses **both** gates (F1) — it proves Mod4/5/6 **wiring only**, never the gate. Log every
  use; FALSE immediately after.

### 4b — DI-module health + decode `Fault1 = 126` (F9) — before anything touches the 9751s

Spark is **interlocked on the DI drivers**: the FPGA's DI supervisor emits the **`Key`** that
unlocks the spark output block (FPGA_main section E). No healthy/powered NI-9751 ⇒ no spark
edges, regardless of the gate — so this sub-step comes first even for a spark-only session.
1. On TS10ms `DIControl`, set **`ModuleEnable = TRUE` only** (leave `HVEnable` /
   `InjectEnable` FALSE for now).
2. Read **`DI_Data_Mod5`** and **`DI_Data_Mod6`**: `ModulePresent` TRUE on both; record
   `Fault1`/`Fault2` exactly as displayed.
3. **Decode `Fault1 = 126` against the NI-9751 manual** (it is a bitfield — write down the
   meaning of every set bit in the commissioning book; audit §9 open question). A
   missing-HV-supply fault is *expected* on this bench (HV locked out) — record it and move
   on; anything pointing at the module or driver channels themselves must be chased before
   trusting any DI observable.
4. Energize the 9751s / Key **only** for the scope sub-steps in 4e that need them, per the
   bench plan; de-energize after.

### 4c — Raise the state over the real command path

1. Start all three tiers (4a). On `UI_Main`: `9056notResponding` / `9049notResponding` /
   `PCnotResponding` all **off**; e-stop clear.
2. Choose the command source. For the Python sweep: flip the HMI source switch to **PYTHON**
   (the `PYTHON (effective)` LED confirms), then on the PC:
   ```
   python examples/monarch_operate.py --safety-only-mirror
   ```
   **`--safety-only-mirror` matters**: without it the HMI panel's own requests mirror through
   Python and re-assert within a tick — the panel and your CLI fight over the intent. With it,
   panel e-stop + force overrides still flow (the safety floor), but mode/set belong to the CLI.
3. `status` → expect `connected=True stale=False commanding=True state=0 source=PYTHON`.
4. `mode idling` → within a tick or two `status` shows `state=2`. Confirm the echo end-to-end:
   DSM (`10.1.10.171` → `APC_SharedVars`) → `9049_Global_SYSTEMSTATE` = **2**.
5. If the state won't rise: re-check the three `*notResponding` LEDs (the clamp is the only
   wired limiter — 4a), the e-stop, and `command_source`; a NACK reason appears in
   `status` as `last_nack=…`.

### 4d — Enable spark/DI, watch the counters

**Set timing before enables** — the gateway range-checks `Speed ref` **only**; SA/DI values
pass through **unvalidated** (`docs/command-path-asbuilt.md` §3), so type carefully. Bench
values (JSON, **no spaces** inside a value — the CLI splits on whitespace; booleans lowercase):
```
set spark_advance_cadbtdc 20
set di_advance_cadbtdc 60
set di_duration_ms 2.5
```
Then the enables:
```
set activate_cylinder [true,true,true,true,true,true]
set ign_enable true
set di_enable true
```
Observe, in order:
1. TS10ms — the **`SparkEnable`** and **`InjectionEnable`** 6-LED arrays all light (the
   gate output, post-`SYSTEMSTATE`/`CylPressError`).
2. **`FPGA_IGNDI_supervisor`** — `NumberOfActiveIGN_DI` = **12** (6 SI + 6 DI), `SI1–6` +
   `DI1–6` LEDs on, `Number of inactive sparks/injections` = 0. *Caveat:* SI channels only
   count with the `Key` present (4b) — DI = 6 but SI = 0 with everything enabled points at
   Key/9751 power, not the gate.
3. **Per-cylinder truth test**: `set activate_cylinder [false,true,false,false,false,false]`
   → exactly `SI2` + `DI2` active (count = **2**). Restore all six. (This also stages the 5e
   bitmask capture.)

### 4e — Scope the edges + sweep SA/SOI from Python

Hookup (dummy loads / probes only — treat connectors as live):
- **Spark** = Mod4 `DIO0–5` (cyl 1–6). **DI** = Mod5/Mod6 outputs.
- Trigger: TS10ms `DIControl → DI Scope Trigger Event` (e.g. INJECTION PULSE), or the FPGA's
  **Trig1** once-per-cycle pulse if it's routed out — anything cycle-locked.

Expected geometry at 900 rpm (cycle = 133.3 ms, **1° = 0.185 ms**): six spark pulses per
cycle spaced **120° = 22.2 ms** (TDC offsets 0/480/240/600/120/360 — firing order
1-5-3-6-2-4); spark **dwell is hard-coded 4 ms** in `SparkSettings` (≈ 21.6° @ 900 rpm).

The sweep (record commanded value vs measured edge for each point):
1. `set spark_advance_cadbtdc 10` → `20` → `30`: each +10° moves the spark edge
   **1.85 ms earlier** relative to the cycle trigger; the TS10ms `SA [CADBTDC]` indicator
   follows each step.
2. `set di_advance_cadbtdc 40` → `60`: SOI edge moves 3.7 ms. `set di_duration_ms 1.5` → `3`:
   pulse width changes 1.5 ms.
3. *If DI edges refuse to move:* the DI window limits are **diagram constants**
   (`Window_Start/End` printed as 90/−30 DBTDC; the GDoc says 200/0) — an SOI outside the
   window may simply not schedule. Check the window before suspecting the command path.
4. Repeat one spark point at a second rpm (e.g. 1800 → 1° = 0.093 ms) to confirm the
   angle-domain scheduling scales with speed.

### 4f — Same sweep from the HMI (UI mode) — the other writer

The GUI is the *second* legitimate writer of `PC_ControlSettings` (B3.c promote,
`docs/command-path-asbuilt.md` §2), and the F3b lesson applies to its controls too: a panel
knob can display a value that never reaches the cluster field it claims to set. Prove each
control at the pins, once:
1. Flip the HMI source switch back to **UI** (the `PYTHON (effective)` LED goes off). Sanity:
   a Python `set` now NACKs `source is UI` — expected, note it.
2. On the **`APC_PC_UI_Main`** panel set, one at a time: **`Spark advance [CADBTDC]`**,
   **`DI advance [CADBTDC]`**, **`DI duration [ms]`** — use *different* values than the 4e
   sweep (e.g. SA 25, SOI 50, duration 2.0) so a stale echo can't masquerade as a pass.
3. For each: the scope edge / pulse width moves by the predicted ms (same arithmetic as 4e)
   and the TS10ms `SA [CADBTDC]` indicator follows. A control whose edge does **not** move is
   a UI-wiring defect — record which one and chase it in `UI_Main`'s cluster assembly.
4. Also confirm the enables from the panel once (`IGN enable` / `DI enable` / the cylinder
   checkboxes) drive the same twelve lights as 4d did from Python.
5. Return the source switch to whichever mode the next step needs.

*Accept:* outputs appear **only** with `SYSTEMSTATE ≥ 2` and `CylPressError` FALSE;
`NumberOfActiveIGN_DI` = 12 (and = 2 in the single-cylinder test); SA/SOI/duration move the
scheduled edges by the predicted ms at both rpm **from both writers — Python (4e) and the
UI_Main panel (4f)**. Override-forced outputs prove wiring only — the gate test is step-5c.

---

## Step 5 — Drills (the operational proof, and F-hazard resolution)

**Prerequisite:** the full Step-4 running config (all three tiers, state raised over the real
command path, outputs on the scope, `baseline_motored` playing, **motoring XML loaded — not
the drill XML**). For every drill record in the commissioning book: timestamp, what was
observed (with latencies where asked), and the **recovery path** back to a running system.
Run 5a/5b (destructive to the session) **last** if you want to chain the others in one sitting.

- **5c — State-gate walk** *(do this one first — it certifies the Step-4 observables).*
  With `Override PC settings = FALSE`:
  1. From Python, step the mode **up**: `mode standby` (0) → `mode motoring` (1) →
     `mode idling` (2) → `mode firing` (3). Dwell ≥ 10 s per state.
  2. At each state record: `NumberOfActiveIGN_DI` (expected **0, 0, 12, 12**), the
     `SparkEnable`/`InjectionEnable` LED arrays, the DSM `9049_Global_SYSTEMSTATE` echo
     (must track within a cycle or two), and whether edges are present on the scope.
  3. Walk **down** too: `mode firing` → `mode motoring` must kill the outputs — the gate is
     level-sensitive, not latched; a count that stays 12 below state 2 is a FAIL.
  *Accept:* outputs exist in exactly {2, 3}, both directions.

- **5d — `CylPressError` veto + clear.** The Step-6 matrix already proved trip+latch+clear on
  the lamps; the **new content here is the veto leg** — the outputs actually dying. Use the 6a
  sim branch (not a function generator — it can't clear all six channels anyway):
  1. State ≥ 2, outputs on the scope, `baseline_motored` playing, **drill XML** loaded for
     this drill only (6b custody rules: swap in, and restore the motoring XML immediately
     after).
  2. Point `Sim folder` at the **`overpressure`** set → within ~2 cycles the max-pressure
     ERROR latches ×6 → `9049_Global_CylPressError` TRUE → **`NumberOfActiveIGN_DI` 12 → 0,
     scope goes quiet**. Record the trip→veto latency in cycles.
  3. Point back at `baseline_motored`, let a few clean cycles pass, PC **CLEAR WARNINGS** →
     error releases → count returns to 12, edges return. Record clear→restore latency.
  4. Restore the motoring XML (Reload INI 9049 or app restart per 6b) and re-verify all-green.
  *Accept:* veto and restore both observed at the pins, not just the lamps.

- **5e — Echo live-capture (F4).** Decides the bitmask-vs-boolean question in
  `9049_ControlSettings` and fixes the Python model. **Not in Override mode** — the raster
  taps the pre-Override wires (F4), so an Override capture lies.
  1. All six cylinders enabled (4d): in DSM read the `9049_ControlSettings` SGL array —
     is **[1] InjectionEnable** / **[5] SparkEnable** = **63** (Boolean-array-to-number
     bitmask) or **1** (plain boolean)?
  2. Discriminator capture: `set activate_cylinder [false,true,false,false,false,false]` →
     [1]/[5] read **2** if bitmask, **1** if boolean. (The all-six capture alone can't
     distinguish 1-vs-1 for a single low cylinder — this one can.)
  3. Confirm **[0] = the `PFI0 mode` panel value (0), not system state**, [3]/[4] =
     duration/SOI as commanded, [7] = Speed (RPM).
  4. Reconcile → **fix `supervisory/monarch/settings_9049.py`** (`from_array`/`to_array` and
     the module docstring) + its tests; note the answer in `docs/9049-openloop-audit.md` §9.
  *Accept:* both captures decoded; `settings_9049.py` matches reality; `pytest` green.

- **5b — Sync-loss.** With outputs on the scope:
  1. Set `EPTControl.SimEnable = FALSE` mid-run → `EPTData.SyncStopped` TRUE
     (`MissedCrankFlag`/`MissedCamFlag` may set), `CrankCount`/`CurrentPosition` → 0,
     CAS `Graph time` stalls into its ~1 Hz DAQ-timeout retry, IGNDI count → 0 (the
     supervisor factors `CrankStalled`/`SyncStopped`), **edges cease**.
  2. Restore `SimEnable = TRUE` → click `Manual Clear Sync Errors`
     (+ `MissedCrankFlagClr`/`MissedCamFlagClr`) → re-check the Step-1 accept; `ForceReSync`
     on CAS if the read doesn't resume.
  3. **Check the diagnostics' wake**: the first cycles after resync can be garbage
     (zero-pad, F3) — record whether any error latched during the outage and CLEAR it.
  *Accept:* outputs gate off on sync loss and the documented click sequence recovers sync;
  post-recovery latches identified and cleared.

- **5a — Watchdog.** The hardware safe-hold anchor (>4 Hz `WatchdogIn` or the FPGA kills
  engine-sync outputs). Baseline first: `WatchdogIn` toggling on TS10ms, `FPGA Heartbeat`
  blinking, count = 12, edges on the scope.
  1. **Kill the RT side**: abort `RT_main` (this kills all three RT loops at once).
  2. Expected within ≲ 250 ms: EPT shuts down position tracking → spark/DI edges cease.
     Distinguish the layers: the **FPGA `Heartbeat` LED keeps blinking** (FPGA alive, RT
     dead) — that's the correct safe-hold picture, not a fault.
  3. Restart `RT_main`. **Panel controls revert to saved defaults** — expect to redo Step 1
     (`SimEnable` TRUE, `SimPeriod`) before sync returns.
  4. **Document the audit-§9 question**: after restart, do sync and outputs return on their
     own once the panels are re-set, or is a manual re-arm needed (`Manual Clear Sync
     Errors`? re-toggle enables? CLEAR WARNINGS for first-cycle garbage?) — write down the
     exact minimal recovery sequence; it becomes the operations-manual procedure.
  *Accept:* outputs dead ≲ 250 ms after RT stop with the FPGA still alive; recovery sequence
  documented step-by-step.

- **5f — E-stop.** End-to-end with the physical button, not simulated: 9049 in the loop,
  state ≥ 2, outputs live on the scope.
  1. Trip the e-stop → record what dies and in what order (edges, state echo, which tier
     reacted), and what latches.
  2. Recovery: **CLEAR EMERGENCY STOP is operator-only at the HMI** — the gateway NACKs it
     from Python (`operator only`, ICD §7.4). Verifying that NACK once
     (`tools/send_command.py`) is a worthwhile bonus check.
  3. Walk the state back up (5c) to prove the recovery path.
  *Accept:* e-stop kills outputs end-to-end; recovery path documented; Python cannot clear it.

- **5g — Recording (F6).** On CAS_loop set **`Enque? = TRUE`**; start a REC via the UI's data
  save (DataSaveControl) while a sim set plays → confirm **TDMS** files land on the cRIO
  (naming `APC_CRIO9049_DATE_HOUR_TESTCODE_ID_*` per `FilesPathFormation`), pull them per
  `docs/crio-file-access.md`, and open one (npTDMS or the Excel importer): full 7200-sample
  traces matching the sim set being played. **Record the intended compiled default of
  `Enque?`** for the deployment sheet (F6) — it silently decides whether a deployed system
  logs at all.

- **5h — Loss-of-PC clamp, UI-mode leg** *(optional but cheap here — closes the
  "confirm once on hardware" caveat in `docs/command-path-asbuilt.md` §5).* In **UI mode**,
  with state ≥ 2: kill the UI apps (PC_HB stops toggling) → within ~5 s (250 counts)
  `PCnotResponding` → the 9056 clamp Selects −1 → SAFE; the 9049 echo follows and outputs
  die. Restart the UI, clear, recover. The PYTHON-mode leg is already covered (drills
  B4-1/2). **Update the caveat note in `docs/command-path-asbuilt.md` when done.**

*Accept:* all drills pass; F4 echo reconciled and `settings_9049.py` updated; watchdog,
sync-loss, and e-stop recovery sequences documented click-by-click (they become the
operations manual); 5h closes the command-path §5 caveat if run.

---

## Step 6 — False-trip / latch matrix (feeding synthetic pressure under SimEnable)

**Why a pressure source at all:** with a floating 9222 the pressure is flat, the MFB
normalization divides by ~0, and **CA50 comes out non-finite — it beats ANY finite
threshold, even the 1e6 disarm (F3a, confirmed live 2026-07-14).** And the flags are
per-cylinder OR'd into `CylPressError`, so **all six `Pcyl` channels** need finite signal —
a function generator on 1–2 channels can never clear the veto. Chosen method: the
**Seam-A sim-read branch** below (replays `gen_cas_traces` sets — the only method that can
drive every fault). `UsePcylDatabase` remains the one-boolean fallback for a quick
"veto clears" check only (F5 hazard: VERIFY returned to FALSE afterwards).

### 6a — Build the CAS_loop sim-pressure branch (one-time, ~30 min)

1. Generate the drill suite on the PC: `python tools/gen_warning_matrix.py`
   → `trace-sets/warning_matrix/<7 sets>/` + `CylWarningLevels.drill.xml` +
   `manifest.md` (the expected-trip table) — and optionally
   `--xlsx "docs/cRIO9049 Warning Matrix.xlsx"` for the bench record sheet.
2. Copy the sets to the cRIO: WinSCP (per `docs/crio-file-access.md`) →
   `/home/lvuser/sim/<set>/` — **copy ONLY the raw `cycle_NNNN.csv` (9×7200);
   NEVER the `*_phased.csv`** (6×7200, desktop-harness-only). A `cycle_*.csv`
   List-Folder pattern matches both and alphabetical sort interleaves them
   raw/phased/raw/phased — feeding 6-row pre-phased frames through
   PPhaseCorrection poisons every metric (IMEP ±45 bar, MAPO ~74, all-red
   lamps; seen live 2026-07-14). Purge strays with
   `rm /home/lvuser/sim/*/*_phased.csv`.
3. Open **`APC_9049_CAS_loop.vi`** → **Ctrl+E**. Locate **`DAQmx Read.vi`**
   (bottom-center, "Analog 2D DBL NChan NSamp", wired to the `7200` constant).
4. Drop a **Case Structure** (*Programming → Structures*) beside it. Create a front-panel
   boolean **`SIM pressure?`** (*Controls → Boolean*) wired to the selector — **saved
   default FALSE** (Data Operations → Make Current Value Default).
5. **False case (real):** move `DAQmx Read.vi` + its constants inside; task/error through
   the border; data output → an output tunnel.
6. **True case (sim):**
   - *File I/O → **Read Delimited Spreadsheet.vi*** — **format `%.5f`**, **delimiter ","**
     (string constant; it defaults to tab!).
   - List Folder pattern: use **`cycle_????.csv`** (`?` = exactly one character),
     NOT `cycle_*.csv` — the `*` form also matches `cycle_NNNN_phased.csv` and
     interleaves the two file kinds (the 2026-07-14 all-red false-trip storm).
   - Path — a rotating index over the folder's own listing (four nodes, all
     *Programming* palette; the set loops forever):
     1. Front panel: *Modern → String & Path → **File Path Control***, label
        **`Sim folder`**; wire its terminal into the case (tunnel).
     2. ***List Folder*** (*File I/O → Advanced File Functions*): path ←
        `Sim folder`, pattern ← constant **`cycle_????.csv`** (never `cycle_*.csv`
        — it also matches the `_phased.csv` files, see the warning above). Its `file names`
        output is sorted alphabetically = numerical order (zero-padded names).
     3. ***Array Size*** on `file names` → N; ***Quotient & Remainder***
        (*Numeric*): **x** ← the blue **`[i]`** iteration terminal of the
        **INNER While loop — "CAS ACQUISITION and CONTROL LOOP"**, the same loop
        holding your Case Structure (its `[i]` sits pinned in that loop's
        lower-left interior and ticks once per acquired cycle; the OUTER
        task-restart loop's `[i]` only ticks per acquisition session — wrong
        counter. Check: this wire must cross no loop border — if a tunnel
        square appears, you grabbed the outer `i`). **y** ← N; use the
        **remainder** (= `i mod N`, counts 0…N−1 forever; resets to 0 if the
        inner loop restarts — the set just replays from cycle_0001, harmless).
     4. ***Index Array***: `file names` + remainder → this iteration's filename
        → ***Build Path*** (base ← `Sim folder`, name ← filename) → the
        **file path** input of Read Delimited Spreadsheet.
     Indexing the real listing beats `Format Into String %04d` (no name-format
     assumption, no +1 off-by-one). Behavior: retargeting `Sim folder` mid-run
     takes effect next iteration (List Folder re-runs each cycle — negligible
     cost); a wrong/empty folder shows as **error 7 (file not found)** on the
     CAS error indicator every iteration and self-heals once the path is fixed.
   - Output is [9×7200] = [NChan×NSamp] — same orientation, **no transpose** (verify once
     on the AI Graph; add *Transpose 2D Array* only if the shape is wrong).
   - ***Wait (ms)*** = one cycle period, because in sim mode nothing else paces the
     loop (in real mode the encoder-clocked `DAQmx Read` *blocks* one cycle per
     iteration; the file read returns in ms — without a Wait the loop spins at
     SD-card speed). **Wait = 120 000 / rpm** (4-stroke, 2 revs/cycle):
     300→400 ms · 600→200 ms · **900→133 ms** · 1333 (SimPeriod 500)→90 ms · 1800→67 ms.
     Build: front-panel numeric **`Sim rpm`** (default 900, data-entry min 60) →
     constant `120000` → *Divide* → *Wait (ms)*; operator sets `Sim rpm` to match
     `SimPeriod` whenever it changes.
     **Do NOT wire `rpm from DAQ` into the Wait** — it is stopwatch-derived from
     the loop's own iteration cadence, which in sim mode IS the Wait: circular
     (first iteration reads ~0 elapsed → huge rpm → ~0 Wait → spin). It stays
     valuable as a cross-check *indicator*: once the Wait is right it should
     display ≈ `Sim rpm`. (Mis-pacing never corrupts the diagnostics — they're
     per-cycle math — it only makes the replay's real-time rate unrealistic.)
     *True auto-pacing, only if sweeping speeds often:* publish TS10ms's
     `ticks2speed` output (EPT speed — valid under SimEnable, non-circular) via a
     9049-local single-process SV and use `120000 / max(rpm, 60)`.
     **AS-BUILT (2026-07-14, verified from the reprint):** auto-pacing via the
     `9049_EngineSpeed_RPM` SV → **In Range and Coerce (60..3000)** →
     `120000/x` → U32 → Wait — guard in place ✓ (Wait bounded 40 ms..2 s);
     delimiter = `","` ✓; DAQmx Read intact in the False case ✓.
     Expected quirk: `rpm from DAQ` reads **~15–20% below** the set sim rpm
     (e.g. 1071 vs ~1333) because `Wait (ms)` ADDS to the file-read/processing
     time instead of absorbing it — loop period = Wait + overhead. Harmless
     (diagnostics are per-cycle); for exact pacing swap *Wait (ms)* for
     ***Wait Until Next ms Multiple*** (same input) so iterations land on the
     period grid. Still to confirm before any build: `SIM pressure?` **saved
     default** = FALSE (the print shows it TRUE at capture — current state and
     compiled default are indistinguishable in an export; F5/F6).
   - Error in → error out straight through.
   - Data output → the **same** output tunnel ("Use Default If Unwired" OFF).
   - **Sever the DAQ error in sim mode (found 2026-07-14):** do NOT chain the
     incoming (DAQmx) error into Read Delimited — feed it a fresh no-error
     constant — and AND the loop's stop condition with **NOT `SIM pressure?`**.
     Otherwise a failed `DAQmx Start Task` (the −200088 startup race, known
     from the 9056 — deployed-bringup #5) makes the inner loop exit every
     iteration: `[i]` resets, **only `cycle_0001.csv` plays, at ~1 Hz**.
     Fingerprint: `rpm from DAQ` ≈ 120, IMEP σ = exactly 0, flat trend lines,
     CAS DAQmx error −200088. Same race now observed on the 9049 after an app
     restart → **port the 9056 retry-loop fix to 9049 `SensorCalibration`**
     (real-mode consequence: no acquisition until app restart — not benign).
7. Wire the tunnel to wherever `DAQmx Read.vi`'s data originally went. **Ctrl+S.**
   Note: injected values are **post-scale engineering units (bar)** — the DAQ custom
   scales (F2) are bypassed, which is exactly what the diagnostics expect.

### 6b — Run the matrix drill

1. **Swap the XML:** copy `trace-sets/warning_matrix/CylWarningLevels.drill.xml` →
   cRIO `/home/lvuser/natinst/bin/CylWarningLevels.xml` (ALL 7 fields armed at
   drill values); press **Reload INI (9049)** on the UI CYLINDER (Errors) screen
   (`ReloadINI9049 → 9049_LoadWarningsFromINI` — no app restart needed, confirmed
   from the 2026-07-14 `UI_Errors` export); then **Retrieve** and spot-check one
   value (e.g. CA50maxError = drill value, not 1e6).
2. Per set, **in manifest order** (`baseline_motored` first). **Amended
   baseline_motored pass criterion (2026-07-14 live finding):** the six flags
   OTHER than late-combustion clean and steady, CA50 *baseline* finite.
   Late-combustion latches randomly on motored streaming — the CA50 detector is
   noise-driven with no combustion, clamps at its search-window end (+45 spikes
   on the trend) and intermittently returns non-finite, beating even the 1e6
   disarm (F3/F3a as-built; **fix = Step 6c below** — sanitize CA outputs
   non-finite→−99 in `APC_HRL`). Consequence for Steps 3–4 (spark/DI gating):
   stream a **fired** set — fired CA50 is stable (~12.9) so `CylPressError`
   stays FALSE. Then:
   `Sim folder` → `/home/lvuser/sim/<set>` · `SIM pressure?` = TRUE · `SimEnable` = TRUE
   → run ≥ 25 cycles → **CLEAR WARNINGS once after the first cycles settle** (first
   acquired cycle is zero-padded garbage — F3) → compare `PcylDiagWarningsAndErrors` +
   `9049_Global_CylPressError` (DSM on `10.1.10.171`) against the **manifest table** →
   on ERROR sets confirm the latch holds, IGNDI `NumberOfActiveIGN_DI` drops, and PC
   **CLEAR WARNINGS** releases it.
3. Record each set in `docs/cRIO9049 Warning Matrix.xlsx` (expected vs observed vs
   latch-cleared).
4. **Restore:** put the motoring `CylWarningLevels.xml` back (drill profile is uncapped
   and drill-sized — never run the engine on it), `SIM pressure?` = FALSE.

Deliverable: the completed matrix sheet = the false-trip matrix for the commissioning book.

**✅ MATRIX COMPLETE (2026-07-14, `screenshots/SIL-1_results/`, record sheet
filled):** all 7 sets run against the all-armed drill XML.

| set | result |
|---|---|
| baseline_motored | PASS — all 42 green, U64s = 0 |
| baseline_fired | PASS — all green (IMEPref green: the check is one-sided low-side, F3d — high IMEP can never trip it; NOT gate evidence) |
| overpressure | PASS — max-pressure ERROR ×6 (281.5 > 231.3), latched, cleared |
| late_combustion | PASS — late ERROR ×6 (CA50≈39 > 22.9) **at state ≥ 2: the 6c re-arm proof** |
| knock | PASS — knock ERROR on cyls 2 & 5 ONLY (the injected ones) |
| misfire | PASS — self-reg + cyl-to-cyl + cyclic-var on **cyl 3 only** (the deviations are ONE-SIDED low-side checks, F3d — only the low cylinder can trip) |
| variability | PASS primary — cyclic-var ERROR ×6 **at display row 5 ⇒ F3c RESOLVED (labels correct)**; collateral cyl-to-cyl on 2/4/6 = stitch × q-step mixing on the largest offsets (real measured dev, not a defect) |

Two manifest-model corrections (not system defects): all three misfire
deviations are **one-sided low-side** checks (`IMEP ≤ ref − thr`, F3d — found
by the user from the print; the tool's expectations now model this); the
variability set's per-cycle q steps produce genuine low-side cyl-to-cyl
deviation through the two-cycle stitch on high-offset cylinders (2/4/6).

### 6c — Permanent fix: state-gate the late-combustion check (chosen approach) — click-level

**Why:** on no-combustion data the CA50 detector is noise — it clamps at its
search-window end (~+45) and intermittently returns **non-finite**, which
beats ANY threshold (`1e6` included — F3a, live 2026-07-14). Late combustion
is only *meaningful* when combustion is commanded, i.e. **SYSTEMSTATE ≥ 2**
(IDLING/FIRING). So gate the check on state instead of fighting it with
thresholds. This is the F3 root fix ("the chain has no state awareness"),
kills the finite noise trips too, and lets `CA50max` stay armed at the fired
value permanently (no per-mode profile swap for this field).

**Safety self-consistency:** the gate uses the same `9049_Global_SYSTEMSTATE`
that already gates spark/DI in TS10ms. Stale-low or NaN state → check off,
but actuation is off by the same signal (can't be firing while the 9049 sees
≤1). Stale-high → extra false trips — the safe direction.

**Where:** `APC_9049_CombCluster2Array.vi` (on the 9049 target) — NOT
`Pcyl_Diag`/`APC_HRL`. Gating here needs **no connector-pane change** to the
SIL-0-validated VIs (the desktop harness keeps working unmodified), the
`9049_Global_SYSTEMSTATE` global is target-local and already read by its
neighbors, and it sits **before the error latch** — which is essential:
gating after the latch would not stop the latch from setting.

1. Open `APC_9049_CombCluster2Array.vi` → **Ctrl+E**. Identify the two
   `PcylDiag` unbundles: the **Warnings** cluster (simple OR → the
   `WarningsAndErrors` indicator) and the **Errors** cluster (each category →
   a feedback-node **latch** → OR → `9049_Global_CylPressError`).
2. Drop a **`9049_Global_SYSTEMSTATE`** global read (copy-paste the node from
   `APC_9049_CAS_loop.vi` if quicker). Drop ***Greater Or Equal?***
   (*Comparison*) with a constant **2** → one boolean, label it
   `combustion expected`.
3. **Errors path (the one that vetoes fire):** find the **`late combustion`**
   6-element boolean array wire between the Errors unbundle and its feedback
   latch. Delete that segment; drop an ***And*** node; wire the array to one
   input and `combustion expected` to the other (And is polymorphic —
   array·scalar gives element-wise); And output → the latch input. The gate
   MUST be upstream of the feedback node.
4. **Warnings path:** same one-And treatment on the `late combustion` warning
   array before its OR (keeps the yellow lamps quiet while motoring too).
5. *(Optional, same pattern, 2 more And nodes each)*: gate **`knock`** and
   **`misfire from IMEP`** the same way — both are equally meaningless below
   IDLING (no combustion to knock; Expected-IMEP undriven). This shrinks the
   motoring-vs-fired XML delta to just the numeric levels.
6. **Ctrl+S**, rebuild/redeploy when convenient.

**AS-BUILT (2026-07-14, verified from the reprint):** gates in place on BOTH
paths for **late combustion AND misfire-from-IMEP** (the F3 trap gated too —
good extension); errors-path Ands confirmed **upstream of the feedback
latches**; `≥2` compare labeled "Is combustion expected?". Knock left ungated
(deliberate; XML disarm covers motoring).
**LIVE-VERIFIED (same day, `baseline_fired` @ STAND_BY, drill XML):** IMEPref
green at IMEPn 25.8 vs armed 15.5, late-combustion green at CA50 12.8 —
gating side proven. **Re-arm half also proven** — the matrix `late_combustion`
run tripped late ERROR ×6 at state ≥ 2 (results table above). Both directions
closed; nothing owed on this edit.
**Procedure addition:** CLEAR WARNINGS once after **any data-source change**
(Sim-folder switch, `SIM pressure?` toggle, acquisition start) — a set switch
sweeps a large IMEP step through the 20-cycle std window and latches
cyclic-variability on a cylinder subset (seen live: motored→fired switch,
27-bar step, cyls 1/3/5/6 latched; flushes in ≤20 cycles).

**Verify — both ✅ DONE (2026-07-14, matrix run):**
- Stream `baseline_motored` (state ≤ 1, any CA50max, even armed) →
  late-combustion stays green indefinitely. THE acceptance for this edit —
  passed (all 42 green).
- Re-run the `late_combustion` fault set **with state raised to ≥ 2** and
  confirm the flag still trips and latches — passed (late ERROR ×6; recorded
  in the results table + record sheet). Procedure kept for regression re-runs:
  request IDLING, or hold state with the 9056 SM's **ManualState = 2** override
  if latched warnings clamp it below 2.

**Drill implication (matrix):** after this edit the `late_combustion` set can
only trip while SYSTEMSTATE ≥ 2 — the manifest/record-sheet row for it now
implies "state held ≥ 2 during the set".

### 6d — Warning thresholds disconnected from the comparisons (F3b) — ROOT CAUSE FIXED

**Resolution (2026-07-14):** probes showed the compares using panel defaults
(MaxPCylMax 100/1000, CA50max ≈15) while the FGV/UI displayed the loaded XML
values — because **`Load INI on startup` was saved FALSE**: the running 9049
had NEVER loaded a warning XML. Fixed: control set **TRUE and saved as
default**. (Scope was all fields; VI non-reentrant. F3a is most likely
re-explained: finite +45 CA50 spikes vs the default 15, not non-finite
values.) **Lesson: the UI threshold display reads the FGV, not the
comparisons — verify protections by probe/behavior only.**

**Residual verifications (each quick):**
1. **Acceptance: ✅ PASSED (2026-07-14, `baseline_motored-1/2.png`).** ALL 42
   lamps green with the **all-armed drill XML** (Pmax 150.8 < 213.5; CA50
   spikes +45 correctly gated at state ≤ 1; σ 0.02–0.04 < 0.2);
   `CylPresWarnings` = `CylPresErrors` = **0**. The always-yellow row is dead;
   F3b fix + 6c state gate + clean cyclic traces all verified simultaneously.
   **`baseline_fired` also ✅ PASSED** (same day, after an app restart cleared
   the −200088 task race): all green at STAND_BY; healthy run (full 20-cycle
   rotation, σ ≈ 0.03). Both matrix control rows are banked. *(Correction
   2026-07-15: the green IMEPref row was earlier cited as gate evidence — it
   is not; the check is one-sided low-side (F3d), so a HIGH IMEP can never
   trip it regardless of state. The CA50 gate proofs stand: motored +45
   spikes green at state ≤ 1; late_combustion red at state ≥ 2.)*
2. **F3a settle:** re-test the CA50 1e6 disarm on motored — quiet ⇒ F3a was
   purely this; still tripping ⇒ the non-finite path is real (state gate
   covers motoring either way).
3. **Mid-run reload:** edit one XML value, press UI RELOAD INI, probe a
   threshold wire. If unchanged, the drill's XML-swap step becomes
   **"swap XML → restart the 9049 app"** (startup-load now guarantees a
   correct load). Same check for SET NEW WARNING LEVELS.
4. **Deployment:** `Load INI on startup = TRUE` must ride into every build —
   F6-class compiled default (added to the §8 pre-fuel checklist).
5. `overpressure` set + drill XML: warning row yellow > 213.5, red > 231.3 —
   proves the loaded values now govern the flags end-to-end.

**F3c — ✅ RESOLVED (2026-07-14, matrix `variability` run):** the single-flag
injection landed red at display **row 5** ⇒ labels correct, no active
mislabeling (name-bound nodes). Residual: the Pcyl_Diag-vs-UI typedef order
alignment stays as rebuild debt (audit F3c).

**Optional hygiene (backlog, not required for SIL):** non-finite CA values
still flow into `9049_CalculatedVariablesRaster` telemetry and into
`KnockCA50Control`'s CA50 input (inert today, but the future CA50 closed loop
must never see Inf/NaN — same family as the NaN-at-Unflatten bench bug, F8).
The earlier per-output coerce (In Range and Coerce ±360 → "In Range?" →
Select original / **−99**, at the Unbundle inside `APC_HRL`'s cylinder loop)
remains the right pattern for that cleanup when the closed loop work starts.

---

## SIL-1 exit criteria / deliverables

- [x] Sync acquired on-target at ≥1 rpm setpoint; `Speed(RPM)` correct (2026-07-14).
- [x] **Trig0-follows-sim = YES — Step 2 closed** (2026-07-14 bench: `rpm from DAQ` = set rpm,
      `Graph time` full 7200-sample cycles, DAQ error 0).
- [x] Motoring profile validated on-target — EXCEEDED: all 42 lamps green under the
      ALL-ARMED drill XML; `CylPressError=FALSE` holds (2026-07-14).
- [ ] State-gated spark/DI scheduling scoped; SA/SOI/duration sweep confirmed from **both
      writers** — Python (4e) and the UI_Main panel (4f).
- [ ] Drills 5a–5g passed and documented; **watchdog recovery** + **sync-loss** behaviours
      recorded (+ optional 5h closes the command-path §5 UI-mode-clamp caveat).
- [ ] **F4 echo reconciled** → `supervisory/monarch/settings_9049.py` corrected.
- [x] False-trip / latch matrix produced — COMPLETE 7/7 (2026-07-14; record sheet filled;
      F3a/b/c/d found + dispositioned). ⚠ motoring XML restore still owed at close-out.
- [ ] Pre-fuel checklist items 7–10 (audit §8) provably satisfiable from this bench.
- [ ] **Session close-out:** `Override = FALSE`, `SimEnable = FALSE`, `UsePcylDatabase = FALSE`,
      **`SIM pressure?` = FALSE**, motoring `CylWarningLevels.xml` restored — verified on the
      deployed build before it can ever see fuel (F1/F5).

## Then → SIL-2 / SIL-3

- **SIL-2** — real A(+B)+Z(+cam) TTL into Mod3 DIO0–3 (Arduino emulator or a µC); covers the
  9401 input path, deglitch, synthetic-cam, quadrature, and speed transients the internal sim
  can't. (1800 rpm = 108 kHz A / 30 Hz Z, phase-locked.)
- **SIL-3** — actuation dry tests: coils on bench plugs, DI into dummy loads; Key interlock;
  decode `Fault1=126` (F9). This is where the team's commissioning plan takes over.
