"""Standalone E16 loop: runs the forecast cycle once per UTC hour, from minute 1.

The engine loop does the same (scripts/engine_loop.py maybe_forecast); the cycle's lock file and
its "hour already recorded" check make running both safe. This exists for when the engine loop
cannot be restarted without admin rights (it runs as a Windows service).

    pythonw -m scripts.forecast_loop
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from config import settings

PY = sys.executable.replace("pythonw.exe", "python.exe")
LOG = os.path.join(settings.ARTIFACT_ROOT, "engine", "forecast.log")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main() -> int:
    done = None
    while True:
        hour = int(time.time()) // 3600
        if hour != done and time.time() - hour * 3600 >= 60:
            with open(LOG, "a", encoding="utf-8") as out:
                out.write(time.strftime("%Y-%m-%d %H:%M:%SZ ", time.gmtime()) + "standalone loop: cycle\n")
                out.flush()
                r = subprocess.run([PY, "-m", "forecast.cycle"], stdout=out, stderr=out, timeout=900,
                                   creationflags=NO_WINDOW, check=False)
            # Exit 2 = the broker session failed and nothing was written: retry until minute 15.
            if r.returncode != 2 or time.time() - hour * 3600 > 900:
                done = hour
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
