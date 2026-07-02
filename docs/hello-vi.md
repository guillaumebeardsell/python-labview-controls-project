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

1. `TCP Create Listener`, port **5020**, outside all loops.
2. **Outer while loop** — one iteration per client session:
   - `TCP Wait On Listener` (timeout −1). When it returns a connection ID,
     set `Client connected` true.
   - **Inner while loop** — the session:
     - `TCP Read`, mode **CRLF**, max bytes 4096, timeout **100 ms**.
       - Error 56 (timeout) is normal: clear it, treat as "no line".
       - Any other error (66 = peer closed): exit the inner loop.
     - If a line arrived: write it to `Last received`, increment
       `Lines received`.
     - `Match Pattern` on the line for `"type":"command"`. If found,
       `TCP Write` this constant (string constant in **'\' Codes Display**
       so `\r\n` is real):

       ```
       {"type":"command_ack","id":1,"accepted":true,"reason":"hello from LabVIEW"}\r\n
       ```

     - Telemetry at 1 Hz: keep the last-send tick in a shift register
       (`Tick Count (ms)`). When ≥ 1000 ms have passed, increment the seq
       shift register, `Format Into String` with this format string (seq
       wired to **both** `%d`s), append `\r\n`, `TCP Write`:

       ```
       {"type":"telemetry","seq":%d,"ts":0,"mode":"HELLO","channels":{"counter":%d},"flags":{"labview_ok":true}}
       ```

       Show the seq on `Telemetry seq`.
   - After the inner loop exits: `TCP Close Connection`, `Client connected`
     false, loop back to `TCP Wait On Listener` — so Python can disconnect
     and reconnect freely.
3. Stop button as needed; `TCP Close` the listener on exit.

The inner loop needs no wait primitive — the 100 ms read timeout paces it.

## 2. Run the Python side

Two options, in order of preference:

**A. Python on Windows (matches the production topology).** Install Python
3.11+ from python.org (check "Add python.exe to PATH"), then:

```bat
git clone https://github.com/guillaumebeardsell/python-labview-controls-project.git
cd python-labview-controls-project
pip install -e .
python examples\hello_link.py
```

Both processes on the same machine, connecting over `127.0.0.1` — no
firewall involvement.

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
