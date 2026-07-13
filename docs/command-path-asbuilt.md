# Command path — as-built & verified (PC ⇄ cRIO)

**What this is:** the *verified as-built* of the PC→cRIO command path and its
loss-of-supervisor safety net, reconstructed from the LabVIEW exports under
`original-labview-codebase/` on **2026-07-11**. The **ICD (`docs/icd.md` §7) is
the spec**; this doc is the *evidence* that the spec is (or isn't) realized, with
per-claim VI + diagram-page citations so a future session can re-verify fast.

> TL;DR — The command path is **sound and single-writer end-to-end**.
> Source-select, e-stop precedence, and the `PC_HB` relay all match the ICD.
> The loss-of-PC SAFE clamp is **armed in both UI and PYTHON modes** (verified).
> **One specified-but-unbuilt gap:** `UI_HeartBeat` (ICD §7.5) — a dead operator
> console while Python holds authority is not yet detectable.

---

## 1. End-to-end flow

```
                     operator inputs (setpoints, modes, e-stop, PC_HB)
                                      │
   APC_PC_UI_System.vi ── writes ──►  PC_GlobalVariables_PIDsyst2main   (LabVIEW global)
        (P&ID tabs;                    │
         self-toggles PC_HB)           ▼
   APC_PC_UI_Main.vi ── reads global, assembles the full command cluster ──►  PC_OperatorRequests  (SV, ALWAYS)
        │                                                                        │
        │  case: CommandSource_IsPython?                                         │  (Python reads this as
        │   • FALSE (UI mode)  → promote PC_OperatorRequests → PC_ControlSettings│   telemetry "operator_requests")
        │   • TRUE  (PYTHON)   → do NOT promote (gateway writes it instead)      │
        ▼                                                                        ▼
   ┌─ UI mode:     UI  ──────────────────────────────────►  PC_ControlSettings (SV)  ──►  cRIO 9056
   └─ PYTHON mode: Python ─TCP:5020─► APC_PC_PythonGateway.vi ─► PC_ControlSettings (SV) ─►  cRIO 9056
                                       (validates, single-writer)
```

**Exactly one writer of `PC_ControlSettings` at a time** — UI in UI mode, gateway
in PYTHON mode. Never both (the UI redirects to `PC_OperatorRequests` in PYTHON
mode). This is ICD §7.4, and it is as-built (see §2, §3).

---

## 2. UI side — `APC_PC_UI_System.vi` + `APC_PC_UI_Main.vi`

| Claim | Evidence |
|---|---|
| `UI_System` bundles every operator input (all `-REF` setpoints, control modes, `EMERGENCY STOP`, `PC_HB`, `MTR HB`) into the LabVIEW global `PC_GlobalVariables_PIDsyst2main`. | `APC_PC_UI_System/…d.png` |
| `UI_System` **self-generates `PC_HB`** — feedback-node → Boolean NOT, flips every loop iteration (not on-change). | `APC_PC_UI_System/…d.png` |
| `UI_System` has **no** source-select and **no** `UI_HeartBeat`. | `APC_PC_UI_System` (all pages) |
| `UI_Main` reads the global and assembles the full `APCControlSettings` cluster (EMERGENCY STOP, Requested mode, spark/DI advance+duration, Speed ref, IGN/DI enable, Activate cylinder, Force idling/motoring, PID refs). | `APC_PC_UI_Main/…d.png` (2026-07-11 export) |
| **Source-select redirect (B3.c) — as-built.** `UI_Main` writes `PC_OperatorRequests` **always**; a case gated on `CommandSource_IsPython` promotes `PC_OperatorRequests → PC_ControlSettings` **only in the FALSE (UI-mode) case**. | `APC_PC_UI_Main/…d.png`, source-select case crop |
| `PYTHON (effective)` LED + `9056_PCnotResponding`/`9049notResponding`/`MTRnotResponding` reads are on the `UI_Main` panel (B3.b affordances). | `APC_PC_UI_Main/…d.png` |

> **Stale-export note:** the `UI_Main` export was **re-printed 2026-07-11 01:59**.
> An earlier 2026-07-08 copy predated B3.c and showed the UI writing
> `PC_ControlSettings` unconditionally — do not trust pre-07-11 `UI_Main` prints.

---

## 3. Gateway — `APC_PC_PythonGateway.vi` (Python-facing, TCP :5020)

Exports are `.gif`; convert with PIL to view (`Image.open(g).convert('RGB')`).

**Command block (upper True/"line arrived?" case):**
- Parses the JSON command (`name`, `id`, `params`/`settings`).
- **Source-select enforced:** a `CommandSource_IsPython` SV gates acceptance;
  a Python command while source = UI is **NACKed `"source is UI"`**.
- **Validation ladder** (NACK `reason` strings seen on the diagram):
  `rate` · `source is UI` · `parse` · `range: Speed ref %g` · `operator only`.
  → **Range-checking is `Speed ref` only (0..3000).** DI duration, spark advance,
  and PID refs are **not** range-checked at the gateway (see gap in §6).
- On accept: writes **`PC_ControlSettings`** (boxed True case) and replies
  `{"type":"command_ack","id":%d,"accepted":%s,"reason":"%s"}\r\n`.
- `CLEAR EMERGENCY STOP` is `operator only` → always NACKed from Python (e-stop
  precedence, ICD §7.4).

**Telemetry frame (lower True case) — emits all of:**
`{"type":"telemetry","seq","ts","system_state","warnings_limit","manual_state",`
`"force_state","settings","limited_settings","command_source","operator_requests"}`.
SV reads feeding it: `SystemState_SM`, `PC_ControlSettings`,
`Limited_ControlSettings`, `ManualState_SM`, `WarningLevels_SM`, `ForceState_SM`,
`CommandSource_IsPython`, `Operator Requests`.

Evidence: `APC_PC_PythonGateway/…d.gif` (main), command-region + telemetry-region crops.

---

## 4. `PC_HB` ownership & the WatchDog (detection)

- **`PC_HB` is a field of the command cluster** (`PID control references.PC_HB`),
  so whoever writes `PC_ControlSettings` sources it:
  **UI toggles it in UI mode; Python toggles it (via the gateway relay, every
  send) in PYTHON mode** (ICD §7.2/§7.5 option a). So `PC_HB` supervises the
  *active command path*, not the UI specifically.
- **`APC_9056_WatchDog.vi`** stall-counts four heartbeats independently. For PC:
  reads `PC_ControlSettings.PID control references.PC_HB` → change-detect →
  increment-or-reset counter → compare `> PCwatchdogThreshold` → `PCnotResponding`.
  **No source gate** — detection is mode-independent.
  Threshold = **250 counts ≈ 5 s** at the TS-loop rate (ICD §7.5).
  Same pattern for `9049_HeartBeat`, `9056_HeartBeat`, `MTR HB`.
- Evidence: `APC_9056_WatchDog/…d.gif` (07-07 export; the four-channel counter).

---

## 5. Loss-of-PC SAFE clamp — `APC_9056_TS_loop.vi` → `APC_9056_StateMachine.vi`

**The question "is the SAFE clamp gated on source = PYTHON?" — answer: NO, it is
armed in BOTH modes.** Verified from the 2026-07-10 `TS_loop` export:

```
   9056notResponding ─┐
   9049notResponding ─┤ OR ─► Select( true → -1 [SAFE] , false → 3 [FIRING] ) ─► StateMachine
   PCnotResponding  ──┘                                                          "STATE LIMITATION
                                                                                  FROM WARNINGS" (I8)
```

- The `PCnotResponding` flag feeds the −1/3 Select **directly**, OR'd with the
  two cRIO watchdogs. **No `CommandSource_IsPython` node gates it.** So a frozen
  `PC_HB` (Python *or* UI-mode command path dead) → limit −1 → SAFE, in either
  mode. This is the ICD §7.5 **end-state**, not the interim PYTHON-only gating.
- `MTRnotResponding` (membrane rig) is on a **separate** path — not in this OR.
- **`APC_9056_StateMachine.vi`** consumes that I8 as `STATE LIMITATION FROM
  WARNINGS` and **Min's it against the requested state** (warnings can only
  *lower* state), using the `MAX LEVEL OF CONTROL` table (rows = actuators, cols
  = states −1..3, plus a SAFE-LEVEL column). `DisregardWarnings` can bypass.
  Outputs `SYSTEM STATE` (I8) and `Limited_ControlSettings`.
- Evidence: `APC_9056_TS_loop/…d.png` (clamp crop) + `APC_9056_StateMachine/…d.png`.

> **Staleness caveat:** WatchDog & StateMachine exports are **2026-07-07**,
> TS_loop is **2026-07-10** — all pre-date the B3.c UI redirect (07-11), but the
> clamp wiring is direction-independent (it only reads the `*notResponding`
> flags), so the "armed in both modes" finding stands. Confirm once on hardware
> with a **UI-mode `PC_HB`-freeze drill** (kill the UI in UI mode → expect the
> 9056 to clamp SAFE within ~5 s). Logged drills only cover the PYTHON-mode
> freeze so far (B4-1/2).

---

## 6. The one real gap — `UI_HeartBeat` (specified, NOT built)

Because `PC_HB` follows Python in PYTHON mode (§4), it **cannot** detect the
operator console (the HMI that holds the software e-stop + monitoring) dying
while Python holds authority — Python keeps `PC_HB` alive through the gateway.
The clamp being armed in both modes (§5) does **not** close this: it fires on
`PC_HB` freeze, and `PC_HB` isn't frozen in that scenario.

ICD §7.5 already **specifies** the fix: a standalone `UI_HeartBeat` network SV
toggled by the UI loop *regardless of source*, watched as a **5th WatchDog
channel**. Response phase-in: alert + Python-side sequence-abort first; LabVIEW
SAFE clamp value team-decided (conservative default: SAFE). **Build task — not a
discovery.** Required before Python holds firing-relevant authority.

Other command-path gaps (see `docs/session-handoff-2026-07-11.md` §robustness):
thin gateway validation (Speed-ref-only, §3); unauthenticated TCP :5020;
no content-staleness guard on frozen-but-present telemetry.

---

## 7. Evidence index (what to re-open, and its freshness)

| VI export dir | Role here | Print date | Fresh enough? |
|---|---|---|---|
| `APC_PC_UI_System` | operator inputs → global; self-toggles `PC_HB` | 2026-07-11 | ✅ |
| `APC_PC_UI_Main` | global → cluster; **source-select redirect** | 2026-07-11 | ✅ (re-printed) |
| `APC_PC_PythonGateway` | validate + write `PC_ControlSettings`; telemetry frame | 2026-07-08 | ✅ (shows B3 command path) |
| `APC_PC_VariableMapping` | **telemetry return** (cRIO→PC merge) — *not* the command writer | 2026-07-11 | ✅ |
| `APC_9056_WatchDog` | stall-count heartbeats → `*notResponding` | 2026-07-07 | ✅ (direction-independent) |
| `APC_9056_TS_loop` | `*notResponding` → Select(−1:3) → SM warnings-limit | 2026-07-10 | ✅ (direction-independent) |
| `APC_9056_StateMachine` | Min warnings-limit vs requested; the limiter table | 2026-07-07 | ✅ |

Cross-refs: **spec** `docs/icd.md` §7; **seam/B0** `docs/migration-seam.md`;
**current status + robustness gaps** `docs/session-handoff-2026-07-11.md`.
