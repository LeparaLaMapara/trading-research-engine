"""Keep scripts/engine_loop.py running: restart it a minute after it exits, for any reason.

Started at logon from the user's Startup folder (Task Scheduler needs admin rights this
account's sessions do not have). The loop's own lock file stops a second copy, so starting
this twice is harmless.

    pythonw -m scripts.engine_supervisor
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from scripts.engine_loop import LOG, NO_WINDOW, ROOT

PY = sys.executable.replace("pythonw.exe", "python.exe")
SUP_LOCK = os.path.join(ROOT, "supervisor.lock")


def main() -> int:
    os.makedirs(ROOT, exist_ok=True)
    from scripts.engine_loop import _alive
    try:
        pid = int(open(SUP_LOCK, encoding="utf-8").read().strip() or 0)
        if pid and pid != os.getpid() and _alive(pid):
            return 0
    except (OSError, ValueError):
        pass
    with open(SUP_LOCK, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    while True:
        start = time.time()
        r = subprocess.run([PY, "-m", "scripts.engine_loop"], creationflags=NO_WINDOW,
                           capture_output=True, text=True, check=False)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z  supervisor: loop "
                     f"exited with {r.returncode} after {time.time() - start:.0f}s"
                     f"{': ' + r.stderr.strip()[-300:] if r.stderr.strip() else ''}\n")
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
