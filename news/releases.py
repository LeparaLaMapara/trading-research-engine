"""US data release days from the St. Louis Fed's ALFRED vintage archive (no key needed).

Every vintage of a series is the day a version was published. A vintage is a RELEASE only when
it adds a new month of data; seasonal-factor revisions and re-basings add none and are dropped.
Both series are released at 08:30 New York.

    python -m news.releases            # writes data/releases.json

The Forex Factory history on Hugging Face is mistimed (news/calendar.py) and is never used.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

OUT = "data/releases.json"
SERIES = {"NFP": "PAYEMS", "CPI": "CPIAUCSL"}
LIST = "https://alfred.stlouisfed.org/series/downloaddata?seid={sid}"
VINTAGE = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={sid}&vintage_date={d}"
SPAN = ("2014-01-01", "2026-10-31")


def get(url: str) -> str:
    for attempt in range(4):
        try:
            return urllib.request.urlopen(url, timeout=60).read().decode()
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def vintages(sid: str) -> list[str]:
    d = sorted(set(re.findall(r"20\d\d-\d\d-\d\d", get(LIST.format(sid=sid)))))
    return [x for x in d if SPAN[0] <= x <= SPAN[1]]


def last_obs(sid: str, d: str) -> str:
    rows = [r for r in get(VINTAGE.format(sid=sid, d=d)).strip().splitlines()[1:] if r]
    return rows[-1].split(",")[0]


def releases(sid: str, log=print) -> list[dict]:
    out, prev = [], ""
    for d in vintages(sid):
        obs = last_obs(sid, d)
        if obs > prev:
            out.append({"date": d, "adds": obs})
            prev = obs
        else:
            log(f"{sid} {d}: adds no new month (last {obs}), dropped")
        time.sleep(0.2)
    return out


def main() -> int:
    res = {"source": "ALFRED, St. Louis Fed", "time_ny": "08:30",
           "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for name, sid in SERIES.items():
        res[name] = releases(sid)
        print(name, len(res[name]), res[name][0], res[name][-1])
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    return 0


def load(name: str, path: str = OUT) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [r["date"] for r in json.load(fh)[name]]


if __name__ == "__main__":
    raise SystemExit(main())
