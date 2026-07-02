# Hello VI — LabVIEW ⇄ Python Connectivity Experiment

Goal: prove two-way communication between LabVIEW 2020 SP1 and the Python
stack while both run, before porting any logic. The LabVIEW side is a
throwaway VI built from TCP and string primitives only — **no JSONtext, no
clusters, no parsing**. Pair it with `examples/hello_link.py`.

Success looks like:

- Python prints `telemetry seq=1 mode=HELLO ...` lines at ~1 Hz with an
  incrementing counter.
- LabVIEW's front panel shows heartbeat lines arriving at 1 Hz and a ping
  command every 5 s.
- Python prints an `ack id=1 accepted=True reason='hello from LabVIEW'` for
  every ping.
- Ctrl-C on the Python side prints `RESULT: PASS`.

## 1. Build the VI

**Front panel:** a string indicator `Last received` , a numeric indicator
`Lines received`, a numeric indicator `Telemetry seq`, and a boolean LED
`Client connected`.

**Block diagram:**

Add a `Stop` button with mechanical action **Switch When Pressed** — not
latched: both loops read it, and a latch resets on the first read so the
second loop would never see it.

1. `TCP Create Listener`, port **5020**, outside all loops.
2. **Outer while loop** — one iteration per client session. Exit condition:
   `Stop` (via a **local variable**) OR a listener error other than 56.
   - `TCP Wait On Listener` with timeout **500 ms** — not −1, or the loop
     blocks inside the primitive and the Stop button is never polled while
     waiting for a client. Error 56 (timeout) means "no client yet": clear
     it and loop. When it returns a connection ID, set `Client connected`
     true.
   - **Inner while loop** — the session:
     Exit condition: `Stop` (button terminal) OR a read error other than 56.
     - `TCP Read`, mode **CRLF**, max bytes 4096, timeout **100 ms**.
       - Error 56 (timeout) is normal: clear it, treat as "no line".
       - Any other error (66 = peer closed): exit the inner loop.
     - If a line arrived: write it to `Last received`, increment
       `Lines received`.
     - **Reply to commands** (a `command_ack`) and **send telemetry at
       1 Hz** — both are `TCP Write`s on this same connection. Node-by-node
       wiring is in **§1a** below; both live inside this inner loop.
   - After the inner loop exits: `TCP Close Connection` on the **connection
     ID**, set `Client connected` false, loop back to `TCP Wait On Listener`
     — so Python can disconnect and reconnect freely.
3. After the outer loop exits: `TCP Close` the **listener**.

The inner loop needs no wait primitive — the 100 ms read timeout paces it.

**Refnum rule (this is what causes most Error 1 dialogs).** `TCP Wait On
Listener` has two stacked teal outputs: **listener ID out** (top) and
**connection ID** (bottom). Every per-session TCP node — `TCP Read`, both
send-side `TCP Write`s, and the inner `TCP Close Connection` — takes the
**connection ID**, branched from one wire. The **listener** refnum (from
`TCP Create Listener`, or WOL's top output) goes to exactly two places:
WOL's *listener in*, and the final `TCP Close` **outside** the outer loop.
Feed the inner close the listener by mistake and you destroy the listener at
the end of each session, so the next `Wait On Listener` fails with Error 1.

## 1a. Building the send side, node by node

Both pieces go in the **inner (session) loop** and both `TCP Write` to the
**connection ID** (branch the same teal wire that feeds `TCP Read`). Thread
the error wire `TCP Read → ack → telemetry → loop edge` so the writes run
*after* the read, in order, and short-circuit if the read already errored.

### Command reply (produces `ack id=1 ...` in Python)

Build this first — it's the quick win, and a `telnet` session can trigger it.

1. **`Match Pattern`** (String palette). Wire the **received line** (the
   `TCP Read` *data out*, same wire that feeds `Last received`) into its
   *string* input.
2. Into *regular expression*, wire a **string constant** containing exactly
   `"type":"command"` (normal display — the double-quotes are literal
   characters, nothing to escape).
3. `Match Pattern`'s *offset past match* output (bottom, I32) → **`≥ 0`**
   (`Greater Or Equal To 0?`). That boolean is "a command line arrived."
   (Equivalent: *match substring* → `Empty String/Path?` → `Not`.)
4. Feed the boolean to a **Case structure**:
   - **True:** a **string constant in `'\' Codes Display`** (right-click →
     *'\' Codes Display* so `\r\n` becomes a real CR+LF), containing:

     ```
     {"type":"command_ack","id":1,"accepted":true,"reason":"hello from LabVIEW"}\r\n
     ```

     → `TCP Write` *data in*; connection ID → `TCP Write` *connection ID*;
     pass the error through.
   - **False:** wire connection ID and error straight across, write nothing.
5. Nest this inside the same "line arrived?" case you already use to update
   `Last received` / bump `Lines received`, so you're not matching on an
   empty timeout string. (Harmless if you don't — an empty string never
   matches — but tidier.)

### 1 Hz telemetry (produces `telemetry seq=...` in Python)

Add **two shift registers** to the inner loop (right-click the loop border →
*Add Shift Register*, twice):

- `lastTick` (I32) — initialize the left terminal, outside the loop, with a
  single `Tick Count (ms)` read (or just `0`; then the first frame fires
  immediately, which is fine).
- `seq` (I32) — initialize the left terminal with `0`.

Each iteration:

1. `Tick Count (ms)` → **`now`**. Compute `now − lastTick` (**`Subtract`**) →
   `elapsed`. Test `elapsed ≥ 1000` (**`Greater Or Equal?`**) → boolean.
2. **Case structure** on that boolean:
   - **True (time to send):**
     - `seq` → **`Increment`** → `newSeq`.
     - **`Format Into String`**: format-string constant

       ```
       {"type":"telemetry","seq":%d,"ts":0,"mode":"HELLO","channels":{"counter":%d},"flags":{"labview_ok":true}}
       ```

       Grow the node to **two arguments** and wire `newSeq` (I32) to **both**
       `%d` inputs. Output is the JSON line, no terminator.
     - **`Concatenate Strings`**: JSON `+` a `\r\n` constant (`'\' Codes
       Display`).
     - `TCP Write`: *data in* = that string; *connection ID* = the
       connection (branch the `TCP Read` wire).
     - `newSeq` → the `seq` shift register (right) **and** → the
       `Telemetry seq` indicator. `now` → the `lastTick` shift register
       (right).
   - **False (not yet):** pass `seq` and `lastTick` through their shift
     registers **unchanged**; connection ID and error straight across, no
     write.

The `%d` fields want an integer — keep `seq` as **I32** (an orange/DBL wire
into `%d` coerces with a warning). `ts` is hard-coded `0` here on purpose;
the Python side tolerates it for this experiment.

### Quick verification

- **Without Python:** `telnet 127.0.0.1 5020` — a telemetry line should
  appear every second; typing
  `{"type":"command","id":1,"name":"x","params":{}}` + Enter should return
  the ack line (see §4).
- **With Python:** `telemetry seq=...` at 1 Hz and `ack id=1
  accepted=True reason='hello from LabVIEW'` after each ping; Ctrl-C →
  `RESULT: PASS`.

## 2. Run the Python side

Two options, in order of preference:

**A. Python on Windows (matches the production topology).** Both processes
run on the same machine and connect over `127.0.0.1`, so Windows Firewall is
not involved. Use **Command Prompt** for the steps below (Win+R → `cmd` →
Enter); PowerShell also works with one extra hurdle noted in step 3.

*Step 1 — install Python 3.10+ (once).*

1. Check what's already there: `py --version` (or `py -0p` to list every
   installed version). If it reports 3.10 or newer, skip to step 2 — the
   test suite is verified on 3.10. Careful: typing `python` on a machine
   *without* Python opens the Microsoft Store — that's a Windows alias, not
   an installation.

   Note for later: Python 3.10 stops receiving security fixes in October
   2026, so before this layer goes to production, install a current 3.12/3.13
   alongside it (Windows installs coexist; nothing else on the PC is
   disturbed) and recreate the venv with `py -3.13 -m venv .venv`. The code
   runs unchanged.
2. Download the latest 64-bit installer from
   <https://www.python.org/downloads/windows/>.
3. Run it. On the first screen **check "Add python.exe to PATH"**, then
   *Install Now* (per-user install, no admin rights needed).
4. Close and reopen Command Prompt — PATH changes don't reach already-open
   windows — and confirm with `python --version`.

*Step 2 — install Git (once).* `git --version`; if it's missing, install
from <https://git-scm.com/download/win> (all defaults are fine) and reopen
the terminal. No-git fallback: on the GitHub repo page, *Code → Download
ZIP*, extract, and skip the `git clone` below — but you lose easy
`git pull` updates.

*Step 3 — clone and install (once).*

```bat
cd C:\
git clone https://github.com/guillaumebeardsell/python-labview-controls-project.git
cd python-labview-controls-project
py -m venv .venv
.venv\Scripts\activate
pip install -e .
```

- `py -m venv .venv` creates a private Python environment in `.venv\`, so
  nothing is installed machine-wide on the control-room PC. We use the `py`
  launcher (not `python`) because it works even when Python was installed
  without the "Add to PATH" option — bare `python` on such a machine hits
  the Microsoft Store alias instead. After `activate`, plain `python` works
  in that terminal: the venv puts its own `python.exe` first on PATH.
- `activate` puts that environment on this terminal's PATH — the prompt
  gains a `(.venv)` prefix. It's needed once per new terminal. In
  PowerShell the command is `.venv\Scripts\Activate.ps1`; if that's blocked
  by execution policy, run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or just use
  Command Prompt.
- `pip install -e .` downloads pydantic and installs the `supervisory`
  package in editable mode: after a `git pull`, code changes take effect
  with no reinstall. Expect `Successfully installed supervisory-0.1.0`.
- Offline control-room PC? `pip install` needs internet once. If the
  machine has none, on a connected PC run
  `pip download -d wheels pydantic` , copy the `wheels\` folder over, and
  install with `pip install --no-index --find-links wheels -e .`.

*Step 4 — run the experiment.*

1. Start the hello VI in LabVIEW (and make sure the `stop` button isn't
   still latched TRUE from a previous run).
2. In the `(.venv)` terminal:

   ```bat
   python examples\hello_link.py
   ```

3. Within a second you should see `connected to gateway at 127.0.0.1:5020`,
   the VI's `Client Connected` LED on, and `Lines received` climbing about
   once per second (heartbeats) with an extra bump every 5 s (pings).
4. Once the VI's send side is built you'll also see `telemetry seq=...` at
   1 Hz and an `ack id=1 ...` after every ping in the Python window.
5. Ctrl-C stops the script and prints the summary. `RESULT: PASS` needs
   both directions — with a receive-only VI you'll get telemetry/ack counts
   of 0 and a FAIL even though the Python→LabVIEW half is proven by
   `Lines received`.

*Day-to-day afterwards:* new terminal →
`cd C:\python-labview-controls-project` → `.venv\Scripts\activate` →
`git pull` → run.

*Troubleshooting.*

- `'python' is not recognized`, or the Store opens: the PATH box wasn't
  checked. Rerun the installer → *Modify* → check it, then reopen the
  terminal. The `py` launcher usually works regardless:
  `py examples\hello_link.py`.
- `'git' is not recognized` right after installing: reopen the terminal.
- Python logs endless `connect ... failed` / `No connection could be made
  because the target machine actively refused it`: the VI isn't running or
  isn't listening on 5020. Check the port independently from PowerShell:
  `Test-NetConnection 127.0.0.1 -Port 5020` (the classic `telnet` client is
  disabled on Windows by default).
- Script connects but `Lines received` never moves: the VI is running but
  stuck before `TCP Read` — check the `Client Connected` LED and the case
  structure paths.

**B. From the devcontainer (no Windows Python needed).** LabVIEW's listener
accepts connections on all interfaces by default, so from the container:

```bash
python examples/hello_link.py --host host.docker.internal
```

If it can't connect, Windows Firewall is the usual suspect: allow LabVIEW
(or port 5020) for the vEthernet/WSL network when Windows prompts, or add an
inbound rule.

## 3. Try the failure modes while you're there

- Stop the Python script mid-run: LabVIEW should ride through (read
  timeouts), then accept the reconnect when you restart the script.
- Stop and restart the VI: Python logs `gateway link down, reconnecting`,
  then reconnects by itself within ~5 s.

## 4. Sanity-check the VI without Python

From any shell on the Windows machine, `telnet 127.0.0.1 5020` (or
`ncat`) — you should see a telemetry line appear every second, and typing
`{"type":"command","id":1,"name":"x","params":{}}` + Enter should get the
ack line back.
