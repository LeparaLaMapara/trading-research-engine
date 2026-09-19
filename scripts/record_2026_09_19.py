"""Record the 2026-09-19 research programme as durable episodes (research/episodes.py)."""
from __future__ import annotations

import json

from research import episodes as E

Z = json.load(open("docs/results/zoo-2026-09-19.json"))
F = json.load(open("docs/results/zoo-followup-2026-09-19.json"))
C = json.load(open("docs/results/carry-2026-09-19.json"))
L = json.load(open("docs/results/long-history-2026-09-19.json"))
code = E.code_commit()

def rec(q, verdict, **kw):
    i = E.record("2026-09-19", q, verdict, **kw)
    print(i, verdict, q[:70])

rec("Does any of 22 forecasting methods (baselines, 5 rules, 10 learned, 3 ensembles) earn a "
    "portfolio Sharpe on a 64-instrument daily CFD universe that survives deflation?",
    "FALSIFIED", claim="complexity or pooling finds an edge after honest costs",
    prior="about 20% that something passes DSR 0.95",
    source="docs/results/zoo-preregistration-2026-09-19.md",
    experiment="scripts/train_zoo.py, walk forward 2017-2024, measured broker financing",
    data=Z["data_hash"], evidence={"champion": Z["champion"], "champion_dev": Z["champion_dev"],
                                    "champion_dsr": Z["champion_dsr"], "N": Z["N"],
                                    "holdout": Z["holdout"]},
    belief_update="No candidate beats holding everything long at equal risk (dev 0.46, "
                  "holdout 1.05). The dev champion GRU (0.19) is 80% long bias; its holdout "
                  "0.96 is below long_risk_parity's 1.05.",
    revisit_if="a venue with materially lower holding costs, or new non-price data",
    next_question="Is the binding constraint the model or the venue's costs?")

rec("Is the pooled ML gross signal real skill or disguised long exposure?", "UNDERPOWERED",
    experiment="demeaned forecasts per date, residual vs long_risk_parity",
    evidence={"gru_corr_to_long": 0.80, "gru_resid_gross": 0.05, "xgb_demeaned_gross": 0.73,
              "xgb_demeaned_net": -0.21},
    belief_update="GRU: long bias. XGBoost: a relative cross-sectional signal of about 0.7 "
                  "gross exists but is not separable from luck net of costs.",
    next_question="Does a slower relative version survive costs?")

rec("Does slowing the relative ML signal (EWMA 10/30) make it survive costs?", "UNDERPOWERED",
    source="docs/results/zoo-followup-preregistration-2026-09-19.md",
    evidence={"best": F["table"][0]["model"], "dev": F["table"][0]["dev_sharpe"],
              "dsr": F["table"][0]["dsr"], "ci": F["table"][0]["ci"]},
    belief_update="Turnover fell from 87 to 10 a year and net rose from -0.22 to +0.10, but "
                  "financing (not spread) is now what eats the signal.",
    revisit_if="lower financing venue; longer history for the ML panel")

rec("Does FX carry (point-in-time OECD 3m rates) earn money net of costs, 2017-2024?",
    "FALSIFIED", source="docs/results/carry-preregistration-2026-09-19.md",
    evidence={r["model"]: {"net": r["dev_sharpe"], "price_only": r["price_only_sharpe"]}
              for r in C["table"]},
    belief_update="Interest earned (+0.58 Sharpe) is offset almost exactly by high-yielders' "
                  "depreciation (-0.58): uncovered interest parity held in this window.",
    revisit_if="a longer window including 2003-2008, where the carry literature's returns sit")

rec("Is trend following dead on these instruments, or was 2017-2024 a bad window?",
    "FALSIFIED", source="docs/results/long-history-preregistration-2026-09-19.md",
    experiment="Dukascopy 37 instruments 2004-2024, same costs",
    evidence={r["model"]: {"net": r["net"], "gross": r["gross"], "periods": r["periods"]}
              for r in L["table"]},
    belief_update="Negative in every era net of costs; gross only 0.1 to 0.3. The published "
                  "trend premium lives largely in bond, rate and agricultural futures this "
                  "broker does not offer as continuous CFDs.",
    revisit_if="access to bond/rate/ag futures, or continuous series built from the broker's "
               "dated bond futures (UST10Y_*, EURBND_*)")

rec("What is the binding constraint on multi-day strategies at this broker?", "SURVIVED",
    claim="overnight financing, not spread and not model choice",
    experiment="cost decomposition; zoo.financing splits broker swaps into fee and differential",
    evidence={"financing_sharpe_units_portfolio": [0.39, 0.47], "trading_cost_units": [0.05, 0.09],
              "measured_fee_annual": {"fx": "0.6-2%", "metal": "0.8%", "major_index": "4.4%",
                                      "crypto": "10% (longs 20%, shorts 0%)", "energy": "6%+"}},
    belief_update="Holding a diversified CFD book costs 0.4 to 0.6 Sharpe a year at this broker. "
                  "Diversification makes it worse, because returns partly cancel and fees add.",
    next_question="Which venue gives the same exposures without the holding fee (exchange "
                  "futures, VALR perps with funding) and what are their measured costs?")
