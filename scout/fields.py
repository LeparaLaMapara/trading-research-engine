"""The fields the reading room reads, and what each one is read FOR.

Markets are studied under many names. A physicist calls a price a random walk with memory, an
economist calls it an equilibrium with frictions, a statistician calls it a noisy nonstationary
series. The reading room reads all of them because the useful idea is often a concept from one
field that nobody has tried in another.

Each field has:
  arxiv   - arXiv categories, each with an optional keyword filter. Broad categories (cs.LG,
            math.PR, cond-mat.stat-mech) get themed filters, or a week of them would be a few
            hundred papers about protein folding.
  openalex - search phrases for OpenAlex, which indexes journals, SSRN and NBER working papers
            that never reach arXiv (most of economics and finance).
  bridge  - the question a reader asks of a paper from this field. It is what makes a physics
            paper worth reading for a trading engine.
"""
from __future__ import annotations

FIELDS: list[dict] = [
    {
        "name": "quantitative finance",
        "arxiv": [("q-fin.TR", None), ("q-fin.ST", None), ("q-fin.PM", None),
                  ("q-fin.CP", None), ("q-fin.RM", None), ("q-fin.MF", None),
                  ("q-fin.GN", None), ("q-fin.PR", None)],
        "openalex": ["currency returns predictability", "cryptocurrency return predictability",
                     "time series momentum", "carry trade returns",
                     "transaction costs trading strategy"],
        "bridge": "What market effect is claimed, how big is it after realistic costs, and "
                  "could it exist in daily FX, metals or crypto CFDs?",
    },
    {
        "name": "economics",
        "arxiv": [("econ.EM", None), ("econ.GN", None), ("econ.TH", None), ("q-fin.EC", None)],
        "openalex": ["exchange rate forecasting", "uncovered interest parity deviations",
                     "limits to arbitrage", "central bank announcement effects exchange rates",
                     "order flow exchange rates"],
        "bridge": "What economic mechanism would make prices predictable, who is on the other "
                  "side of the trade, and why has it not been arbitraged away?",
    },
    {
        "name": "statistics",
        "arxiv": [("stat.ME", "time series OR forecasting OR change point OR multiple testing"),
                  ("stat.ML", "time series OR forecasting OR financial OR nonstationary"),
                  ("stat.AP", "financial OR market OR price"),
                  ("stat.CO", "time series OR sequential")],
        "openalex": ["false discovery rate backtest", "change point detection financial",
                     "forecast evaluation predictive accuracy"],
        "bridge": "Does this give a better way to detect a real effect, avoid fooling ourselves, "
                  "or estimate something we currently estimate badly (volatility, regimes, "
                  "costs)?",
    },
    {
        "name": "mathematics",
        "arxiv": [("math.PR", "rough paths OR Hawkes OR Levy OR martingale OR fractional"),
                  ("math.OC", "portfolio OR optimal execution OR stochastic control OR "
                              "trading"),
                  ("math.ST", "time series OR dependence OR heavy tail"),
                  ("math.DS", "time series OR prediction OR chaos")],
        "openalex": ["optimal stopping trading", "rough volatility",
                     "stochastic control optimal execution"],
        "bridge": "Is there a result here (a stopping rule, a control policy, a property of a "
                  "process) whose conditions plausibly hold for daily prices, and what would "
                  "it predict?",
    },
    {
        "name": "physics",
        "arxiv": [("physics.soc-ph", "market OR financial OR price OR economic"),
                  ("cond-mat.stat-mech", "power law OR criticality OR phase transition OR "
                                         "anomalous diffusion OR fluctuation"),
                  ("physics.data-an", "time series OR forecasting OR entropy OR "
                                      "nonstationary"),
                  ("nlin.AO", "synchronization OR collective OR critical transition"),
                  ("nlin.CD", "time series OR prediction OR reservoir")],
        "openalex": ["econophysics", "early warning signals critical transitions",
                     "agent-based model financial market", "Hawkes process financial"],
        "bridge": "Which physical concept (criticality, diffusion, synchronization, entropy, "
                  "early-warning signals) maps onto markets, what is the market-side analogue "
                  "of each variable, and what testable prediction does the analogy make?",
    },
    {
        "name": "computer science",
        "arxiv": [("cs.LG", "financial OR stock OR forex OR cryptocurrency OR trading"),
                  ("cs.GT", "market OR trading OR auction OR market maker"),
                  ("cs.MA", "market OR trading OR agent-based"),
                  ("cs.CE", "financial OR trading OR portfolio")],
        "openalex": ["reinforcement learning trading evaluation",
                     "machine learning return prediction out-of-sample"],
        "bridge": "Is the evaluation honest (out-of-sample, after costs, against a naive "
                  "baseline), and is there a cheap version our 85-dollar daily-bar account "
                  "could actually run?",
    },
    {
        "name": "mathematical and computational economics",
        "arxiv": [("q-fin.EC", None), ("cs.GT", "equilibrium OR mechanism OR price formation")],
        "openalex": ["computational economics market microstructure simulation",
                     "heterogeneous agent asset pricing model", "adaptive markets hypothesis"],
        "bridge": "What does the model say about when predictability appears and disappears, "
                  "and can that condition be observed in data we can get?",
    },
]

# Older, well-cited work. One theme per week in rotation, so over a quarter the engine reads the
# foundations each field is built on, not only this week's preprints.
CLASSIC_THEMES: list[str] = [
    "time series momentum", "currency carry trade", "volatility clustering",
    "market microstructure price impact", "backtest overfitting", "econophysics scaling",
    "regime switching asset returns", "limits to arbitrage", "Hawkes process order flow",
    "predictability of exchange rates", "cryptocurrency factor", "critical transitions",
    "optimal execution",
]


def arxiv_queries() -> list[tuple[str, str, str | None]]:
    """(field name, category, keyword filter) for every arXiv query, de-duplicated."""
    seen: set[tuple[str, str | None]] = set()
    out: list[tuple[str, str, str | None]] = []
    for f in FIELDS:
        for cat, kw in f["arxiv"]:
            if (cat, kw) in seen:
                continue
            seen.add((cat, kw))
            out.append((f["name"], cat, kw))
    return out


def bridge_for(field_name: str) -> str:
    for f in FIELDS:
        if f["name"] == field_name:
            return f["bridge"]
    return FIELDS[0]["bridge"]


#: Journals and working-paper series whose papers get extra weight: the top finance and
#: economics outlets, where results are refereed hard and most often replicated. By ISSN, so
#: OpenAlex can filter on them.
TOP_VENUES: dict[str, str] = {
    "0022-1082": "Journal of Finance",
    "0893-9454": "Review of Financial Studies",
    "0304-405X": "Journal of Financial Economics",
    "0022-1090": "Journal of Financial and Quantitative Analysis",
    "1572-3097": "Review of Finance",
    "0025-1909": "Management Science",
    "0012-9682": "Econometrica",
    "0002-8282": "American Economic Review",
    "0033-5533": "Quarterly Journal of Economics",
    "0034-6527": "Review of Economic Studies",
    "0022-3808": "Journal of Political Economy",
    "0304-4076": "Journal of Econometrics",
    "0304-3932": "Journal of Monetary Economics",
    "0022-1996": "Journal of International Economics",
    "0261-5606": "Journal of International Money and Finance",
    "1469-7688": "Quantitative Finance",
    "0898-2937": "NBER Working Paper Series",
}

#: What the top-venue harvest looks for: markets this engine can trade, and the effects the
#: literature documents for them.
TOP_VENUE_QUERY = ('currency OR "exchange rate" OR carry OR momentum OR trend OR volatility OR '
                   'cryptocurrency OR bitcoin OR commodity OR gold OR "transaction costs" OR '
                   '"return predictability" OR "risk premium" OR liquidity OR positioning')


def is_top_venue(paper: dict) -> bool:
    return any(i in TOP_VENUES for i in paper.get("issn") or [])
