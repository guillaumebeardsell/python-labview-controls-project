# Deployed-Mode Bringup — 2026-07-09 Session Record & Procedure

First time the MONARCH control system ran **fully autonomous**: both cRIOs
booting their own startup applications with no LabVIEW attached, PC apps as
built EXEs, Python observing via the gateway. End state verified live:
`system_state = 0` (STAND_BY), `warnings_limit = 3` (no clamp), `PC_HB`
toggling, e-stop clear — **from the startup EXEs**, matching interactive
behavior.

This doc records the working procedure, the three root causes that had to be
fixed to get there (all latent deployment bugs that would otherwise have
surfaced during commissioning), and the recurring rules.

## The rules (learned the hard way)

1. **Run PC apps as built EXEs, never from the project.** Running any VI from
   the project forces LabVIEW to connect to referenced targets, and
   connecting to a cRIO **aborts its running startup application** (the
   "Conflict Resolution … abort the existing application" dialog). Click OK
   on that dialog only when you *intend* to stop the controller; on a live
   plant this is an operational decision. Default answer: **Cancel**.
2. **Exactly one shared-variable host.** `APC_SharedVars` lives on the
   **9049** (`10.1.10.171`) and nowhere else. A duplicate instance on any
   other machine (we found one on the control-room PC) splits clients across
   engines: some see live values, others see "(No Known Value)", and the
   9056↔9049 watchdogs false-trip. Check in DSM after changes; undeploy
   strays.
3. **Never build from out-of-sync VIs.** If LabVIEW shows *"VI edited in
   another application instance"*, the same VI differs between the PC and RT
   contexts. A build made in that state deploys **stale logic** (our 9056
   EXE shipped a stale `9049SharedVarPolling` and couldn't see the 9049).
   **File → Save All** (accept "synchronize with other contexts") until the
   error list is clean, *then* build.
4. **Reboot order: 9049 first, then 9056, then PC apps.** The 9049 hosts the
   variables everyone else binds to.
5. **Deploying the 9056 always pokes the 9049** (its dependencies include the
   9049-hosted library), so a 9056 "Run as startup" will offer to abort the
   9049's app — accept, then **restart the 9049 last**.

## Build & deploy procedure (both cRIOs, from scratch)

0. Pre-checks: actuator/valve power OFF (SAFE state actively drives outputs);
   welded-switch pass on panel defaults (see `docs/9049-openloop-audit.md`
   §8: Override=OFF, SimEnable=OFF, UsePcylDatabase=OFF, Enque?=ON).
1. **File → Save All**; confirm the Error List has no "edited in another
   application instance" items.
2. Under `NI-cRIO-9049…` → Build Specifications → `APC_9049_RT`
   (Real-Time Application, startup VI = `APC_9049_RT_main.vi`,
   target dir `/home/lvuser/natinst/bin`, filename `startup.rtexe`):
   **Build → Run as startup** (deploys + sets boot app + reboots).
   Credentials: the controllers' local admin account (in the team password
   store; same on both).
3. Under `CRIO9056 NTS` → `APC_9056_RT` likewise: **Build → Run as startup**
   → **OK** on the 9049 conflict → reboot 9056.
4. **Restart the 9049** (NI MAX → right-click → Restart) so its app returns.
   Wait ~2 min per chassis.
5. PC side, as EXEs from `C:\LabVIEW PROJECT\builds\MONARCH\`:
   `APC_Monarch.exe` (UI; toggles `PC_HB`) and `APC_PythonGateway.exe`
   (telemetry/command gateway, port 5020). Do **not** run these VIs from the
   project (rule 1). Only one gateway client at a time (single-session
   listener).
6. Do not right-click-Deploy `APC_SharedVars.lvlib` manually — it ships
   inside the 9049 app and self-deploys at boot. Manual deploys are how stray
   copies appear (rule 2).

## Verification checklist

- DSM: `9049_HeartBeat` toggling (~2 Hz), `9056_HeartBeat` toggling;
  `APC_SharedVars` hosted **only** on the 9049. (The 9049 may appear twice —
  once by hostname, once by IP `10.1.10.171` — same machine, same engine;
  cosmetic.)
- UI: `9056_PCnotResponding` OFF once the UI EXE runs;
  `9056_9049notResponding` OFF.
- Telemetry (gateway or `examples/monarch_listen.py`): `warnings_limit = 3`,
  `system_state` numeric and tracking the request; with UI closed the state
  must clamp to SAFE in ~5 s (loss-of-PC watchdog) and step-recover on
  restart.
- The 9049 state *echo* (`9049_Global_SYSTEMSTATE`) numeric, not NaN
  (NaN = the 9049 cannot read the 9056 broadcast — split engine or 9049 app
  down).
- Cold-start drill: power-cycle both chassis → everything returns by itself
  (9049 first) → SAFE → STAND_BY once the UI runs.

## Root cause #4 (found later the same day): FPDCO load crash

The 9049 startup app **crashed intermittently at load** — some boots fine,
some dead before the first heartbeat (which earlier looked like "dies after a
while" / random staleness). The controller's own log gave the answer in one
line:

    DAbort 0xC8211D41: Problem loading "APC_9049_CAS_loop.vi"
    ... FPDCO data is not initialized

Cause: the RT build's default **"Remove front panel"** stripped panel data
that `APC_9049_CAS_loop.vi` needs at load time (panel-heavy loop VI with
locals/refs to its controls). Fix: build spec → **Source File Settings** →
select each RT loop VI (`CAS_loop`, `SAVE_loop`, `TS10ms_loop`) → untick
*Use default save settings* → untick **Remove front panel** (leave *Remove
block diagram* checked) → Clear Compiled Object Cache → Save All → rebuild →
redeploy. Because the crash was intermittent, the acceptance test is
**three consecutive clean reboots** with the heartbeat returning each time.

**The diagnostic move that ended the guessing — pull the RT log over SSH:**
enable Secure Shell Server in MAX (System Settings), then
`ssh admin@10.1.10.171` → `ls -lt /var/local/natinst/log/` →
`cat` the newest `errlog.txt` / `lvrt_*_cur.txt` / `lvlog*.txt`. A healthy
boot shows `InitExecSystem` + `starting LV_ESys…` thread lines; a load crash
shows a `DAbort` with a bread-crumb of the VI being loaded. Use this FIRST
whenever a cRIO app "isn't coming up" — one real error message beats hours of
black-box inference. (For the full SSH/SFTP file-access recipe — WinSCP for
files, PuTTY/`pscp` for a shell — see `docs/crio-file-access.md`.)

## Symptom → cause quick table

| Symptom | Cause |
|---|---|
| 9049 app dead after *some* boots, fine after others | FPDCO load crash — see root cause #4 (front panels stripped from RT loop VIs) |
| `system_state` NaN (echo) | 9049 can't read 9056 broadcast: 9049 app down, or split variable engines, or `9056_MeasAndCalc` not published (open item) |
| `9049notResponding` ON while DSM shows the heartbeat toggling | The 9056 reads a *different* engine instance than DSM (duplicate library), or its build predates the sync fix |
| `PCnotResponding` ON | No UI EXE / Python toggling `PC_HB` (by design → SAFE) |
| State stuck −1 with `warnings_limit = −1` | One of the watchdog flags above, or a black-level warning (check the Errors screen / `Raster*_WarningLevels`) |
| Variables "(No Known Value)" in DSM | You're looking at an orphan/duplicate instance (check the host node) |
| Conflict dialog on any run/deploy | Rule 1 / rule 5 — decide deliberately, restart the 9049 afterwards |
| Command inputs ignored while UI runs | `command_source` = PYTHON with no commander running: UI writes go to `PC_OperatorRequests`, nothing applies them. Flip source to UI (B3.b switch on `UI_Main`) or run the Python commander |

## As-built deltas this session (2026-07-09)

- `APC_9056_WatchDog.vi`: 9049 threshold raised **50 → 250** (~5 s at the
  ~20 ms loop) — margin for the 9049 heartbeat's ~2 Hz toggle (it is paced by
  the FPGA 500 ms heartbeat frame, not the 10 ms loop). Same value as the PC
  threshold; well inside the safe-hold budget (the FPGA watchdog remains the
  hard, millisecond-scale spark/DI kill).
- New build specs: `APC_9049_RT`, `APC_9056_RT` (RT startup apps),
  `APC_PythonGateway` (PC EXE). `APC_Monarch` (existing) builds the UI.
- Stray `APC_SharedVars` instance undeployed from the control-room PC
  (DSM → Network Items → DESKTOP → Undeploy); verified it does not return
  when the EXEs run.
- cRIO admin credentials confirmed and recorded in the team password store.

## Status / next

Autonomous deployment **works end to end** (verified live 2026-07-09,
including the FPDCO fix: STAND_BY reached from startup EXEs). Open items:

1. **Three-reboot acceptance test** of the 9049 (the FPDCO crash was
   intermittent — one clean boot proves nothing).
## Root cause #5 — DAQmx startup race (FOUND & FIXED, 2026-07-10)

The 9056 deployed EXE came up with **all-zero `9056_MeasAndCalc`** (only the
timestamp non-zero) and **`9049_Global_SYSTEMSTATE` = NaN**. Symptom, from a
debug-probe of the running EXE: **`-200088` "Task specified is invalid or does
not exist" at `DAQmx Timing (Sample Clock).vi`.** The whole investigation was a
lesson in false leads — ruled out, in order: DSM "blank" array (DSM can't
render array/"Advanced" SVs — blank ≠ empty; Quality=Good means written); FPGA
(disabling the FPGA loop didn't help — heartbeat went stale, DAQ still failed);
`emulate 9205/9208/9214` controls (default FALSE); front-panel stripping (kept
all panels, still failed); "generic config" (a **subVI-front-panel artifact** —
`SensorCalibrations`' *own* panel shows stale defaults, but `RT_main`'s
indicators, fed by its actual output, showed the **real** config `WF-PT-001_bar`
etc. in the EXE); stale/duplicate copies (build referenced the correct file).

**The decisive experiment (the user's):** in the EXE, `9056_MeasAndCalc` was
zeros — but **stopping and restarting `APC_9056_RT_main` made it fill with real
values**. Stop/restart-fixes-it is the unmistakable signature of a **boot-time
device-readiness race**: the startup `.rtexe` launches *before NI-DAQmx has
finished enumerating the C-series modules*, so the first `SensorCalibrations`
task-create/timing fails with −200088; a manual restart re-runs it after DAQmx
is ready. Interactive always worked for the same reason (the controller was
already booted). A fixed 60 s `Wait` did **not** fix it (it's device *state*,
not just elapsed time — the restart also releases the failed task).

**Fix (in `APC_9056_RT_main`):** a short initial `Wait` (5 s), then wrap the
`SensorCalibrations` call in a **retry While loop** — condition `error.status
AND (i < 50)` (Continue-if-True), a 1 s `Wait` per iteration, outputs as
Last-Value tunnels into `TS_loop`. **No Clear Task / Reset Device needed** — a
*failed* DAQmx create doesn't reserve the device, so simply re-calling
`SensorCalibrations` succeeds once DAQmx is ready. (An early attempt with a
`DAQmx Clear Task` on the task array was a bug: it also cleared the good task
that flows to `TS_loop`, so it kept failing — removing it fixed it.) The
deployed EXE now self-heals on a cold boot.

**Verify:** cold power-cycle the 9056 (hands off) 3×; each time it must come up
with real `9056_MeasAndCalc` and a numeric state, no manual restart.

## Symptom → cause quick table (superseded detail retained for #5)

2. **`9056_MeasAndCalc` all zeros / state NaN in the deployed EXE** →
   **DAQmx startup race** — see root cause #5. Fix: retry loop around
   `SensorCalibrations`. (All the "generic config / stale copy / FPGA"
   leads were false — the config loads fine; DSM just can't show arrays and
   subVI panels show stale defaults.)
3. Hardening drills: cold power-cycle of both chassis; kill-UI → SAFE →
   recover on the deployed build.

Then the deployed system is the platform for the SIL work in
`docs/9049-openloop-audit.md` §7 (EPT `SimEnable` virtual crankshaft,
synthetic CAS traces).
