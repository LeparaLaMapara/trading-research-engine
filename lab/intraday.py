"""E01: intraday momentum, flat before the overnight rollover.

The rule is fixed by docs/programme/E01-intraday-momentum-prereg.md. Everything here is a pure
function of hourly bars so the schedule, the no-rollover guarantee and the absence of lookahead
can each be tested on their own.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MORNING_START_H = 23      # open of the 23:00 bar on day d-1
ENTRY_H = 12              # open of the 12:00 bar on day d
EXIT_H = 20               # open of the 20:00 bar on day d
ROLLOVER_HOURS = (20, 21, 22)   # bars starting here must carry no position
VOL_WINDOW, MIN_HISTORY = 60, 20


def day_table(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day: morning return, entry and exit prices.

    `bars` has ts_utc (seconds, bar OPEN time) and open. Days missing any of the three bars
    are dropped, as the pre-registration says.
    """
    t = pd.to_datetime(bars["ts_utc"], unit="s", utc=True)
    px = pd.Series(bars["open"].to_numpy(), index=t)
    hour = px.index.hour
    entry = px[hour == ENTRY_H]
    entry.index = entry.index.normalize()
    exit_ = px[hour == EXIT_H]
    exit_.index = exit_.index.normalize()
    # The 23:00 bar belongs to the NEXT day's morning.
    start = px[hour == MORNING_START_H]
    start.index = start.index.normalize() + pd.Timedelta(days=1)
    d = pd.concat({"start": start, "entry": entry, "exit": exit_}, axis=1).dropna()
    d = d[~d.index.duplicated()]
    d["morning"] = d["entry"] / d["start"] - 1.0
    d["afternoon"] = d["exit"] / d["entry"] - 1.0
    return d


def positions(days: pd.DataFrame) -> pd.Series:
    """The signal: sign of the morning return. Known at ENTRY_H, before the afternoon."""
    return np.sign(days["morning"])


def weights(days: pd.DataFrame) -> pd.Series:
    """Inverse trailing volatility of the afternoon return, PRIOR days only."""
    vol = days["afternoon"].rolling(VOL_WINDOW, min_periods=MIN_HISTORY).std().shift(1)
    return 1.0 / vol


def instrument_returns(days: pd.DataFrame, pos: pd.Series, cost_rt: float) -> pd.DataFrame:
    """Per-day gross and net return of one instrument, unweighted.

    One round trip on every day with a non-zero position: in at ENTRY_H, out at EXIT_H.
    """
    traded = pos != 0
    gross = pos * days["afternoon"]
    net = gross - np.where(traded, cost_rt, 0.0)
    return pd.DataFrame({"gross": gross, "net": net, "w": weights(days), "traded": traded})


def hourly_position_path(days: pd.DataFrame, pos: pd.Series) -> pd.Series:
    """The position held in each hourly bar, reconstructed from the schedule. Used only to
    PROVE the rule is flat across the rollover: it is the thing the test asserts on."""
    out = {}
    for d, p in pos.items():
        if p == 0:
            continue
        for h in range(ENTRY_H, EXIT_H):            # held in bars 12:00 .. 19:00
            out[d + pd.Timedelta(hours=h)] = p
    return pd.Series(out, dtype=float)


def assert_flat_at_rollover(path: pd.Series) -> None:
    if path.empty:
        return
    bad = path[path.index.hour.isin(ROLLOVER_HOURS) & (path != 0)]
    if len(bad):
        raise AssertionError(f"position open across the rollover at {bad.index[0]}")


def portfolio(per_inst: dict[str, pd.DataFrame], col: str = "net") -> pd.Series:
    """Equal-risk average across the instruments that traded each day."""
    frames = []
    for sym, df in per_inst.items():
        ok = df["traded"] & df["w"].notna() & np.isfinite(df["w"])
        frames.append((df.loc[ok, col] * df.loc[ok, "w"]).rename(sym))
    if not frames:
        return pd.Series(dtype=float)
    wide = pd.concat(frames, axis=1)
    # Divide by the day's total weight: an inverse-volatility weighted mean across the
    # instruments that traded, whatever the absolute weight level.
    wsum = pd.concat([per_inst[s]["w"].where(per_inst[s]["traded"]).rename(s)
                      for s in per_inst], axis=1).reindex(wide.index)
    return (wide.sum(axis=1) / wsum.sum(axis=1)).dropna()


def ann_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 3 or r.std() == 0:
        return 0.0
    years = (r.index[-1] - r.index[0]).days / 365.25
    per_year = len(r) / years if years > 0 else 252
    return float(r.mean() / r.std() * np.sqrt(per_year))
