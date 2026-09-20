# Short horizon precursor signals: literature review

Written 2026-09-20. Web research only. No code in this repository was changed to produce it.

## Why this review exists

We are deciding whether to spend compute on short horizon precursor signals. The decision is
constrained by measured facts about our own setup, not by what is theoretically real:

| Constraint | Measured or known value |
|---|---|
| Order round trip, minimum | 369 ms |
| Order round trip, median | 949 ms |
| Order round trip, 99th percentile | 3.5 s |
| Colocation | none |
| Market data held | broker top of book spot events (361k rows, microsecond receive stamps) |
| Depth feed | none collected |
| Trade prints | none |
| Funding history | none |
| Capital | about R2,000 (roughly USD 110) |
| VALR perpetual futures fees | 0.04% taker, 0.00% maker (unverified against the live fee page) |

A round trip of taker to taker on VALR perps costs about **8 basis points** before spread. Every
effect size below should be read against that number. An edge of 0.5 bp is not a small edge for
us, it is a negative edge.

A note on confidence. Where I read the paper's own text (HTML or ar5iv) I mark the row
**[full text]**. Where the number comes only from an abstract, a publisher landing page or a
search result summary, I mark it **[secondhand]** and it must be verified before anyone acts on
it. Several publisher sites (ScienceDirect, SSRN, ResearchGate, Taylor and Francis) refused
automated access, so some important papers are secondhand here.

---

## 1. Order flow imbalance and trade sign imbalance

| Source | Market and period | Method | Effect size | Horizon | Limitations and flags |
|---|---|---|---|---|---|
| Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47-88. [arXiv:1011.6402](https://arxiv.org/abs/1011.6402) / [ar5iv](https://ar5iv.labs.arxiv.org/html/1011.6402) **[full text]** | 50 S&P 500 stocks, NYSE TAQ, April 2010 | OLS of mid price change in ticks on order flow imbalance, `dP = beta * OFI + eps`, beta re-estimated per half hour | Cross sectional average **R-squared 65%**, range **44% to 79%**. Price impact coefficient `beta = c / AD^lambda` with **lambda approx 0.98**, **c approx 0.45** | **10 second** intervals, stable across scales | **This is a contemporaneous decomposition, not a forecast.** The 65% is OFI explaining the price change happening in the same window. It says price moves *are* order flow, not that order flow *precedes* price. Level 1 data only, hidden orders missed. Three wide spread stocks fit badly. This paper is routinely miscited as a prediction result. |
| Cont, R., Cucuringu, M., Zhang, C. (2023). "Cross-impact of order flow imbalance in equity markets." *Quantitative Finance* 23(10), 1373-1393. [arXiv:2112.13213](https://arxiv.org/abs/2112.13213) **[secondhand]** | US equities, multi asset panel | PCA over OFI at multiple book levels to build an "integrated OFI"; sparse vs cross impact models | Integrated multi level OFI beats best level OFI in and out of sample. Cross impact adds **nothing** to contemporaneous explanation once multi level OFI is used. Lagged cross asset OFI **does** improve forecasts | Forecast gain is at **short horizons and decays rapidly** | Exact R-squared numbers not verified. The honest reading: the only genuinely predictive part is small and short lived, and it needs multi level depth across many assets, which we do not have. |
| Anonymous / "Generalized Order Flow Imbalance" [arXiv:2112.02947](https://arxiv.org/abs/2112.02947) **[secondhand]** | US equities | log-GOFI transform of OFI | OFI out of sample R-squared **32.89% / 38.13% / 42.57%** at 30 s / 1 min / 5 min; log-GOFI **83.57% / 85.37% / 86.01%** | 30 s to 5 min | **Flag hard.** An 86% R-squared on returns is not a forecasting result in any tradeable sense. It is almost certainly contemporaneous and possibly mechanically related to the target through the transform. Treat as a decomposition, not alpha. |
| "An Empirical Analysis on Financial Markets: Insights from the Application of Statistical Physics" [arXiv:2308.14235](https://ar5iv.labs.arxiv.org/html/2308.14235) **[full text]** | Coinbase BTC/USD, **one hour**, 15:00-16:00 on 2022-11-28, 3,600 one second points | Regression of price change on OFI, VPIN, momentum change | OFI **R-squared 0.094 at 1 s**, **0.019 at 10 s** (F = 373.0 and 70.87). Momentum change R-squared 0.168 at 1 s and **0.816** at 10 s | 1 s and 10 s | **One hour of one instrument on one day.** This is an anecdote with p values attached. The 0.816 momentum figure is a red flag for overlapping or mechanically autocorrelated construction. The useful takeaway is only directional: crypto OFI R-squared is an order of magnitude below the equity contemporaneous figure, and it falls sharply from 1 s to 10 s. |
| Anastasopoulos, A., Gradojevic, N., Liu, F., Maynard, A., Tsiakas, I. "Order flow and cryptocurrency returns." *Journal of International Financial Markets, Institutions and Money* (2026). [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1386418126000029), [working paper PDF](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2025-Greece/papers/OrderFlowpaper.pdf) **[secondhand]** | Cross section of cryptocurrencies | Weekly portfolio sorts on order flow | Long short spread **1.83% per week**, **t = 2.82**, annualised **Sharpe 1.93** | **Weekly** | Publisher blocked automated access, numbers unverified. A weekly horizon is completely insensitive to our latency. But "order flow" here means signed trade volume, which we do not have. |
| Saluja, N., Sreenu, N., Srivastava, S., Srivastava, S. (2026). "Order Flow and Cryptocurrency Returns: A Machine Learning Approach with Out-of-Sample Validation." [SSRN 7055779](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7055779) **[secondhand]** | Cryptocurrencies, daily | Nonlinear ML on daily order flow | Alpha up to **0.86% per day**, annualised **Sharpe 3.97**; a related figure of Sharpe 3.52 with break even cost 0.48% per day is cited | **Daily** | **Would not survive out of sample in my judgement.** A Sharpe near 4 from a cross sectional crypto ML sort, in a 2026 working paper, with no replication, is the classic profile of a result that shrinks by more than half on a fresh sample. Flagged as not to be built on. |

**What section 1 actually establishes.** OFI explains contemporaneous price change very well in
equities and much less well in crypto. The *predictive* component is real but small, short lived
and requires depth or trade prints. Nothing here gives a retail operator with top of book quotes
a forecast.

---

## 2. Limit order book imbalance, queue imbalance, liquidity withdrawal

| Source | Market and period | Method | Effect size | Horizon | Limitations and flags |
|---|---|---|---|---|---|
| Gould, M.D., Bonart, J. (2016). "Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book." *Market Microstructure and Liquidity* 2(2). [arXiv:1512.03492](https://arxiv.org/abs/1512.03492) **[full text of abstract and summary]** | 10 liquid Nasdaq stocks | Logistic and local logistic regression of next mid price move direction on level 1 queue imbalance | Strongly significant in every stock. **Considerable** classification improvement over the null for large tick stocks, **moderate** for small tick stocks | **The next one mid price change.** Related work finds power over roughly the next **2 mid price changes**, decaying to near zero after | No transaction cost or tradeability analysis at all. The signal lives for one or two book events, which on a liquid instrument is milliseconds. **This is the canonical result that does not survive our latency.** |
| Albers, J., Cucuringu, M., Howison, S., Shestopaloff, A.Y. "Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets." [arXiv:2108.09750](https://arxiv.org/abs/2108.09750) **[full text]** | 14 Bitcoin markets across 8 exchanges (Binance, Huobi, Okex, FTX, Deribit, Bybit, Bitmex, Kraken), perpetual swaps, quarterly futures, one spot market, **February 2021**, 50 ms snapshots | Book imbalance, trade flow imbalance, past returns and cross venue mean divergence, nonlinear transforms, linear models per venue pair | Models explain **10% to 37%** of variation in future returns depending on target venue. Binance USDT perpetual is the strongest single predictor, about **26% R-squared** when predicting FTX | **500 ms and 1000 ms ahead** | The strongest genuinely predictive result in this review, and it is at 1 second. But it uses full order book snapshots across 8 venues. Authors state maker strategy backtesting was **infeasible** and live validation covered only one venue. Snapshots, not order by order. One month, and FTX no longer exists. |
| Wang, H. (2025). "Exploring Microstructural Dynamics in Cryptocurrency Limit Order Books: Better Inputs Matter More Than Stacking Another Hidden Layer." [arXiv:2506.05764](https://arxiv.org/html/2506.05764v2) **[full text]** | Bybit BTC/USDT spot, **a single day**, 2025-01-30, 100 ms snapshots, top 200 levels | Logistic regression, XGBoost, CatBoost, CNN hybrids, DeepLOB; Savitzky-Golay and Kalman filtering | Binary direction accuracy best **0.728** at 500 ms with 40 book levels and SG smoothing; **0.58** with only 5 levels; worst case 0.522 | 100 ms, 500 ms, **1000 ms** | **The depth dependence is the finding that matters to us: 40 levels gives 71.5% accuracy, 5 levels gives 58%.** Top of book alone would be worse still. One day of one pair. **No transaction cost simulation whatsoever.** Author notes inference latency alone can erase the alpha. |
| Anantha, A.N., Jain, S., Maiti, P. (2025). "Order Book Filtration and Directional Signal Extraction at High Frequency." [arXiv:2507.22712](https://arxiv.org/html/2507.22712v1) **[full text]** | NSE BANKNIFTY index futures, 3 days in January 2021, top 5 levels, millisecond | Filtration schemes by order lifetime and modification, scored by Pearson correlation, regime R-squared and Hawkes excitation | Best filter raises OBI-return Pearson correlation from **0.01018 to 0.01133** | Contemporaneous 10 s windows, 1 s forecast window | **Included as a cautionary example.** A correlation of 0.011 is indistinguishable from nothing for trading purposes, yet the paper reports an "11.3% improvement". Percentage improvements on near zero baselines are how weak microstructure results get dressed up. No cost or latency analysis. |
| Liquidity withdrawal before trades: findings summarised across the LOB cancellation literature, including Dahlström et al. (2024), "The determinants of limit order cancellations," *Financial Review*. [Wiley](https://onlinelibrary.wiley.com/doi/10.1111/fire.12363) **[secondhand]** | US equities | Event study of net order flow around market order arrivals | Same side best quote net order flow is **negative from at least 10 seconds before** an incoming market order, consistent with adverse selection avoidance. About **14 cancellations per trade** at the NBBO in 2020 | **10 s lead**, which is slower than our latency | This is the one book based precursor with a lead time we could actually act on. But it requires observing cancellations, which needs a full depth feed with order level detail. Broker top of book cannot see it. Also documented in equities, not crypto or CFD. |

**What section 2 actually establishes.** Book imbalance predicts, but its predictive life is one
to two book events unless you aggregate many levels or many venues. Depth is not optional: the
single cleanest number in this section is 71.5% accuracy with 40 levels against 58% with 5.
Liquidity withdrawal has a genuinely slow 10 second signature, but only visible with order level
depth.

---

## 3. Cross exchange and cross market lead lag in crypto

| Source | Market and period | Method | Measured lead | Limitations and flags |
|---|---|---|---|---|
| Albers et al., [arXiv:2108.09750](https://arxiv.org/abs/2108.09750) **[full text]** | 8 Bitcoin exchanges, Feb 2021, 50 ms | Cross venue predictive regression | **Binance and Huobi are consistent price leaders.** Predictive power over the following **500 to 1000 ms**, up to 26-37% R-squared for the lagging venue | The lead is expressed as predictive R-squared at a 0.5 to 1 s horizon rather than a single lead time in ms. That framing is actually more useful to us than a lead time. |
| Plazuelo Pascual, J., Tardon Rubio, C., Toro Cebada, J., Hernando Veciana, A. (2025). "Price Discovery in Cryptocurrency Markets." [arXiv:2506.08718](https://arxiv.org/abs/2506.08718) **[full text, partial]** | ETH on Binance vs Uniswap v2; BTC spot vs CME futures; September 2023 to September 2024 | Hasbrouck information share, Gonzalo-Granger permanent-transitory, Hayashi-Yoshida lead lag on asynchronous ticks | **Centralised markets generally lead** for ETH. For BTC, futures tend to lead spot, with mixed results in high volatility | Numeric information shares and lead times were not extractable from the accessible sections. Direction is established, magnitude is not. |
| "Price discovery in cryptocurrency markets: sub-second evidence." *Economics Letters* (2026). [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S016517652600220X) **[secondhand, paywalled]** | Binance, sub-second | Analysis of 10 consecutive 100 ms bins within each second | Systematic sub-second patterns in trading activity and price discovery; **the first 100 ms contributes to permanent price change** | Could not access. Whatever it establishes lives entirely inside our 369 ms floor. Noted so we know it exists and can stop wondering. |
| Makarov, I., Schoar, A. (2020). "Trading and arbitrage in cryptocurrency markets." *Journal of Financial Economics* 135(2), 293-319. [LSE PDF](https://personal.lse.ac.uk/makarov1/index_files/CryptocurrencyMarkets.pdf) **[secondhand]** | 34 exchanges, 19 countries, 2017-2018 | Arbitrage index from minutewise cross exchange VWAP | Large recurrent arbitrage spreads **persist for days and weeks**, and are far larger **across countries** than within them; capital controls are the binding constraint | Directly relevant to a South African operator. The persistent cross country deviations are a capital mobility story, not a latency story. We cannot exploit them at R2,000 with exchange control in the way. |
| Unattributed figures circulating in search results ("Coinbase leads Gemini by 0.2 s", "Kraken leads OKEx by 6.4 s", "Hyperliquid fills lag by approx 700 ms") **[unverified, no primary source found]** | | | | **Do not use.** I could not trace these to a paper. Recorded only so nobody rediscovers them and treats them as established. |
| [pietrobicocchi/crypto-leadlag-network](https://github.com/pietrobicocchi/crypto-leadlag-network) **[full text]** | Intended: Binance USD-M perps aggTrades, 30-40 symbols, 3-6 months | Hayashi-Yoshida | **No results. The README states "repository skeleton, nothing implemented yet."** | Listed because it appears high in searches and looks like evidence. It is not. Its stated design point is worth borrowing though: an illiquid asset appears to lag purely because its returns arrive late, which is the main trap in any lead lag estimate we run. |

**What section 3 actually establishes.** Binance leads. The lead is measurable at the 500 ms to
1 s scale and is large enough in R-squared terms (10-37%) to be interesting at our latency. That
is the single most encouraging finding in this review. Cross country deviations persist for weeks
but are gated by capital controls, which is our situation exactly.

---

## 4. Perpetual futures: funding, basis, open interest, liquidation cascades

| Source | Market and period | Method | Effect size | Horizon | Limitations and flags |
|---|---|---|---|---|---|
| Schmeling, M., Schrimpf, A., Todorov, K. (2023). "Crypto carry." BIS Working Paper 1087. [BIS PDF](https://www.bis.org/publ/work1087.pdf) **[full text of abstract sections]** | BTC and ETH futures and perpetuals across crypto native venues | Carry decomposition, crash risk analysis | Crypto carry averages **above 10% annualised** and reaches **60%**, far above equities, bonds, FX and commodities. **High carry predicts future price crashes** | Weeks to months; crash prediction at a multi day horizon | Sharpe ratios not reported in the accessible text. Authors note arbitrage capital faces margin spikes and liquidations during drawdowns, which is precisely the risk that kills a R2,000 account. The carry is compensation for crash risk, not free money. |
| Garcia Seuma, R.M. (2026). "Where does the criticality live? Early-warning signals are event-heterogeneous across seven crypto-perpetual liquidation cascades." [arXiv:2607.27070](https://arxiv.org/html/2607.27070) **[full text]** | Binance BTCUSDT USD-margined perpetual, seven cascades 2022-2025 including the 19bn USD event of 2025-10-10; 1 min price, 5 min leverage and order flow | Rolling variance and lag-1 autocorrelation on detrended residuals, Kendall tau over 39 configuration sweeps per variable per event, placebo against 300 ordinary windows | **No single variable consistently precedes cascades.** Price shows critical slowing down in 5 of 7 events but is silent in the two exogenous news shocks. Only robust pattern: compression of taker order flow variance, **Fisher combined p approx 5e-6**, but population level only. Placebo: only **4 of 6** real cascades below the 5th percentile | Minutes to hours before the event | **The authors explicitly state these findings are "not tradeable."** Single venue, leverage variables are proxies for an unobservable liquidation state, only six usable events. This is the most honest paper in the review and its answer is no. |
| Kim, C., Hansen, P.R. (2026). "The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures." [arXiv:2607.09426](https://arxiv.org/html/2607.09426v2) **[full text]** | Binance USDT perps, BTC ETH XRP SOL DOGE ADA, 2021-01-01 to 2024-10-31, ms trades aggregated to 10 s and 1 min | Predict the 10 s return opening each quarter hour from 12 quarter-hour-spaced lags plus technical indicators | **Out of sample R-squared 3.37%** mean, range **1.60% (SOL) to 5.85% (ADA)**. Direction **AUC 0.6011**. Economic magnitude **approx 0.5 bp** | 10 s window at each quarter hour boundary; order imbalance has a separate **4 to 12 hour** predictive component | Predictors are fixed **at least 15 minutes before** the boundary, so **no low latency infrastructure is required.** But the authors are blunt: 0.5 bp is "roughly one tenth of a single standard-tier taker fee" (Binance taker 5.0 bp). They recommend it for execution timing and liquidity provision, **not as a standalone strategy.** |
| Bieganowski, B., Slepaczuk, R. (2026). "Explainable Patterns in Cryptocurrency Microstructure." [arXiv:2602.00776](https://arxiv.org/html/2602.00776v1) **[full text]** | Binance Futures perps, BTC LTC ETC ENJ ROSE, 2022-01-01 to 2025-10-12, **1 second resolution** | CatBoost with GMADL directional loss, walk forward with purging, SHAP, pessimistic inventory marking | Taker strategy information ratios: **ETC 8.97, ENJ 6.58, ROSE 5.28, BTC 0.25, LTC 0.07**. Maker strategy mostly negative. Significant at 5% only on ETC, ENJ, ROSE | **3 second** log return of mid price | **Latency is explicitly "not modeled"; results are an "upper bound in the fastest regime."** At our 949 ms median round trip we would lose about a third of a 3 second horizon before the order lands. The huge IRs are on illiquid mid and long tail coins, and the authors flag that the 2025-10-10 flash crash drives outsized returns, especially ROSE. Top of book features plus OFI plus VWAP deviation, so it needs trade prints. **Treat the 8.97 IR as non-replicable at our latency.** |
| Funding rate practitioner claims (extreme funding above 0.10% per 8h precedes corrections; 95th percentile approx 0.12% for BTC) **[secondhand, practitioner sources only]** | | | | No peer reviewed source found with a clean effect size for funding predicting returns at the hours horizon. The academic funding literature is mostly pricing theory (Ackerer, Hugonnier, Jermann NBER w32936; He et al.) rather than return prediction. **This is a genuine gap in the literature, which means it is also an untested hypothesis rather than a known edge.** A related study found only **40% of top funding arbitrage opportunities generate positive returns after transaction costs**. |

**What section 4 actually establishes.** The multi hour and multi day precursors (carry, funding
extremes) are the ones our latency cannot hurt, and they are also the ones the literature
establishes least well for return prediction. Liquidation cascade early warning is explicitly
reported as not tradeable by the only paper that tested it properly.

---

## 5. Decay after costs and after latency

This is the section that decides the question.

| Source | Method | Finding | Why it matters to us |
|---|---|---|---|
| Kearns, M., Kulesza, A., Nevmyvaka, Y. (2010). "Empirical Limitations on High Frequency Trading Profitability." [arXiv:1007.2593](https://ar5iv.labs.arxiv.org/html/1007.2593) **[full text]** | Simulate an **omniscient** trader with perfect knowledge of future prices, using market orders only, across the entire US equity universe for 2008. Holding periods **0.01, 0.1, 0.5, 1, 2, 3, 4, 5 and 10 seconds** | Maximum achievable profit with **perfect foresight**: **21bn USD at 10 s, 760m USD at 1 s, 21m USD at 10 ms.** Less than 0.05% of the 52tn USD traded. Adding 1.2 cents per share of fees costs 2.3bn USD, **reducing profits by two thirds** | **The single most important result here.** It is an upper bound, not an estimate. Profit available collapses by a factor of roughly 28 going from a 10 s hold to a 1 s hold, and by another factor of 36 from 1 s to 10 ms. Read in reverse: **the available money grows with holding period.** Shortening our horizon to chase microstructure is moving toward the part of the curve where even perfect prediction earns almost nothing. |
| Byrd, D., Palaparthi, S., Hybinette, M., Balch, T.H. (2020). "The Importance of Low Latency to Order Book Imbalance Trading Strategies." [arXiv:2006.08682](https://arxiv.org/abs/2006.08682) **[full text of abstract and summary]** | Agent based interactive discrete event simulation, thousands of agents over thousands of simulated days, latency controlled directly | **Latency is inversely related to profit for OBI traders.** More importantly, **latency rank rather than absolute magnitude** determines how returns are allocated among agents running the same strategy | Devastating for us. On an OBI style signal the payoff depends on where we sit in the latency queue, not on whether 949 ms is "fast enough in absolute terms". We are last in that queue by several orders of magnitude. Simulation, not historical data, because trader identity and location are unobservable in real data. |
| Bieganowski and Slepaczuk (2026), above **[full text]** | 1 s crypto perps, 3 s horizon | Latency "not modeled", results are the "upper bound in the fastest regime"; maker strategies lost catastrophically during the Oct 2025 crash through adverse selection while taker strategies profited | The best looking crypto microstructure result in this review disclaims latency entirely. The maker/taker asymmetry during the crash is the adverse selection warning: our zero fee maker route on VALR is exactly the side that got destroyed. |
| Kim and Hansen (2026), above **[full text]** | Quarter hour effect, no latency requirement | 0.5 bp edge against a 5 bp taker fee | A clean worked example of a **real, replicable, latency insensitive** effect that is still not tradeable, because the effect size sits an order of magnitude below the cost floor. |
| Dean Markwick, "Order Flow Imbalance: A High Frequency Trading Signal" [blog](https://dm13450.github.io/2022/02/02/Order-Flow-Imbalance.html) **[secondhand, practitioner]** | Replication of OFI on real data | Concludes OFI signals are "not practical in reality" because transaction costs destroy the return profile, since the strategy wants to trade constantly and pays the full spread on every round trip | Not academic, but it is one of very few public attempts to actually trade the Cont-Kukanov-Stoikov signal, and it fails on costs. Worth noting that the failure mode is trade frequency, not signal absence. |

**What section 5 actually establishes.** Three independent lines of evidence say the same thing.
Kearns gives an upper bound that shrinks fast as the horizon shortens. Byrd shows that for book
imbalance strategies your rank in the latency queue, not your absolute speed, determines your
share. And the two best recent crypto results either disclaim latency modelling or report an
effect below the fee floor. **No study in this review reports a microstructure precursor that
remains profitable for a non colocated participant at second scale after costs.** The closest is
Albers et al.'s cross venue result at 500-1000 ms, and its authors could not backtest the maker
version and validated live on only one venue.

---

## 6. Replication status, in one paragraph

Cont-Kukanov-Stoikov is the only result here that has been replicated many times, and what
replicates is the *contemporaneous* decomposition, not a forecast. Queue imbalance one tick ahead
(Gould and Bonart) is well replicated and lives for one or two book events. The Kearns upper
bound has never been challenged and is structural rather than statistical, so it is the safest
thing in this document. Everything crypto specific here is from 2025 or 2026, unreplicated, and
mostly single venue, often single day. The two headline Sharpe figures (3.97 daily ML, 8.97
information ratio at 3 seconds) come from unreplicated 2026 working papers with either no latency
model or no verified full text, and both should be assumed to shrink by more than half out of
sample.

---

## What is worth our compute at 1 second latency

The literature's answer to the framing question is mostly no. The precursors that are strongest
(queue imbalance, OFI) live inside our latency floor. The precursors that survive our latency
(quarter hour effects, carry) are either below our cost floor or not established as return
predictors at all. The one genuinely encouraging result is cross venue lead lag, because Albers
et al. measure it at exactly our horizon rather than below it.

Below are five hypotheses, stated so they can be killed. They are ordered by expected information
per unit of compute, not by expected profit.

### H1. Binance leads VALR at a horizon we can trade

**Falsifiable statement.** Regressing the VALR BTC perpetual mid price return over the interval
`[t+1s, t+2s]` on the Binance BTC perpetual mid price return over `[t-1s, t]` yields a
coefficient significantly greater than zero with out of sample R-squared above 1%, measured on
locally timestamped data, and the implied per trade edge exceeds 8 bp round trip taker cost plus
the VALR half spread.

**Why.** Albers et al. report 10-37% R-squared predicting a lagging venue's 500-1000 ms forward
return, with Binance the consistent leader. VALR is a small venue and should lag more, not less.
The horizon is above our 369 ms floor and straddles our 949 ms median.

**Data needed.** Synchronised top of book from Binance and VALR, timestamped on our own clock, at
least 30 days, both websocket feeds, both free.

**Do we hold it.** **No.** We hold cTrader spot events only. Collection cost is near zero and this
is the cheapest high value data we are missing. The known trap (from the crypto-leadlag-network
README) is that an illiquid venue appears to lag purely because its quotes update late, so the
test must use quote *update* events and a Hayashi-Yoshida style estimator, not fixed bars.

**Kill condition.** If the R-squared at a 1 s lag is below the level that covers 8 bp plus spread,
kill the whole precursor programme. This is the best case in the literature.

### H2. Funding rate extremes predict multi hour returns net of cost

**Falsifiable statement.** On VALR BTC and ETH perpetuals, entering short when the realised 8 hour
funding rate is in its top decile, and flat otherwise, produces a positive mean return over the
following 8 to 24 hours that exceeds 8 bp round trip, with a t statistic above 2 over at least 200
funding periods.

**Why.** BIS crypto carry establishes that high carry predicts crashes, and carry averages above
10% annualised. The horizon is hours, so our latency is irrelevant. This is the only candidate
where a 949 ms round trip costs us literally nothing.

**Data needed.** VALR funding rate history, perpetual mid, spot mid, over at least one year.

**Do we hold it.** **No funding history.** VALR publishes funding, so this is a collection task,
not an access problem. Note that we will need to start collecting now and wait, because a
backfill may not be available.

**Flag.** The academic literature on funding as a *return predictor* is thin. BIS is about carry
and crash risk, not a tradeable timing rule. Treat this as our own hypothesis with weak prior
support, not as a replication.

### H3. The quarter hour effect is an execution timing rule, not a signal

**Falsifiable statement.** On our own executions, orders placed inside the 10 second window
opening each quarter hour experience measurably worse or better slippage than orders placed at
random times within the same hour, by at least 0.5 bp, over at least 200 orders.

**Why.** Kim and Hansen establish the effect with out of sample R-squared of 3.37% and no latency
requirement, and they state plainly that 0.5 bp is one tenth of a taker fee, so it is useless as
alpha. But it is not useless as a rule about *when not to send an order*. This is the correct
demotion of a real finding.

**Data needed.** Our own fill records with request and fill timestamps, plus the mid at request
time. Crypto perp mid history at 10 s resolution for the offline version.

**Do we hold it.** **Partially.** We have request timestamps and entry to fill deltas in
`scripts/probe.py` and the trade log, but not enough orders yet for 200 observations. We hold no
crypto quote history.

**Kill condition.** Fewer than 0.5 bp difference means drop it permanently rather than keep it as
a folk rule.

### H4. Level 1 queue imbalance on the broker feed predicts the 1 second ahead mid

**Falsifiable statement.** Level 1 queue imbalance, computed as `(bidSize - askSize) / (bidSize +
askSize)` from cTrader depth quotes on our most liquid instrument, predicts the sign of the mid
price change 1 second ahead with out of sample AUC above 0.55, and the implied edge exceeds the
measured round trip spread and commission.

**Why.** Gould and Bonart establish the relationship strongly in equities. Wang shows crypto book
imbalance at a 1 second horizon reaches 58% binary accuracy with only 5 levels.

**Data needed.** Bid and ask *sizes*, not just prices. **Important correction to our stated
position:** our "no depth feed" is a collection gap, not an access gap. The cTrader Open API
exposes `ProtoOASubscribeDepthQuotesReq` and `ProtoOADepthQuote`, which carries `id`, `size`,
`bid` and `ask`. IC Markets advertises DOM and per level volumes on cTrader. Our existing
`ProtoOASpotEvent` stream carries prices only, which is why we have 361k spot events and no book.
Turning on depth subscription is a small change to the telemetry logger.

**Do we hold it.** **No, but we can have it this week at no cost.**

**Flag, and it is a serious one.** A CFD broker's "book" is a synthetic aggregation of liquidity
provider quotes, not a real central limit order book with queue priority. The queue imbalance
mechanism that Gould and Bonart identify, adverse selection against a visible queue, may simply
not exist on this feed. Byrd's result also applies directly: on an OBI signal our payoff is set by
latency rank, and we are last. **Expected outcome is failure.** Its value is that it fails cheaply
and closes the question.

### H5. Nothing computable from top of book prices alone beats our cost floor at 1 to 60 seconds

**Falsifiable statement.** Over our 361k logged spot events, no feature computable from bid and
ask prices alone (mid return over multiple lookbacks, spread level, spread change, quote update
intensity, time since last update, realised volatility) predicts the 1 to 60 second forward mid
change well enough that the implied per trade edge exceeds the measured round trip spread, on
walk forward out of sample data, with a deflated Sharpe above zero.

**Why.** This is the null we should try hardest to reject, because it is the only hypothesis
testable entirely on data we already hold, today, with no new collection. Kearns gives the prior:
at a 1 second horizon even perfect foresight across the entire US equity market yields 760m USD,
which is 3.6% of the 10 second figure. Our prior should be that this null survives.

**Data needed.** Nothing new. `data/telemetry.db`, 361,402 spot events with microsecond receive
stamps, plus `backtest/run.measured_cost`.

**Do we hold it.** **Yes, entirely.** This is the only one of the five we can run immediately.

**Value of the negative result.** If H5 survives, we have a documented, measured reason to stop
proposing top of book microstructure features in the research loop, which saves the council from
rediscovering them. That belongs in `data/research.db` `lessons`.

---

### Recommended order of work

1. **H5 first.** It costs no new data and it calibrates everything else. Run it before collecting
   anything.
2. **H1 second**, and start the Binance plus VALR quote collector immediately regardless, because
   it needs elapsed time to accumulate.
3. **H2 third**, and start the funding collector at the same time as H1's, for the same reason.
4. **H4 fourth**, one week of depth quotes, expect failure, close the question.
5. **H3 last**, as a fill quality rule, once we have 200 live orders.

### The honest summary

At 949 ms median round trip, R2,000 of capital and an 8 bp round trip cost, the published
literature supports **one** credible precursor hypothesis: cross venue lead lag from a large venue
to a small one, at a 500 ms to 1 s horizon, and even that comes from a single month of 2021 data
on an exchange set that includes FTX. Everything else either lives inside our latency floor or
below our cost floor. The compute we spend should be biased toward killing hypotheses quickly, not
toward building a microstructure feature library.
