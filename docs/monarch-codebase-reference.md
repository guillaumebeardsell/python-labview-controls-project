# MONARCH LabVIEW Codebase — VI Reference

> **Location note (2026-07-20):** this file describes
> `original-labview-codebase/MONARCH-CODEBASE/` but lives here in `docs/` on
> purpose. It used to be `MONARCH-CODEBASE/README.md` and was accidentally
> deleted **twice** (commits `efcb09d`, `12126a4`) by the folder-sync that
> mirrors the Windows LabVIEW tree — anything placed inside the mirrored
> folder gets swept. Do not move it back.

A per-VI map of the MONARCH LabVIEW control system, written so a future session (human or
model) can understand what every VI does **without opening LabVIEW or re-reading the PDF
exports**. Compiled 2026-07-07 from: the `MONARCH.lvproj` target tree, string extraction
from every `.vi` binary (subVI calls, shared-variable reads/writes, typedefs), the HTML/PNG
VI exports in the sibling folders under `original-labview-codebase/`, the three PDFs
(`APC Control System- LV MONARCH Overview.pdf` [Ovw], `20251020ERD01GUI01 FPGA on cRIO
9049.pdf` [Deck], `9049 FPGA VIs - Google Docs.pdf` [GDoc]), the three DOCX docs
(SCADA_HMI, Data Logging and Variables, the E1/M1 report [Report]), and this repo's live
findings (`docs/migration-seam.md`, `docs/shadow-findings.md`).

Entries marked *(inference)* are deduced from names/wiring, not stated in any document.

## What this folder is — and what it is not

- A **curated copy** of `C:\LabVIEW PROJECT\MONARCH\` from the Windows control-room PC
  (the original folder had 241 files; see `MONARCH-cleanup-list.xlsx` at the repo root —
  sync-conflict copies and orphans were excluded from this copy).
- **Snapshot taken ~2026-07-06.** The live project has since gained changes NOT in these
  files: the Python gateway VI (`APC_PC_PythonGateway.vi`), the B0 watchdog→StateMachine
  wiring, the WarningIntegration→StateMachine wire, the `PC_HB` UI toggle, and the
  telemetry re-taps. `docs/migration-seam.md` describes the live as-built state.
- `.vi` files are **binary** (LabVIEW 2020 SP1, 32-bit). You cannot read the diagrams here,
  but `strings -n 6 <file>.vi` reliably reveals shared-variable paths, subVI references,
  and typedef usage. Human-readable exports (HTML + PNG/GIF diagrams) for ~30 key VIs live
  in the sibling folders of `original-labview-codebase/` (e.g. `APC_9056_StateMachine/`,
  `APC_9049_FPGA_main_including_hierarchy/`). Fresh full-res exports (2026-07-07 late
  evening) exist for: TS_loop, WatchDog, StateMachine, UI_System, UI_Errors,
  PythonGateway, ControlSettingsRaster, and all seven 9056 controllers — these
  post-date the B0/B3.c rewiring and are the as-wired evidence.
- `FPGA Bitfiles/` holds compiled bitfiles for both FPGA targets, so the FPGA VIs can be
  deployed without recompilation.
- **Almost no VI has a real VI-description.** Where a description exists it is usually the
  generic NI "DAQmx Custom Scales" example boilerplate (many VIs were cloned from that NI
  example) — ignore it. The real knowledge is in diagram comments and the external docs,
  which is why this README exists.

## System map

| Target | lvproj name | IP | Top VI | Role |
|---|---|---|---|---|
| Windows PC | `My Computer` | — | `APC_PC_UI_Main.vi` | HMI/SCADA over shared variables; Modbus-TCP **master** to the MTR membrane PLC. Almost no control logic. |
| cRIO-9049 | `NI-cRIO-9049-020A5DED` | 172.22.10.2 | `APC_9049_RT_main.vi` → `APC_9049_FPGA_main.vi` | Engine-synchronous: encoder→crank angle, spark & DI pulse generation, cylinder-pressure / combustion analysis, CAS data logging. |
| cRIO-9056 | `CRIO9056 NTS` | 172.22.10.3 | `APC_9056_RT_main.vi` → `APC_9056_FPGA_main.vi` | Plant: gas feeds (NG/Ar/O2), thermal HX loops, vents, dyno — **and the supervisory StateMachine + WatchDog**. |
| MTR PLC | external | 172.22.11.1:502 | — | CO2/membrane gas-separation skid; own state machine + heartbeat; Modbus-TCP slave of the PC. |

Command path: operator → PC writes `PC_ControlSettings` (shared variable cluster) →
**9056 StateMachine** limits it to `Limited_ControlSettings` and sets `SYSTEM STATE` →
9056 controllers consume it; the 9049 reads `PC_ControlSettings` directly for spark/DI
settings and publishes its command subset back as `9049_ControlSettings`.

**Loop rates** (as-built, some confirmed live 2026-07):

| Loop | Rate | Notes |
|---|---|---|
| 9049 FPGA main | 40 MHz single-cycle | encoder tracking, spark/DI output |
| 9049 FPGA heartbeat frame | 500 ms | blinks LED, publishes `FPGA Heartbeat`, chassis temp |
| 9049 `TS10ms_loop` | 10 ms (1 kHz timed-loop clock, dt=10) | FPGA interface + spark/DI settings |
| 9049 `CAS_loop` | per engine cycle (7200 samples @ 0.1 CAD; ≈67 ms @ 1800 rpm) | pressure DAQ + combustion analysis |
| 9056 `TS_loop` control loop | **~20 ms / ~50 Hz** (paced by the NI9205 DAQmx block read, 20 samples) | StateMachine + limiter + PIDs + WatchDog. The Report's "100 ms main loop" is the older design. |
| 9056 `TS_loop` housekeeping loops | 1000 ms `Wait Until Next ms Multiple` | TS_loop runs ~5 parallel loops |
| PC UI router loop | 200 ms | `UI_System` visualization + MTR Modbus |
| PC telemetry gateway | 1 Hz | not in this snapshot; see `docs/monarch-telemetry.md` |

**Vocabulary:** CAS = crank-angle-synchronous; TS = time-synchronous; CAD = crank angle
degrees; CAT = crank angle ticks (here MAX_CAT = 28,800/cycle: 3600-line encoder × 2²
extrapolation × 2 for 4-stroke; 1 tick = 0.025°); EPT = Engine Position Tracking (NI
Powertrain Controls library); HRL = heat-release library; DI = direct injection; IGN/SI =
spark; PFI = port fuel injection; MTR = the membrane skid vendor. System states: **−1
SAFE, 0 STAND_BY (default), 1 MOTORING, 2 IDLING, 3 FIRING**. Controller mode levels:
**0 = safe (forces the XML-configured `Safe mode control` value), 1 = manual
passthrough, 2 = closed-loop**; cascade-capable loops (Texh/Toil/Ar) add **3 =
cascaded closed loop**, and NG adds **4/5/6 = closed loop on selected feedback**
(2/4 = lambda, 5 = IMEP, 6 = torque). Vents encode 1 = closed, 0 = open (chosen so
min() = safe).

---

## Windows PC VIs

### APC_PC_UI_Main.vi — operator main screen (top-level PC VI)
Three-monitor HMI, screen A ("monarch APC v0.1"). Engine/combustion focus: APC-mode
slider (**UI-side +1-per-step rate limit**, mirroring the StateMachine's), state
indicators, EMERGENCY STOP & VENT, IGN/DI/PFI on-off, CA50 closed-loop and knock-limiter
enables, spark/DI/PFI timing setpoints, speed low/high selector (900/1800 rpm), live
cylinder-pressure plot with per-cylinder IMEP/IMEPσ/Pmax, cylinder deactivation,
crank-resync + toggle-TDC buttons, REC/test-ID/pre-trigger/cycle-count logging controls,
SFTP file transfer from both cRIOs, test notes [Ovw pp.82–85]. Conditions the requested
state and writes **`PC_ControlSettings`**; e-stop buttons on all three screens feed the
same flag [Ovw p.76]. Calls `UI_System` + `UI_Errors` as subpanels, the two SharedVarPolling
VIs, `VariableMapping`, `ClearErrorButton`, `System Exec`.

### APC_PC_UI_System.vi — P&ID mimic + MTR Modbus master (screen B)
Full plant P&ID mimic: sensor/actuator values (names on hover), control-loop
activate/deactivate, open/closed-loop selection and references, main NG/Ar/O2 + vent
switches, 9049/9056 RT heartbeat indicators, membrane-skid state + 12 membrane warnings.
Contains the **Modbus-TCP master to the MTR PLC** (slave 172.22.11.1:502; registers
40001/41001/45001/46001; MTR states 0 Undefined … 6 Emergency ShutDown) and a "membrane
skid state machine"; 200 ms name-based router loop that never terminates [Ovw pp.78–80,
87–88]. Uses `float2u16`/`u162float` to pack Modbus registers. **Also generates `PC_HB`
(B3.c; pixel-verified in the 2026-07-07 23:42 re-export):** a feedback-node → NOT flips
the bit each main-loop iteration; it rides the PID-refs cluster into
`PC_GlobalVariables_PIDsyst2main`, which `UI_Main` relays into `PC_ControlSettings` —
the heartbeat the 9056 WatchDog clamps on, making the whole UI app the PC-liveness
proxy. Modbus specifics (same export): reads regs 40001 (7 words: MTR state/HB/errors,
"Control from LV") and 41001 (38 words → the MTR floats); writes 45001
(`Send2MTRuint16`) and 46001 (`Send2MTRfloats`, min/max-clamped); on comms loss, wait
(5 s) and retry.

### APC_PC_UI_Errors.vi — warnings/diagnostics screen (screen C)
Tabs: SIGNAL WARNINGS / SET SIGNAL LEVEL / CYLINDER; "cycles for std" = 100
[full export `../APC_PC_UI_Errors/`, 2026-07-07]. The diagram's own severity legend:
**level 1 = soft warning (self-cleared), level 2 = set IDLING, level 3 = set MOTORING,
level 4 = STOP and VENT** (UI colors: green OK, yellow soft, orange idle, red motoring,
black e-stop [SCADA]). **The "rasters" are the 9056's AI cards** (answers the SCADA-doc
reviewer's open question): Raster 1 = NI9205 (±10 V: WF-PT/OA, EO-PT, TORQUE, spare
`NI9205_9–15_V`), Raster 2 = NI9208 (4–20 mA: NG/NGDI/O2/AR flows+pressures, WF-PT-004/
014/016, SW-FT-001–004), Raster 3 = NI9214-1 (thermocouples: WF/O2/AR/NG/NGDI/PC/EC-TT),
Raster 4 = NI9214-2 (EC/SW/EO-TT + spares), Raster 5 = empty/spare. Per raster: LED
column (level→color) + signal name + selected-channel measured value. Threshold editing
per chassis is a command quartet over shared variables: `set…` → `*_SetWarningLimits`
(+ MIN/MAX sign), `retrieve…` → `*_RetrieveWarningLimits`, `SaveINI…` →
`*_SaveWarningLimitsToINI`, `ReloadINI…` → `*_LoadWarningsFromINI`. The 9049 (CYLINDER)
edit cluster exposes the `9049_WarningLevels` fields: samples for running IMEP std,
MaxPCylMax warning/error [bar], MaxDevFromExpectedIMEP warning/error, MaxDevFromAvg
warning/error, MaxIMEPstdError, MAPOmax warning/error [bar/CAD], CA50max warning/error
[CADATDC]. Also: per-cylinder CA50/MAPO/IMEP/IMEPσ/MaxPcyl plots, a listbox writing
`9049_SelectBroadcastVar` (which pressure trace streams to `SyncCylPres [bar]`), the
2D color maps feeding `PC_Global_Errors`, a **single-button** CLEAR WARNINGS (its own
small loop raising "Clear warning request"; the doc reviewer had asked for multi-step),
and an e-stop terminal.

### APC_PC_PythonGateway.vi — the Python telemetry/command gateway (not in this snapshot)
Lives only in the live project (created 2026-07); full export in
`../APC_PC_PythonGateway/` (2026-07-07 23:42). As-built: TCP listener on the
gateway port → single-client session loop → `TCP Close` (listener + connection IDs,
annotated); `TCP Read` in **CRLF mode** (4096) with a "Line Arrived?" case that parses
incoming JSON (`params`/`settings`/`id`/`name`) and recognizes a
**`set_control_settings`** command (the Phase-B3 command path, in progress); a
"Command Reply – Acknowledgment" frame that `TCP Write`s a canned
`{"type":"command_ack","id":…,"accepted":true,"reason":"hello from LabVIEW"}`; and a
1000 ms-paced telemetry frame that formats
`{"type":"telemetry","seq":…,"ts":…,"system_state":…,"warnings_limit":…,"manual_state":…,"force_state":…,"settings":…,"limited_settings":…}`
from `SystemState_SM`, `WarningLimits_SM`, `ManualState_SM`, `ForceState_SM`, and
`Flatten To JSON` of `PC_ControlSettings` + `Limited_ControlSettings`, then `TCP Write`s
one line. Counters: lines received, telemetry sent. Python-side contract:
`docs/monarch-telemetry.md`, `docs/icd.md`.

### APC_PC_VariableMapping.vi / APC_PID_VariableMapping.vi — name-based signal routers
Given the flat DBL arrays published by each cRIO (`9049_MeasAndCalc`, `9056_MeasAndCalc`)
plus each side's name registry, searches names and builds index arrays, then fills a
typed cluster for display — `APC_VisualizationCluster_v2.ctl` (max 256 entries) for
`VariableMapping`, `APC_PIDCluster.ctl` for `PID_VariableMapping`. **If a name exists on
both cRIOs, the 9056 value wins** [Ovw p.94].

### Other PC-side VIs
| VI | What it does |
|---|---|
| `APC_ClearErrorButton.vi` | Writes `APC_MASTER_ClearWarnings` (operator clear of latched warnings). |
| `APC_WarningColorMap.vi` / `APC_Warning2DColorMap.vi` | Map warning level codes → UI colors (1D/2D). |
| `APC_RunHRL_inPC.vi` | Offline harness: replays recorded (SCE) pressure data through `APC_HRL` on the PC [Ovw p.39]. Dev tool, not part of the running system. |
| `APC_HRLtest.vi` | HRL test harness writing results to a spreadsheet. **No callers.** |
| `APC_PC_SlaveModbus.vi` | Modbus-TCP *slave* on the PC (adapted from the NI example). **No callers** — leftover experiment. |
| `hello-vi.vi` | The Python-link connectivity-test VI (TCP/JSON, reads `PC_ControlSettings` + `9049_Global_SYSTEMSTATE`). Ancestor of the production gateway below. See `docs/hello-vi.md`. |
| `support/Message Queue/*` | Standard NI QMH message-queue library (create/enqueue/dequeue + `Message Cluster.ctl`). Template plumbing, no MONARCH logic. |
| `APC_PCglobalVars.lvlib` | PC-local globals: `PC_Global_Errors` (color-box error cluster), listbox selections, `PC_GlobalVariables_DBLmain2syst` / `_PIDsyst2main` (Main↔System panel exchange, incl. the PID refs relay). |

---

## cRIO-9049 — RT layer

### APC_9049_RT_main.vi — 9049 top level
Loads sensor calibration / builds the DAQ task (`SensorCalibration`), then runs parallel
loops: `CAS_loop`, `SAVE_loop`, `TS10ms_loop`. A Diagram-Disable structure holds
`MODBUSTCP_HealingLoop` ("MODBUS") and `TS100ms_loop` ("System PID") — **both currently
Disabled** [Deck p.6; RT_main diagram PNG].

### APC_9049_TS10ms_loop.vi — FPGA interface + spark/DI settings (10 ms)
Diagram banner: *"LOOP DEDICATED TO THE FPGA ACTIONS (SYNCHRONIZATION, SETTINGS FOR
COMBUSTION AND IGNITION AND ENCODER GENERATION FOR CAS ACQUISITION) and SYSTEM STATE
MACHINE"* (the state machine lived here in 2023; it now runs on the 9056 — see history
below). Opens the FPGA reference and each 10 ms tick:
- **A** — per-cylinder DI/spark commands via `PlsGen_Time_Convert_revf5` +
  `SparkSettings`. One For-loop applies identical settings to all 6 cylinders except
  **TDC offsets = 0, 480, 240, 600, 120, 360** (author: "will be changed for cyl-to-cyl
  control") [Deck p.10].
- **B** — DI config cluster: `Window_Start/End (DBTDC)` are **diagram constants** (90/−30
  here; GDoc shows 200/0); `MainEnable/MainDuration/MainSOI` come from the UI
  (`DI enable`, `DI duration [ms]`, `DI advance [CADBTDC]`) [Deck p.11].
- **C** — the **hard spark/DI enable gate**: `Injection_Enable = ¬CylPressError ∧
  ActivateCylinder ∧ DI_Enable ∧ (9049_Global_SYSTEMSTATE ≥ 2)`; same form for
  `Spark_Enable` with `IGN Enable` [Deck p.12].
- **D** — writes EPTControl, DI_Control, DI_IPhaseInterface, module DIO, ½-Z-pulse,
  toggle-TDC, TRIG1 offset to the FPGA; **toggles the FPGA `WatchdogIn`** every iteration
  (requirement: >4 Hz [GDoc p.2]); drives `MissedCrank/CamFlagClr` from "Clear Sync
  Errors". Reports Finished Late?.
Runs `KnockCA50Control`, `ControlSettingsRaster`; shared vars: reads `PC_ControlSettings`,
writes `9049_HeartBeat`, `CASyncLost`, `CRIOtime`, `CRIOchassisT`, touches
`9049_Global_SYSTEMSTATE`. Front-panel `Override PC settings` control exists.

### APC_9049_CAS_loop.vi — crank-angle-synchronous acquisition + analysis
Reads the encoder-clocked DAQmx AI task: **7200 samples = one engine cycle at 0.1 CAD**
(timeout 1 s). Runs `checkAI` (verify full cycle), `PressureAnalytics` (combustion
metrics), `rpm`; polls `9056` data and `9049_ControlSettings`; enqueues Analog + Cycle
data for `SAVE_loop`; broadcasts via `SharedVarBroadcast`. Handles `CASyncLost` +
`ForceReSync`; **writes `9049_Global_SYSTEMSTATE`** (the 9049's state *echo* — see
gotchas) [Deck pp.23–26].

### APC_9049_SAVE_loop.vi — data logging
Dequeues the CAS/CycAvg queues and writes the test files (see "Data logging" below).
Uses `FilesPathFormation` + `SaveTestAverageValues`; shared vars `DataSaveControl`,
`PostMortemSave`, `SavingInformation`.

### APC_9049_TS100ms_loop.vi — legacy "System PID" loop (DISABLED)
Contains `PID Advanced` instances; the system-PID/state loop from when the 9049 owned
supervisory control (pre-migration design; the Report describes system PIDs + state
machine here). Disabled in `RT_main` *(inference from diagram label + Report)*.

### APC_9049_MODBUSTCP_HealingLoop.vi — Modbus master keep-alive (DISABLED)
Creates/closes a Modbus master instance in a self-healing reconnect loop. Disabled in
`RT_main`; the working MTR Modbus master is on the PC (`UI_System`).

### 9049 combustion-analysis chain (support VIs)
Called per cycle from `CAS_loop` → `PressureAnalytics`:

| VI | What it does |
|---|---|
| `APC_9049_PressureAnalytics.vi` | Umbrella: `checkAI` → `PPhaseCorrection` → `APC_HRL` → `CombCluster2Array`. In: `AIdata [bar]`, filter coefs, `Expected IMEP`. Out: `SyncCylPres [bar]`, `9049_CalculatedVariablesRaster`. |
| `APC_9049_PPhaseCorrection.vi` | Phase-corrects the 6 cylinder-pressure channels using a circular buffer of the last 2 cycles; firing-order init offsets 0,4800,2400,6000,1200,3600 (samples); outputs mean system/exhaust pressure, prechamber peak diff; TDC-fail detection [Deck p.31]. |
| `support/APC_HRL.vi` | Heat-release umbrella: volume → pegging → zero-phase filters → apparent HRL → IMEP → MAPO → `CombustionAnalysisCluster` (IMEPn/g, PMEP, Pmax, MAPO, RI, CA03/10/50/90/97, CA10CA90, maxdp/dCAD, maxQ, kappas) + `Pcyl_Diag` [Ovw p.40]. TODOs: BMEP/BSFC/BSFE/OFR. |
| `APC_9049_HRL_volume.vi` | Cylinder volume V(θ), dV/dθ, surface area at 0.1 CAD from geometry cluster. Author flags: "FIX STROKE CALC", "Verify formula", "not accurate with crankpin offset", "IVC/EVO/EVC to be updated" [Ovw p.45]. |
| `APC_9049_HRL_pegging.vi` | Pegs LP-filtered Pcyl to LP-filtered exhaust pressure over a window (default index 6900, length 200). |
| `APC_9049_HRL_ZeroPhaseFIlter.vi` / `…BP.vi` | Zero-phase (forward-backward) IIR filtering; BP variant band-pass (used by MAPO). |
| `APC_9049_HRL_CreateFilter.vi` | Builds the Butterworth IIR coefficient clusters. |
| `APC_9049_HRL_apparentHRL.vi` | Single-zone apparent heat release: fits polytropic κ, dQ/dθ = κ/(κ−1)·P·dV + 1/(κ−1)·V·dP; calls `MFB` + `CA` (+ `cumsum_dQ`, `APC_CAD_derivative`). |
| `APC_9049_HRL_IMEP.vi` | Pmax, IMEPn (720°), IMEPg (compression+power, CAD 180–540), PMEP. |
| `APC_9049_HRL_MAPO.vi` | Knock metric: max amplitude of band-pass-filtered pressure oscillation. |
| `APC_9049_HRL_preChamber.vi` | Cylinder-6 prechamber pressure handling (peak differential). |
| `APC_9049_MFB.vi` | Rescales cumulative Q to 0–1 → mass fraction burned. |
| `APC_9049_CA.vi` | Finds CA03/10/50/90/97 crossings of the MFB curve (author query: "is first sample −360 or −359.9?"). |
| `cumsum_dQ.vi` | Cumulative sum of heat-release increments *(inference)*. |
| `support/APC_CAD_derivative.vi` | Derivative w.r.t. crank angle *(inference)*. |
| `support/APC_Pcyl_Diag.vi` | Cylinder-pressure diagnostics vs thresholds from `LoadWarningConfig` (running IMEP std via PtByPt std-dev); feeds warning flags. |
| `support/APC_9049_CombCluster2Array.vi` | Flattens the combustion cluster → `9049_CalculatedVariablesRaster`; evaluates warning flags (max pressure, misfire self-reg / cyl-to-cyl / IMEP, cyclic variability, knock, late combustion) and **sets `9049_Global_CylPressError`** (the spark/DI gate input); consumes `APC_SLAVE_ClearWarnings`; calls `keyCA50`/`keyKnock` [Deck p.33]. |
| `APC_9049_keyCA50.vi` / `APC_9049_keyKnock.vi` | Pull the CA50 / knock values out of the metrics set (feed `9049_Global_CA50` / `_SensedKnock`) *(inference)*. |

### 9049 command/telemetry plumbing (support VIs)
| VI | What it does |
|---|---|
| `APC_9049_ControlSettingsRaster.vi` | Packs the 9049 command subset into the SGL array written to **`9049_ControlSettings`**. Confirmed order (2026-07-07 reprint): [0] 9049 STATE (u8), [1] InjectionEnable, [2] MainEnable, [3] MainDuration (ms), [4] MainSOI (DBTDC), [5] SparkEnable, [6] SparkTiming (DBTDC), [7] Speed (RPM); booleans as 1/0. Modeled in `supervisory/monarch/settings_9049.py` (`from_array`/`to_array`). |
| `APC_9049_ControlSettingsPolling.vi` | A bare read of the `9049_ControlSettings` shared variable, returned as the raw DBL array — no unpacking; consumers index it (layout above). Author comment: "Gathering of system wide information on the applied controls… this could be in the 10 ms timed loop." |
| `APC_9049_SharedVarBroadcast.vi` | Publishes `9049_MeasAndCalc` (flat DBL array of measurements + combustion metrics) and `SyncCylPres [bar]` (selected pressure trace; channel chosen by `9049_SelectBroadcastVar`). |
| `APC_9049_9056SharedVarPolling.vi` | Reads `9056_MeasAndCalc` → 9056 IO array + timestamp + `SystemState` (name registry via `APC_9056_Signals`). Also used on the PC. |
| `APC_9049_SensorCalibration.vi` | Builds the scaled CAS DAQmx task (custom scales = sensor calibrations); calls the per-card config VIs of *both* chassis to assemble the global name registry. |
| `APC_9049_NI9222conf.vi` | Channel config (names/offsets/gains/units) for the NI 9222 AI cards (cylinder pressures etc.). The "enter once" per-card config pattern [Report]. |
| `APC_9049_CycleAvgSignals.vi` | Name registry for the 9049 cycle-averaged variable array (confirmed from the 2026-07-14 print: Build Array of TimeStamp + ControlSettingsRaster + CycleRaster name lists → `CRIo9049_CycleAvgSignals`). |
| `APC_9049_LoadWarningConfig.vi` | Loads/saves cylinder-diagnostic warning thresholds from/to XML; publishes `9049_WarningLevels`. |
| `APC_9049_checkAI.vi` | Verifies an acquisition block has 7200 columns (a full cycle). |
| `APC_9049_rpm.vi` | Engine speed from the DAQ data. |
| `APC_9049_FilesPathFormation.vi` | Builds log-file paths per the naming convention (`APC_CRIO9049_DATE_HOUR_TESTCODE_ID_*`). |
| `APC_9049_SaveTestAverageValues.vi` | AVG/STD/MIN/MAX rows for the test-averaged file. |
| `APC_9049_SparkSettings.vi` | Spark advance (DBTDC) + cutoff → `SparkControl` cluster in CAT/ticks via `Offset2CAT`/`time2ticks`. **Dwell hard-coded locally: 4 ms (min 2, max 6)** [Deck p.15]. |
| `APC_9049_KnockCA50Control.vi` | PID spark-advance trim to a CA50 setpoint, with knock override (knock sensed → retard by Delay_Knock; else creep forward by Advance_No_Knock). Reads `9049_Global_CA50`/`_SensedKnock`. **Both enables FALSE in lab config** — manual SA passthrough [Deck pp.17–19]. |
| `APC_9049_float2u16.vi` / `APC_9049_u162float.vi` | Pack/unpack float ↔ 2×U16 (Modbus registers; used by `UI_System`). |
| `APC_AppendUnits.vi` / `APC_ReplaceInNames.vi` | Signal-name utilities: append unit suffixes (`_bar`, `_degC`, `_b`, …); replace `-`→`_` for Matlab-safe names [DATALOG]. |

## cRIO-9049 — FPGA layer

### APC_9049_FPGA_main.vi — 40 MHz single-cycle FPGA main
Five sections [Deck pp.36–41]:
- **A** — configure NI-9401 DIO direction (Mod3: DIO0–3 in = enc A/B/Z + cam, DIO4–7 out;
  Mod4: all 8 out) and wait 1–2 s → `NI9401 Ready`.
- **B** — 500 ms heartbeat frame: `FPGA Heartbeat`, LED blink, `Chassis Temp Raw (×4 C)`
  (host converts), `dT HB (ms)`.
- **C** — encoder conditioning: per-signal deglitch low-pass filters (thresholds in clock
  ticks) → `ept_enc_vte2_revc` (NI Powertrain EPT, encoder pattern, EXTRAP=2 bits).
  Setup modes: real cam (`Must Use Cam & Z`=T) / 4-stroke cam-less (`1/2 Z pulse`=T →
  synthetic 720° cam from every other Z; `toggle TDC` inverts it) / 2-stroke.
- **D** — DAQ triggers: **Trig0 = conditioned ENC A = the sample clock for cylinder-pressure
  DAQ**; Trig1 = synthetic once-per-cycle pulse at `TRIG1_offset_ticks` (width = one cam
  tooth). Trig3 routable to PFI0 for debug/broadcast.
- **E** — actuation: `di_supv_exp_revf5` (DI driver supervisor; emits the **`Key`** that
  unlocks spark) + `esttl_vt_spark_reva` (spark out; needs Key + SparkControl +
  FuelSparkSupervisor from EPT). DI 1–6 → Mod5/Mod6 (NI 9751 DI-driver modules);
  Spark 1–6 → Mod4/DIO0–5.

**The safety anchor:** EPT's `WatchdogIn` must be toggled >4 Hz by the RT side
(`TS10ms_loop`); on loss of RT↔FPGA communication it **shuts down engine position
tracking and all engine-synchronous outputs** (spark/DI die with it) [GDoc p.2]. Sync loss
(`MissedCrankFlag`/`MissedCamFlag`) latches until explicitly cleared.

### APC_9049_FPGA_IGNDI_supervisor.vi — IGN/DI activity counter
Per-channel timers over SI1–6 + DI1–6: a channel with no rising edge within
`Time out limit` ticks is inactive; publishes `NumberOfActiveIGN_DI` (12 = all healthy on
6 cylinders), factoring `CrankStalled`/`SyncStopped` [Deck pp.43–46].

### Third-party FPGA/RT chain (NI Powertrain Controls, on disk inside the VIs)
`ept_revc` / `ept_enc_vte2_revc` (position tracking), `PlsGen_StdA5_revf5` (5-pulse DI
pulse generator; GDoc calls it PlsGen_StdT5), `PlsGen_Time_Convert_revf5` (ms/angle →
ticks/CAT, up to 5 pulses, non-overlapping windows; 5 ms max pulse by default),
`di_supv_revf5`/`di_supv_exp_revf5` + `di_rt_control_revf5`/`di_rt_iphase_conv_revf5`
(DI driver + 8-phase current profile), `esttl_vt_spark_reva` (spark),
`time2ticks`/`Offset2CAT`/`ticks2speed` (unit conversions), `filt_int_reva` (deglitch),
`one_shot_s1_reva`. Documented in [GDoc] and [Deck]; treat as vendor library.

---

## cRIO-9056 — RT layer

### APC_9056_RT_main.vi — 9056 top level
Startup: `LoadINI` (pushes XML/INI-persisted PID gains + warning limits into all
controllers), `SensorCalibrations` (build DAQ tasks + name registry), then `TS_loop`
forever.

### APC_9056_TS_loop.vi — plant control loop (the supervisory heart)
~5 parallel loops; the **control loop is paced by the NI9205 DAQmx block read at ~20 ms
(~50 Hz)** (confirmed live 2026-07-07 — the `1000 ms` wait belongs to a separate
housekeeping/streaming loop). Each control tick: read AI → sensor signals → run
`WarningIntegration`, `WatchDog`, **`StateMachine`**, then the per-subsystem controllers
(`NGControl`, `O2Control`, `ArControl`, `TcoolantControl`, `TexhControl`, `ToilControl`,
`DynoControl`, `MTRsignals`), convert outputs via `0_100_to_4_20mA`/`rpm_to_4_20mA`,
write AO/DIO through `APC_9056_FPGA_main`, publish `9056_MeasAndCalc`
(`SharedVarBroadcast`) and toggle `9056_HeartBeat`. Controller→actuator map [Ovw p.62]:
O2→`O2-FC-001-REF`, Ar→`N-PC-002-REF`, NG→`NG-FC-001-REF`, Tcoolant→`EC-FC-001-REF`,
Texh→`SW-FC-004-REF`, Toil→`SW-FC-009-REF`, Dyno→`DYNO-REF`; PC override switches route
NG/Ar/O2/vents to `NG-FV-001`, `O2-PV-004`, `AR-PV-004`, `WF-FC-001/002/003`.
Front panel carries the **unbound dev controls `ForceState`/`ManualState`** (see gotchas).
The leftover `APC_9053_FPGA_main.vi` reference sits in a **Disabled** diagram frame from
the lab-substitute cRIO-9053 era [Report; export d1 page]. Note: the export in
`../APC_9056_TS_loop/` (2026-07-07 22:49) **post-dates the B0 rewiring** — its main
diagram shows the as-wired WatchDog→Select(−1:3)→Min→StateMachine chain and the `*_SM`
telemetry-tap variables (verified by direct image inspection), even though the `.vi`
binary in this folder is the earlier snapshot.

### APC_9056_StateMachine.vi — THE supervisory state machine (ported → `supervisory/monarch/state_machine.py`)
"Turns `PC_ControlSettings` into `Limited_ControlSettings` and updates SYSTEM STATE,
never allowing a controller to run at a level higher than what the current state and the
state limitations from warnings permit" [Ovw p.74]. Inputs: `CURRENT SYSTEM STATE`,
`STATE LIMITATION FROM WARNINGS`, `PC_ControlSettings`, `ForceState`, `ManualState`.
Outputs: `SYSTEM STATE`, `Limited_ControlSettings` (+ diagnostic terminals for each
limitation source). Logic: state = **min**(requested, warnings limit, Force-idling→≤2,
Force-motoring→≤1, EMERGENCY STOP→−1), clamped to **+1 per tick** on the way up;
`ForceState=TRUE` overrides everything with `ManualState` (including e-stop — see
gotchas). The **executed** 16-row limiting array (pixel-verified from the full-res
2026-07-07 re-export; rows × states −1/0/1/2/3, plus the doc table's safe level):

| Row | Controller | SAFE | STAND_BY | MOTORING | IDLING | FIRING | safe level |
|---|---|---|---|---|---|---|---|
| 0 | NG feed | 0 | 0 | 0 | 0 | **6**¹ | closed |
| 1 | Ar feed | 0 | 0 | **3**² | 3 | 3 | closed |
| 2 | O2 feed | 0 | 0 | 2 | 2 | 2 | closed |
| 3 | COOL TEMP | 1 | 2 | 2 | 2 | 2 | max flow |
| 4 | EXH TEMP | 1 | **3**¹ | 3 | 3 | 3 | max flow |
| 5 | OIL TEMP | 1 | **3**¹ | 3 | 3 | 3 | max flow |
| 6–8 | INT/CROSS/EXH VENT | 0 | 1 | 1 | 1 | 1 | open |
| 9 | DYNO | 0 | 0 | 2 | 2 | 2 | stopped |
| 10 | IGN | 0 | 0 | 0 | 1 | 1 | off |
| 11 | DI | 0 | 0 | 0 | 1 | 1 | off |
| 12 | MTR | 0 | 0 | 2 | 2 | 2 | TBD |
| 13–15 | **NG/Ar/O2 feed valves** | 0 | 1 | 1 | 1 | 1 | closed |

¹ NOT typos (resolved 2026-07-08 via the controller exports): mode enums extend past
2 — cap 3 permits **cascaded** closed loop (Texh/Toil/Ar), and NG's 6 permits every NG
feedback mode (4/5/6 = lambda/IMEP/torque select).
² The on-diagram documentation table says Ar = 2s, but the executed array constant has
3s — a real difference: the executed value permits cascaded Ar control from MOTORING,
the doc table's 2 would forbid it.
Note rows 13–15: the feed shutoff valves are **forced closed only in SAFE**; in all
other states the requested valve position passes through — leaving FIRING, gas is cut
by the feed-controller modes going to 0, not by the valves.
`PostMortemSave` = `(CURRENT SYSTEM STATE > new state) ∧ ¬ForceState` — a manually
forced drop does not trigger the post-mortem dump. `DisregardWarnings` bypasses the
**entire** limiter, not just warnings. **`APC_9056_StateMachine.vi` = current 2026
version; `_v2` on disk elsewhere is an older 2024 draft, not newer.**

### APC_9056_WarningIntegration.vi — warnings → state limitation
Compares NI9205/9208/9214 channel arrays + a named process-signal cluster (AR-FT-001,
NG-FC-001, WF-OA-001/002, temperatures, IMEPn6, TORQUE, CylPresWarnings/Errors, …)
against `Raster*_limits` thresholds (INI-persisted; commanded via the
`9056_Set/Retrieve/Save/LoadWarnings*` shared variables; raster = one 9056 AI card —
see the UI_Errors entry), publishes the
`Raster1–5_Warnings/_WarningLevels/_WarningSign` + `Cylinder_Warnings` arrays, and
outputs **`STATE LIMITATION FROM WARNINGS`** (I8) for the StateMachine. Handles operator
clears (`APC_MASTER/SLAVE_ClearWarnings`) with `ClearSoftWarning` (yellow = self-clearing).
Also stall-detects the 9049 + 9056-FPGA heartbeats (counter vs threshold 10) — but those
flags drive **front-panel indicators only** (see gotchas).

**Full as-built semantics decoded 2026-07-14** (page-by-page re-read + the warning-helper
prints) → **`docs/9056-warning-policy-asbuilt.md`**. Highlights: limits are **4 severity
tiers × 16 slots per raster** (`value×sign < limit×sign`, severity = highest tier tripped,
legend 1 soft/self-clear · 2 → idle · 3 → motoring · 4 → safe+vent); per-slot severities
**max-latch** (soft 1s auto-zeroed by `ClearSoftWarning`; MASTER clear zeroes all + fires
the SLAVE handshake to the 9049); `ErrorMask` gates trips by state (nothing armed in
SAFE/STAND_BY, everything from MOTORING up); cylinder flags score `error?3:(warning?1:0)`
via `MergeCylErrors` — a 9049 cylinder ERROR clamps to **MOTORING, not SAFE**; the
`MaskErrors`/CylinderMask post-hoc masking design sits in a **Disabled diagram frame**
(dead code).

### APC_9056_WatchDog.vi — liveness watchdog (detection)
Monitors four heartbeats: `9056_HeartBeat`, `9049_HeartBeat`, and `PC_HB`/`MTR HB`
carried inside `PC_ControlSettings.PID control references`. Per heartbeat: a counter
increments each ~20 ms iteration the value is *unchanged* and trips `*notResponding`
past a threshold. The threshold inputs are **not wired at the TS_loop call site**, so
the VI's saved front-panel values are the deployed configuration. **Deployed values
(reprint 2026-07-07 23:41):** `Iteration Time [ms]` ≈ 20–21, `PCwatchdogThreshold` =
**250** (= 5 s, per the sizing analysis in `docs/migration-seam.md` — 50 would
false-trip on the ~1 Hz PC heartbeat), 9056/9049/MTR thresholds = 50 (= 1 s; fine for
the fast RT heartbeats, and the MTR flag is indicator-only). The reprinted panel also
carries an in-VI doc label: iteration time is set by the NI9205 DAQmx 20-sample block
read (~20 ms), so thresholds are multiples of 20 ms. In this snapshot the
outputs are **unwired** at the TS_loop call site; the live project (2026-07-07) wires
`PCnotResponding ∨ 9049notResponding → Select(−1:3) → Min →` StateMachine warnings input
— verified by a real PC-drop test.

### 9056 subsystem controllers — the shared mode pattern
All six are copies of one template (`TEMPLATEControl` is the blank scaffold, **no
callers**); facts below verified from the full exports (2026-07-07/08). Inputs =
signal cluster + `PC_ControlSettings` + `LoadIni?`. Mode (from `PID control
references.<X> control mode`): **0 = safe → output forced to the XML-configured
`Safe mode control` value** (currently 0.00 everywhere; not hard-coded, not
last-value); **1 = manual → the `<X>-REF (manual)` reference passes straight
through**; **2 = closed loop (NI `PID Advanced`)**; cascade VIs add **3 = cascaded**
(HL PID sets the LL PID's setpoint); NG adds **4/5/6 = feedback select**. Common
plumbing: `Override PC PID references` selects PC-supplied vs local references (mode
itself always comes from the PC); a `learn?` boolean captures feed-forward into
`FF control`; **every PID runs with hard-wired `dt = 0.100 s`** (see gotchas); per-loop
settings (gains, ranges, FF, safe value) persist to `…/bin/APC_9056_<X>_Settings.xml`.
The StateMachine's limiter caps each VI's mode.

| VI | Structure | PID PV → setpoint ref | Output | Notes |
|---|---|---|---|---|
| `APC_9056_NGControl.vi` | Single PID + feedback selector | mode 2/4: **1/λ** from `WF-OA-002` → `WF-OA-002-REF`; mode 5: `IMEPn6` → `IMEP-REF`; mode 6: `TORQUE` → `Nm-REF` (per-feedback gain sets) | `NG-FC-001-REF` | Diagram note: the flow regulator does the low-level control, so no cascade needed. **XML path is Windows-style `home:\…`** (others POSIX) — persistence may fail on Linux RT. |
| `APC_9056_O2Control.vi` | Single PID + NG feed-forward | **`EC-TT-001` (a coolant temp — mis-wired, see gotchas)** → `WF-OA-001-O2corr-REF` | `O2-FC-001-REF` | Switchable `compensate NG` feed-forward: NG flow (`NG-FT-001`/`NG-FC-001` via `FT/FC?`) × `O2/NG` ratio (default 3) added after the PID. (The overview p.64 said this compensation "should not be used"; no red box exists in the as-built VI.) |
| `APC_9056_ArControl.vi` | **Cascade** | HL: `WF-PT-004` (system pressure) → `WF-PT-004-REF`; LL: `AR-FT-001` (Ar flow) → HL output (or `AR-FT-001-REF`) | `AR-PC-002-REF` | Both PIDs captioned **"Warning hysteresis!"**. Panel notes: start with lower pressure reference; pressure-release mechanism TBD. LL manual ref mislabeled `SW-FT-001-REF`. |
| `APC_9056_TcoolantControl.vi` | Single PID | `EC-TT-001` → `EC-TT-001-REF` | `EC-FC-001-REF` (% → 4–20 mA) | The simplest of the family (modes 0/1/2 only). |
| `APC_9056_TexhControl.vi` | **Cascade** | HL: `WF-TT-004` (WF temp at exh HX) → `WF-TT-004-REF`; LL: `SW-FT-002` (water flow) → HL output (or `SW-FT-002-REF`) | `SW-FC-004-REF` (% → 4–20 mA) | HL PV *indicator* mislabeled `WF-TT-001` (wire is `WF-TT-004`). Panel gains all 0 — relies on its XML. |
| `APC_9056_ToilControl.vi` | **Cascade** | HL: `EO-TT-001` (oil temp) → `EO-TT-001-REF`; LL: `SW-FT-004` (water flow) → HL output (or `SW-FT-004-REF`) | `SW-FC-009-REF` (% → 4–20 mA) | Same shape as Texh. |
| `APC_9056_DynoControl.vi` | Single PID | `EngineSpeed_rpm` → `Speed ref` (PC cluster; manual refs `SpeedSetpointForPID`/`SpeedReference`) | `DYNO-REF` | Modes 0/1/2 only. Cosmetic copy-paste leftovers: modes comment box says "Tcool CONTROL MODES"; XML cluster labels say "LL …". |
| `APC_9056_MTRsignals.vi` | — | — | `MTR signals array` | Unpacks the MTR fields (`MTR modbus floats`/`u16`) carried inside `PC_ControlSettings` for logging/broadcast *(inference; the Modbus master is on the PC)*. |

Thermal loops fail to **max cooling** in SAFE (safe level = max flow).

### Other 9056 support VIs
| VI | What it does |
|---|---|
| `APC_9056_LoadINI.vi` | Startup: calls every controller + `WarningIntegration` in load-config mode (XML PID gains, warning limits). |
| `APC_9056_SensorCalibrations.vi` | Builds the 9056 DAQmx tasks + custom scales; calls the card-config VIs + `SetPathsTS`. |
| `APC_9056_NI9205conf.vi` / `NI9208conf.vi` / `NI9214conf.vi` | Channel name/offset/gain/unit registries per AI card (9205 ±10 V, 9208 4–20 mA, 9214 thermocouples). |
| `APC_9056_Signals.vi` | Assembles the full 9056 signal-name registry from the card configs + `additonalSignals`. |
| `APC_9056_additonalSignals.vi` | Names of derived/computed extra signals *(inference)*. |
| `APC_9056_SetPathsTS.vi` | Builds the TS log-file path (`APC_CRIO9056_DATE_HOUR_10Hz`) *(inference)*. |
| `APC_9056_SharedVarBroadcast.vi` | Publishes `9056_MeasAndCalc`. |
| `APC_9056_9049SharedVarPolling.vi` | Reads `9049_MeasAndCalc` (names via `APC_9049_CycleAvgSignals`). |
| `APC_9056_ErrorMask.vi` | **Per-state arming masks** (printed 2026-07-14). In: `SYSTEM STATE` only. Out: `raster1..5mask` + `CylinderMask` from saved boolean tables — rasters all-OFF in SAFE/STAND_BY, all-ON from MOTORING up; CylinderMask arms only MaxPressure+Knock and only in IDLING/FIRING. A low-speed AND branch exists but is inert (`EngineSpeed` not on the connector pane, low-speed table all-TRUE). |
| `APC_9056_MaskErrors.vi` | Elementwise `mask ? warning : 0` (U8 severities). **Dead as-built** — all call sites in a Disabled diagram frame of WarningIntegration (print d9). |
| `APC_9056_MergeCylErrors.vi` | 9049 flag matrices → five severity scalars (MaxPress, Misfire[rows 1–3 merged], CyclicVar, Knock, LateComb); per element `error ? 3 : (warning ? 1 : 0)`, max over cylinders. Row order: 0 MaxPress · 1–3 misfire variants · 4 CyclicVar · 5 Knock · 6 LateComb. |
| `APC_9056_ClearSoftWarning.vi` | Elementwise `x==1 ? 0 : x` ("Warning vector 0 to 4") — clears soft warnings only, ≥2 stay latched. |
| `APC_9056_WarningBool.vi`, `ForceArraySize16.vi`/`6b.vi` | Threshold booleans, array-size normalization *(inference from names/wiring)*. |
| `APC_0_100_to_4_20mA.vi` / `APC_rpm_to_4_20mA.vi` | Scale 0–100 % / rpm → 4–20 mA AO values. |

### APC_9056_FPGA_main.vi — 9056 FPGA (bridge + RT-stall safe-hold)
I/O bridge between the C-series modules (NI 9375 DIO, 9264 AO 0–10 V, 9266 AO 4–20 mA)
and RT [Report §B.2] — **but not logic-free (print 2026-07-14)**: an `RT watchdog`
boolean the RT side must keep toggling is edge-checked on a 10 ms clock; `Counter max`
(default 100 ⇒ 1 s) overflow → *"SAFE state is applied if RT watchdog is not alive"* —
**all AOs 0, all DOs FALSE**. So the 9056 has a below-RT hardware fallback symmetric to
the 9049 FPGA watchdog. Also: 0.5 s `FPGA Hearbeat` (→ `9056_HeartBeat`), chassis temp,
and a `cRIO_Trig7` toggle-period → `Detected mode` decoder (13-entry table; producer and
consumer unidentified — open question). Panel: "low level FPGA interface only — use RT
module to configure." Separate 9053/9056 variants existed for the lab-vs-plant chassis
swap. Details: `docs/9056-warning-policy-asbuilt.md` (side findings).

---

## Data logging (who writes what)

Four files, stored on the cRIO SSDs [DATALOG]:

| File | Producer | Format | Trigger | Contents |
|---|---|---|---|---|
| `*_CAS.tdms` | 9049 `SAVE_loop` | TDMS, 1/test | operator REC **or error** | raw CAS AI (Pcyl1–6, Ppre, Psyst, Pexh), 7200 rows/cycle, ≤1000 cycles; pre-trigger mode keeps the buffer before REC. |
| `*_CycleAVG.tdms` | 9049 `SAVE_loop` | TDMS, 1/test | operator or error | 1 row/cycle: combustion metrics + 9049 control echoes + 9056 TS variables + MTR block. |
| `APC_CRIO9049_DATE_TESTCODE.txt` | 9049 `SAVE_loop` | ASCII, 1/campaign | appended per recording | 4 rows (AVG/STD/MIN/MAX) × all CycleAVG columns; `Warning` column = 0 (operator) or error code (error-triggered); trailing file-name + test-notes columns. |
| `APC_CRIO9056_DATE_HOUR_10Hz` | 9056 TS_loop logging loop | TDMS (doc also says .txt) | automatic at startup | 10 Hz stream of all TS signals + MTR block + polled CAS averages. |

`DataSaveControl` (TEST CODE / ID / FLUSH-and-SAVE cluster) commands recording;
`PostMortemSave` requests an error-triggered dump (the StateMachine raises it on forced
transitions); `SavingInformation` reports back. Author flag: post-mortem behavior
"[TO BE VERIFIED]"; MTR + PC signals were still to be routed into the logs.

---

## Shared variables

`APC_SharedVars.lvlib` — 60 variables, hosted on the 9049. Variable URLs inside the `.vi`
binaries read `\\10.1.10.171\APC_SharedVars\…`, while the overview gives the cRIOs as
172.22.10.2/.3 — presumably lab vs plant network addressing; reconcile before deploying.
Types decoded from the lvlib. Producers/consumers from VI strings + docs; unmarked = not
yet traced.

| Variable | Type | Meaning / producer → consumer |
|---|---|---|
| `PC_ControlSettings` | cluster (`APC_ControlSettings.ctl`) | **The operator command cluster** (spark/DI/PFI settings, mode requests, e-stop, PID refs subcluster incl. `PC_HB`/`MTR HB`, MTR Modbus arrays). PC UI writes → 9049 TS10ms, 9056 TS_loop/WatchDog read. Modeled in `supervisory/monarch/control_settings.py`. |
| `9049_ControlSettings` | SGL array (8 elems) | 9049 command echo. `ControlSettingsRaster` writes → PC + 9056. Layout confirmed from the 2026-07-07 print and modeled in `supervisory/monarch/settings_9049.py` (values/scaling still to confirm against a live capture). |
| `Limited_ControlSettings` | — | **Does not exist as a shared variable** — it is a wire inside `TS_loop` (StateMachine output → controllers). A telemetry-only SV was added later by the gateway work. |
| `9049_Global_SYSTEMSTATE` | DBL | The 9049's **echo** of system state (written by `CAS_loop`); gates spark/DI in TS10ms. Can go stale if 9049 loops stop — fails safe (low = blocked). |
| `9049_Global_CA50`, `9049_Global_SensedKnock`, `9049_Global_CylPressError` | DBL / bool / bool | 9049-local (single-process) combustion feedback: CA50 for the spark PID, knock flag, and the pressure-error flag set by `CombCluster2Array` that kills spark/DI. |
| `9049_HeartBeat`, `9056_HeartBeat` | bool | RT liveness toggles (WatchDog + WarningIntegration + PC UI watch them). |
| `9049_MeasAndCalc`, `9056_MeasAndCalc` | DBL array | Each chassis' flat measurement+calculation broadcast (decoded by name registries). |
| `SyncCylPres [bar]` | DBL array | One selected live cylinder-pressure trace for the UI plot; channel picked by `9049_SelectBroadcastVar` (u8). |
| `IMEPg [bar]`, `IMEPn [bar]` | DBL array | Per-cylinder IMEP broadcasts. |
| `9049_WarningLevels`, `9056_WarningLevels` | clusters | Active warning-threshold sets (incl. running-IMEP-std / expected-IMEP deviation limits). |
| `9049_…` / `9056_…` `SetWarningLimits`, `RetrieveWarningLimits`, `SaveWarningLimitsToINI`, `LoadWarningsFromINI` | bool | Command flags from the Errors UI to each chassis' warning config. |
| `Raster1–5_Warnings` / `_WarningLevels` / `_WarningSign` | u8 / DBL arrays | The five warning "rasters" published by `WarningIntegration` for the Errors UI. **Raster = one 9056 AI card**: 1 = NI9205, 2 = NI9208, 3 = NI9214-1, 4 = NI9214-2, 5 = spare (from the UI_Errors export — resolves the SCADA reviewer's "what are rasters 1–5?"). |
| `Cylinder_Warnings` | u8 array | Per-cylinder combustion warnings. |
| `APC_MASTER_ClearWarnings`, `APC_SLAVE_ClearWarnings` | bool | Operator clear (PC button) / 9049-side clear relay. |
| `APC_MASTER_EmergencyStop` | bool | E-stop broadcast (in addition to the flag inside `PC_ControlSettings`). |
| `CASyncLost` | bool | Crank-sync loss flag (9049 → UI resync button flashes). |
| `CRIOtime`, `CRIOchassisT` | u32 / DBL | 9049 loop time [ms] and chassis temperature. |
| `DataSaveControl`, `PostMortemSave`, `SavingInformation`, `SendSyncTraces` | cluster/bool | Logging control (see Data logging). |
| `Ar_ON`, `Cond_ON`, `Cool_ON`, `DYNO_ON`, `ExhVENT_ON`, `IGN_DI_ON`, `IntVENT_ON`, `O2_ON`, `PFI_ON`, `MTR` | u8 | Per-subsystem status/level flags (0/1/2 mode levels) *(inference; consumers not traced)*. |

`APC_PCglobalVars.lvlib` (PC-local): `PC_Global_Errors` (color-box cluster),
`PC_Global_ListboxVarBroadcast*` (UI selections), `PC_GlobalVariables_DBLmain2syst` /
`PC_GlobalVariables_PIDsyst2main` (Main↔System panel exchange; the PID-refs relay that
also carries the live `PC_HB` toggle), plus a PC copy of `9049_Global_CA50`.

## Typedefs (`controls/`)

| Typedef | Used for |
|---|---|
| `APC_ControlSettings.ctl` | The command cluster — **byte-for-byte contract with Python** (`docs/monarch-control-settings.md`; re-run the flatten diff when it changes). |
| `APC_PIDcontrolSettings.ctl` | The "PID control references" subcluster (modes, setpoints, vents, `PC_HB`/`MTR HB`, MTR Modbus arrays). |
| `APC_PIDCluster.ctl`, `APC_PIDsettings.ctl`, `APC_cascadePIDsettings.ctl`, `APC_NG_PIDsettings.ctl` | PID display/gain clusters (single, cascade, NG-specific). |
| `APC_WarningLimits.ctl` | 9056 warning-threshold cluster. |
| `APC_CombustionMetrics.ctl`, `APC_CylMetrics.ctl`, `APC_PcylDiag.ctl`, `APC_CylDaignosticsCluster.ctl` (sic) | Combustion-analysis result/diagnostic clusters. |
| `APC_DAQqueues.ctl` | CAS/CycAvg queue + signal-list cluster handed between 9049 loops. |
| `APC_SavingFile.ctl` | Logging control cluster. |
| `APC_VisualizationCluster_v2.ctl` | The PC UI named-signal cluster (max 256). |
| `APC_volume.ctl` | Engine geometry (bore/stroke/rod/CR/offset) for the volume calc. |
| `APC_ErrorCluster.ctl`, `Error Type.ctl`, `FPGA State.ctl`, `Raw Values.ctl`, `Variable References.ctl`, `support/Message Queue/*.ctl` | UI/support plumbing. |

---

## As-built gotchas (read before trusting any diagram)

The system was **built but never commissioned**; the original developer left. Treat docs
as intent, VIs as ground truth, and expect provisioned-but-not-wired features. Live
verifications below are from this repo's Phase A/B work (2026-07), which post-dates this
snapshot.

1. **Detection without response was the norm.** Five instances found: (a) WatchDog
   `*notResponding` outputs unwired at the TS_loop call site → **fixed live 2026-07-07**
   (B0 wiring, verified by a real PC drop); (b) StateMachine's `STATE LIMITATION FROM
   WARNINGS` input ran on its front-panel default, warnings clamped nothing → **fixed
   live** (WarningIntegration output wired in); (c) WarningIntegration's own 9049/9056-FPGA
   heartbeat-stall flags drive indicators only — **still open**; (d) nothing toggled
   `PC_HB`, so `PCnotResponding` would have read permanently tripped → **fixed live**
   (UI_System toggle); (e) the `Limited_ControlSettings` telemetry shared variable was
   created but never written → superseded by call-site taps.
2. **`ForceState`/`ManualState` are unbound front-panel dev controls on `TS_loop`**
   (headless RT target ⇒ compiled defaults False/0 forever). The override path is inert
   as-built. Note: when forced, **ForceState overrides EMERGENCY STOP** (wired after the
   Min) — flagged for review.
3. **`DisregardWarnings` bypasses the entire limiter**, not just the warning clamp —
   misleading name.
4. **The limit table's ">2" cells are real mode caps, not typos** (resolved
   2026-07-08): cap 3 = cascade allowed (Texh/Toil/Ar), NG's 6 = all NG feedback
   modes allowed. The Ar row is a genuine **doc/array mismatch** (doc table 2s = no
   cascade; executed 3s = cascade allowed from MOTORING). And the NG/Ar/O2
   **feed-valve booleans are forced closed only in SAFE** (rows 0,1,1,1,1) — leaving
   FIRING, gas is cut by the controller modes, not the valves. The Python port
   reproduces all of this as-is.
4b. **`APC_9056_O2Control.vi`'s PID process variable is mis-wired to `EC-TT-001` (a
   coolant temperature)** — a Tcoolant copy-paste leftover; the setpoint is an O2
   concentration. Closed-loop O2 as-built regulates flow against the wrong signal —
   re-tag before any closed-loop O2 use. Smaller mislabels of the same family:
   Texh's HL PV indicator says `WF-TT-001` (wire is `WF-TT-004`); Ar's LL manual ref
   says `SW-FT-001-REF` (loop runs on `AR-FT-001`). Also: NG's settings-XML path is
   Windows-style (`home:\…`) on a Linux-RT target (persistence may silently fail),
   and every controller PID runs with hard-wired `dt = 0.100 s` while the TS_loop
   control loop is ~20 ms — if called every tick, integral/derivative action is ~5×
   faster than the gains imply. Verify at tuning time.
5. **State-echo skew**: `9049_Global_SYSTEMSTATE` (written by CAS_loop) is a relay of the
   9056 StateMachine's output and freezes if 9049 loops stop — observed fail-safe (a low
   echo blocks spark/DI), but alarm on sustained mismatch during commissioning.
6. **StateMachine location history**: 2023 design ran it in the 9049 `TS10ms_loop`
   (its diagram banner still says so, and the disabled `TS100ms_loop` is the leftover);
   it was migrated to the 9056 `TS_loop`. `APC_9056_StateMachine.vi` (2026) is current;
   `_v2` is an older 2024 draft despite the suffix.
7. **9053 vs 9056**: the lab validated on a cRIO-9053 stand-in; a 9053 FPGA variant
   existed, and a stale `APC_9053_FPGA_main.vi` reference survives inside the `TS_loop`
   binary.
8. **Boilerplate noise**: any "DAQmx Custom Scales" VI description and generic NI PID/
   statistics per-control text is template residue — no VI carries real documentation.
9. **Hardware/project mismatch**: the overview flags 9049 Mod8 (NI 9222) as not matching
   the wiring diagram; encoder is a BEI H25D 3600-line (0.1°).
10. **No-caller VIs in this copy**: `APC_9056_TEMPLATEControl.vi` (scaffold),
    `APC_PC_SlaveModbus.vi`, `APC_HRLtest.vi` (dev harnesses). `Items-W-No-Callers/`
    lists the orphans excluded from the copy.
11. **Author TODO hotspots** (from the docs, unresolved as of the snapshot): HRL volume
    calc ("FIX STROKE CALC", crankpin offset, IVC/EVO/EVC); O2Control red-box logic "do
    not use"; per-cylinder (vs uniform) spark/DI control; temporal warning rules ("oil
    pressure low > X s") never built; run sequences (purge/start/light-off/venting
    recovery) **never built at all** — greenfield, being authored in Python (Phase D);
    MTR PLC never successfully interfaced end-to-end; post-mortem save "[TO BE VERIFIED]".

## Where to go deeper

- **This repo's docs** (authoritative for the migration): `docs/migration-seam.md`
  (FLOOR/MIDDLE/BRAIN boundary + backlog), `docs/migration-plan.md` (phases + status),
  `docs/shadow-findings.md` (live validation log), `docs/monarch-control-settings.md`
  (the cluster contract), `docs/monarch-telemetry.md` (gateway), `docs/handoff.md`.
- **Exports** (diagrams as PNG/HTML): sibling folders under `original-labview-codebase/`.
- **PDFs/DOCX** in `original-labview-codebase/`: the Overview [Ovw] for slide-by-slide VI
  walkthroughs, [Deck] for the 9049 FPGA design, [GDoc] for EPT cluster field docs,
  SCADA/DATALOG/Report DOCX for HMI, logging, and the author's own status.
- **Python ports**: `supervisory/monarch/` — `state_machine.py` (validated 100% against
  live LabVIEW), `warning_policy.py`, `control_settings.py`, `labview_mapping.py`.
