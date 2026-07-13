# Accessing the cRIO filesystem (WinSCP / PuTTY)

The cRIOs run **NI Linux Real-Time**. Their filesystems are reachable over SSH
from the control-room PC — use **WinSCP** to move files, **PuTTY** for a shell.

## Hosts & accounts

| Target | IP | how to find |
|---|---|---|
| cRIO-9049 (`NI-cRIO-9049-020A5DED`) | `10.1.10.171` | known |
| cRIO-9056 (`CRIO9056 NTS`) | — | NI MAX → Remote Systems |

- **Users:** `admin` (config/full access) or `lvuser` (the account the RT app
  runs under; owns `/home/lvuser`). Either can read the app's files. Password is
  whatever was set in **NI MAX**; on a fresh NI Linux RT target it is often blank.
- **Prerequisite:** the target's SSH server must be on. If a connection is
  refused, enable **"Secure Shell Server (sshd)"** in NI MAX → the target →
  *Settings*, and reboot.

## Key paths on the target

- `/home/lvuser/natinst/bin/` — the deployed startup app (`startup.rtexe`) and
  the files it reads/writes with relative paths, e.g. **`CylWarningLevels.xml`**
  (the warning-limits config; written by the UI's *Save to INI file* action —
  it may not exist until a first save).
- `/var/local/natinst/log/` — RT logs (`errlog.txt`, `lvrt_*_cur.txt`).

## Retrieve a file — WinSCP

1. **New Session:** File protocol **SFTP**, Host name `10.1.10.171` (or the 9056
   IP), Port `22`, User name `admin` (or `lvuser`), Password from MAX. **Login**,
   accept the host key on first connect.
2. Left pane = PC, right pane = cRIO. Navigate the right pane to
   `/home/lvuser/natinst/bin/` (Ctrl+O lets you type the remote path directly).
3. **Download:** drag `CylWarningLevels.xml` to the PC pane (or right-click →
   *Download*). **Upload** a replacement by dragging the other way.
   *(If SFTP is refused, sshd is off — enable it in MAX, or use File protocol =
   FTP as a fallback.)*

## Connect to a shell — PuTTY

1. Host Name `10.1.10.171`, Port `22`, Connection type **SSH** → **Open**,
   accept the host key.
2. `login as:` **admin** (or `lvuser`), password from MAX.
3. Useful commands:
   ```
   ls -la /home/lvuser/natinst/bin/                 # deployed app + config files
   cat    /home/lvuser/natinst/bin/CylWarningLevels.xml
   ls -lt /var/local/natinst/log/                   # RT logs (newest first)
   ```
   PuTTY is shell-only. For a one-line file copy without WinSCP, use PuTTY's
   `pscp`:
   ```
   pscp admin@10.1.10.171:/home/lvuser/natinst/bin/CylWarningLevels.xml C:\temp\
   ```

See also `docs/deployed-bringup.md` (build/deploy to `/home/lvuser/natinst/bin`,
reading RT logs) and `docs/monarch-control-settings.md` (the warning-limits
data contract that `CylWarningLevels.xml` persists).
