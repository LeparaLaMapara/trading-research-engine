"""Run one of the engine's Python modules as a Databricks serverless job.

The workflow `databricks-run.yml` syncs the repository's code to the workspace and submits this
file with the code folder and the module to run as its parameters, for example `scripts.e08_fx_trend`. This file:

  1. copies the code to a scratch directory (workspace files are read-only for jobs),
  2. copies the latest data snapshot from the Unity Catalog volume into its data/ folder
     (uploaded daily by scripts/upload_to_databricks.py on the engine PC), and the outside
     data (data_ext/fetch.py) into data/external/,
  3. runs the module exactly as `python -m <module> <args>` would,
  4. copies any results it wrote under docs/results/ back to the volume, in a folder named
     for this run, so the workflow can fetch them.

It never holds broker credentials and cannot trade: there is no broker login in the job.
"""
from __future__ import annotations

import glob
import os
import runpy
import shutil
import sys
import time

VOLUME = "/Volumes/workspace/trading_engine"


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: run_module.py <code_dir> <module> [args...]")
        return 2
    # Databricks runs this file through exec(), so __file__ is not defined; the workflow
    # passes the synced code folder instead.
    src, module, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    work = "/tmp/trading-research-engine"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(src, work)
    os.makedirs(f"{work}/data", exist_ok=True)
    for f in glob.glob(f"{VOLUME}/raw/*"):
        shutil.copy(f, f"{work}/data/")
    # Outside data (data_ext/fetch.py): rates, positioning, funding, with its manifest.
    os.makedirs(f"{work}/data/external", exist_ok=True)
    for f in glob.glob(f"{VOLUME}/external/*"):
        if os.path.isfile(f):
            shutil.copy(f, f"{work}/data/external/")
    try:
        stamp = open(f"{work}/data/uploaded_at.txt", encoding="utf-8").read().strip()
    except OSError:
        stamp = "unknown"
    print(f"[dbx] data snapshot uploaded {stamp}; running {module} {' '.join(args)}")

    before = {p: os.path.getmtime(p) for p in glob.glob(f"{work}/docs/results/*")}
    os.chdir(work)
    sys.path.insert(0, work)
    sys.argv = [module, *args]
    t0 = time.time()
    code = 0
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:          # modules end with raise SystemExit(main())
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    print(f"[dbx] {module} finished with {code} in {time.time() - t0:.0f} s")

    run_dir = f"{VOLUME}/results/{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    written = [p for p in glob.glob(f"{work}/docs/results/*")
               if p not in before or os.path.getmtime(p) > before[p]]
    if written:
        os.makedirs(run_dir, exist_ok=True)
        for p in written:
            shutil.copy(p, run_dir)
        print(f"[dbx] results copied to {run_dir}: {[os.path.basename(p) for p in written]}")
    if code:
        raise RuntimeError(f"{module} exited with {code}")
    return 0


if __name__ == "__main__":
    main()
