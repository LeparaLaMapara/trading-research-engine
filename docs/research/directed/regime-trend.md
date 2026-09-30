# Do regime-switching (hidden Markov) filters improve trend following?

Written by `scout/reading_room.py`. Model text is labelled; every quote below was checked by code against the paper. Nothing here is a decision to trade: an idea becomes a test only by being pre-registered in `docs/programme`.

## What was read

* Harvested 85 new papers (85 quantitative finance).
* Scored all of them; 22 scored 3 or more; read 8 (2 in full text).
* Grounded: 8 of 8. Model spend: $0.24 over 21 calls.

## This week in plain words (model synthesis)

**Connections across fields**

* Cards 'regime-trend-4' (A Non-Homogeneous Hidden Markov Model for Precipitation Occurrence) and 'regime-trend-8' (Downscaling of Daily Rainfall Occurrence over Northeast Brazil Using a Hidden Markov Model) both directly transfer the concept of Hidden Markov Models (HMMs) from atmospheric science/hydrology (predicting rainfall patterns) to quantitative finance. The common mechanism is using HMMs to identify unobservable, discrete 'regimes' that govern observable phenomena, whether it be rainfall occurrences or financial instrument price movements. Card 'regime-trend-5' (Active and passive portfolio management with latent factors) further reinforces this thematic link by exploring HMMs for identifying latent market factors and regimes within a finance context.

**What this should change**

* The engine's belief that trading costs, particularly overnight financing for crypto CFDs and FX carry/overnight holds, are the primary and often insurmountable barrier to profitability is strongly reinforced. Almost all proposed strategies were killed due to their inability to overcome these costs.
* There is increased confidence that many crypto-related market edges, including momentum, trend-following, and investor attention-based strategies, have significantly decayed or ceased to be profitable after 2022. This renders historical findings from earlier periods less relevant for current strategy development.
* The engine should continue to believe that methodological improvements in prediction accuracy (e.g., volatility forecasting) or general portfolio selection frameworks do not automatically translate into profitable trading strategies. Hypotheses must explicitly quantify a market effect that generates net profit after accounting for all trading costs.
* While HMM-based regime identification ideas faced fatal flaws (costs, lookahead bias), the repeated exploration and high value/information scores for some (e.g., 'regime-trend-5') suggest that understanding and adapting to market regimes remains a high-value research direction, provided the methodological pitfalls can be overcome with forward-looking, cost-aware designs.

**Gaps**

* A significant gap exists in the engine's research pipeline for generating trading hypotheses that *prioritize* the stringent trading cost constraints from the outset, rather than attempting to overcome them after a strategy is conceived.
* The repeated observation of strategy decay post-2022 highlights a gap in developing methods that are inherently robust to evolving market dynamics and non-stationarity, beyond simple HMM applications that have proven difficult to implement without bias or cost issues.
* There is a consistent challenge in translating advanced quantitative methodologies and prediction accuracy improvements into concrete, falsifiable trading strategies that can demonstrably generate net positive returns within the engine's operational constraints.

**Suggested next steps**

* `regime-trend-6`: This card, describing a Bayesian nonparametric portfolio selection methodology, was uniquely not killed by the red team and remains in the queue. This suggests it has potential to be adapted into a cost-aware, testable hypothesis, warranting a deeper dive into its specific mechanisms to identify a market effect that might overcome the engine's cost constraints.
* `regime-trend-5`: Despite being killed for lookahead bias and an unfalsifiable hypothesis, this card received high information (4) and value (5) scores. This indicates the underlying concept of using HMMs for online regime identification to adapt strategies is highly valued. The next step should be to reformulate the hypothesis to address the fatal flaws, focusing on truly forward-looking regime detection and ex-ante strategy adaptation to make it testable and valid.
* `2026-W40-1`: This queue item, focused on auditing XAI-based trading policies, has the highest priority (12.5). Given the consistent failure of specific trading ideas due to various flaws (costs, decay, methodological issues), a robust protocol for auditing new policies is critical for the engine's long-term research integrity and effectiveness.

## Idea cards

### `regime-trend-1` Beyond the Carry Trade: Optimal Currency Portfolios

quantitative finance, [doi:10.1017/s0022109015000460](https://doi.org/10.1017/s0022109015000460), read: abstract. **KILLED**

* **Concept:** Factor investing in currency portfolios (carry, momentum, value reversal).
* **Market analogue:** In FX CFDs, 'carry' corresponds to the interest rate differential between the base and quote currencies. 'Momentum' corresponds to the price trend of the FX pair over a defined period. 'Value reversal' is not sufficiently defined by the abstract to create a testable analogue, especially since the abstract states 'the real exchange rate and the current account do not' contribute.
* **Claim:** Carry, momentum, and value reversal all contribute to portfolio performance in currency markets, producing out-of-sample returns not explained by risk.
* **Hypothesis:** For the engine's available FX currency pairs (AUDCAD, AUDNZD, EURCAD, EURGBP, USDSGD), a trading strategy that combines daily signals from interest rate carry and 20-day price momentum, and then selects the top-ranked pair(s) to trade within the engine's position limits, will generate positive net returns after trading costs.
* **Test:** For each of the five available FX pairs, calculate a daily carry signal (long higher-yielding currency, short lower-yielding using 3-month interbank rates) and a 20-day price momentum signal (e.g., long if 20-day return is positive, short if negative). Combine these signals (e.g., an average score or a weighted sum) to rank the pairs daily. Implement a strategy that opens up to two positions based on the highest-ranked signals, respecting the engine's risk and margin limits. The null hypothesis is that the strategy's net PnL is indistinguishable from one generated by randomly assigning long/short directions to the selected pairs, using the same trading frequency and position sizing. Failure would be defined as the strategy's net PnL not beating the random-sign null at the 99th percentile, or failing to survive a doubled-costs scenario, or not achieving positive returns in most years. This test can be run on historical data.
* **Red team, fatal:** The combination of previous experimental failure of FX momentum (E08/A01), the certainty of significant overnight financing costs for carry trades, and the critical time-of-day confound from rollover spread widening makes this strategy highly unlikely to overcome the engine's primary constraint of trading costs.
> Carry, momentum, and value reversal all contribute to portfolio performance
> whereas the real exchange rate and the current account do not.

### `regime-trend-2` Common Risk Factors in Cryptocurrency

quantitative finance, [doi:10.1111/jofi.13119](https://doi.org/10.1111/jofi.13119), read: full (open-access PDF). **KILLED**

* **Concept:** The concepts are drawn from established factors in the cross-section of stock returns, for which the authors construct cryptocurrency counterparts. The paper states: "We consider a comprehensive list of price- and market-related factors in the stock market, and construct their cryptocurrency counterparts."
* **Market analogue:** The paper's 'cryptocurrencies' are analogous to the engine's crypto CFD instruments (ETHUSD, ADAUSD, BCHUSD, LTCUSD). The core concept of 'momentum strategies perform significantly better among the larger coins' is directly applicable, as the engine's tradable crypto CFDs are generally considered larger coins.
* **Claim:** Three factors – cryptocurrency market, size, and momentum – capture the cross-sectional expected cryptocurrency returns, with nine factors forming successful long-short strategies. Momentum strategies, in particular, perform significantly better among larger coins, generating substantial weekly excess returns.
* **Hypothesis:** Among the engine's available crypto CFDs (ETHUSD, ADAUSD, BCHUSD, LTCUSD), a weekly rebalanced strategy that goes long the crypto CFD with the highest 3-week momentum and shorts the crypto CFD with the lowest 3-week momentum will generate statistically significant positive excess returns after accounting for trading costs.
* **Test:** Backtest a weekly rebalanced strategy on historical data for ETHUSD, ADAUSD, BCHUSD, LTCUSD. Each week, calculate the 3-week momentum for each of these four instruments. Go long the instrument with the highest 3-week momentum and short the instrument with the lowest 3-week momentum. The null hypothesis is that the weekly net return of this long-short portfolio is statistically indistinguishable from zero after accounting for spreads and financing costs. Failure would be if the strategy fails to beat a random-sign null at the 99th percentile, or if its Sharpe ratio is negative, or if it results in a loss after doubling historical trading costs. This test can be run on history.
* **Red team, fatal:** The paper does not account for trading costs, which are the binding constraint for this engine, and its findings are based on an outdated sample period, with recent engine experiments showing a decay of similar crypto momentum/trend edges post-2022.
> Nine cryptocurrency factors form successful long-short strategies that generate sizable and statistically significant excess returns.
> Each week, we sort the returns of individual cryptocurrencies into quintile portfolios based on the value of a given factor. We track the return of each portfolio in the week that follows and calculate the average excess return over the risk-free rate of each portfolio. We then form the long-short strategy based on the diﬀerence between the ﬁfth and the ﬁrst quintiles.

### `regime-trend-3` Risks and Returns of Cryptocurrency

quantitative finance, [doi:10.1093/rfs/hhaa113](https://doi.org/10.1093/rfs/hhaa113), read: full (open-access PDF). **KILLED**

* **Concept:** Investor attention as a predictor of asset returns.
* **Market analogue:** For ETHUSD, an increase in Google searches for 'Ethereum' (relative to its recent average) predicts higher future weekly returns, and a decrease predicts lower future weekly returns.
* **Claim:** Cryptocurrency returns can be predicted by factors which are specific to cryptocurrency markets, specifically proxies for investor attention strongly forecast cryptocurrency returns.
* **Hypothesis:** For ETHUSD, a weekly time-series strategy based on investor attention, where a positive (negative) standardized deviation of Google searches for 'Ethereum' (compared to the average of the preceding four weeks) predicts higher (lower) future weekly returns, will generate positive returns net of trading costs.
* **Test:** Data: Weekly ETHUSD open/close prices from IC Markets (held data), and weekly Google Trends search volume for 'Ethereum' (free to add). Null Hypothesis: Weekly ETHUSD returns are independent of the standardized deviation of weekly Google Trends search volume for 'Ethereum' (compared to the average of the preceding four weeks), after accounting for trading costs. Procedure: At the close of each week (Sunday 21:00 UTC broker time), calculate the Google search proxy for 'Ethereum' as the raw weekly search volume for 'Ethereum' minus its average over the preceding four weeks, then standardize this difference by its historical standard deviation. If the standardized proxy is positive, open a 0.01 lot long position on ETHUSD at the next Monday 21:00 UTC open. If the standardized proxy is negative, open a 0.01 lot short position. Hold the position for one week, closing at the following Monday 21:00 UTC open. Simulate this strategy historically, applying measured spreads (ETHUSD about $3 per ETH) and overnight swap costs (large for crypto CFDs). Failure: The strategy's net Sharpe ratio is not above zero, or it does not beat a random-sign null at the 99th percentile, or it does not survive doubled costs, or most years are negative. Historical run: Yes, can run on history.
* **Red team, fatal:** The hypothesis is contradicted by prior experiments (E07/A01) showing that historical ETH strategies do not persist after 2022, and a very similar idea has already been killed from the research queue.
> Specifically, we determine that there is a strong time-series momentum effect and that proxies for investor attention strongly forecast cryptocurrency returns.
> Second, we construct proxies for investor attention and show that high investor attention predicts high future returns over 1-2 week horizons for Bitcoin, a 1-week horizon for Ripple, and 1-, 3-, and 6-week horizons for Ethereum.

### `regime-trend-4` A Non-Homogeneous Hidden Markov Model for Precipitation Occurrence

quantitative finance, [doi:10.1111/1467-9876.00136](https://doi.org/10.1111/1467-9876.00136), read: abstract. **KILLED**

* **Concept:** The concept of a 'non-homogeneous hidden Markov model' for the 'downscaling problem' is transferred. The paper uses it to relate local precipitation to broad atmospheric patterns.
* **Market analogue:** In a market context, 'precipitation occurrences at multiple rain-gauge stations' correspond to daily price movements (e.g., returns, volatility) of multiple financial CFD instruments. 'Broad scale atmospheric circulation patterns' correspond to broad market conditions or macro indicators such as perpetual funding rates or CFTC positioning. The 'hidden states' represent unobserved market regimes (e.g., trending, range-bound). The 'downscaling problem' becomes predicting individual instrument's regime or behavior based on macro/broad market conditions.
* **Claim:** A Non-Homogeneous Hidden Markov Model (NHHMM) can accurately model and potentially predict market regimes for individual CFD instruments by incorporating broad-scale market drivers, even when these drivers shift over time.
* **Hypothesis:** A Non-Homogeneous Hidden Markov Model (NHHMM) that uses broad-scale market indicators (e.g., perpetual funding rates, CFTC positioning for ETH) to influence regime transition probabilities can identify periods where the 20-day trend-following strategy on ETHUSD (as per E07) is profitable, leading to a net positive Sharpe ratio after all trading costs over the 2022-2026 period, where E07 itself previously failed.
* **Test:** Define two hidden regimes for ETHUSD: 'trending' (e.g., 20-day Simple Moving Average slope positive or negative) and 'non-trending' (e.g., flat 20-day SMA or high mean reversion). Use daily ETHUSD returns/volatility as observable emissions. Incorporate daily ETH perpetual funding rates and weekly CFTC positioning for ETH as non-homogeneous covariates influencing regime transition probabilities. Fit the NHHMM on ETHUSD daily data from 2018-2021. For the out-of-sample period (2022-2026), use the fitted model to predict the most likely regime each day. Execute the E07 trend-following strategy (buy if trending up, sell if trending down) only when the NHHMM predicts a 'trending' regime; otherwise, stay flat. The null hypothesis is that the Sharpe ratio of this NHHMM-filtered strategy over 2022-2026 is not significantly positive after accounting for actual spreads and overnight financing costs (as measured by E04). Failure would be a Sharpe ratio not statistically different from zero, or not outperforming the -0.04 Sharpe of E07 over the same period. This test can be run entirely on historical data.
* **Red team, fatal:** Costs will eat the effect
> A non-homogeneous hidden Markov model is proposed for relating precipitation occurrences at multiple rain-gauge stations to broad scale atmospheric circulation patterns (the so-called ‘downscaling problem’).
> The fitted model accurately reproduces the observed rainfall statistics in the reserved data despite a shift in atmospheric circulation (and, consequently, rainfall) between the two periods.

### `regime-trend-5` Active and passive portfolio management with latent factors

quantitative finance, [doi:10.1080/14697688.2021.1881598](https://doi.org/10.1080/14697688.2021.1881598), read: abstract. **KILLED**

* **Concept:** The core concept transferable is the use of an unobservable Markov chain as a 'latent factor' to model and estimate asset growth rates, thereby identifying different market regimes.
* **Market analogue:** The 'assets' growth rate processes' correspond to the daily returns of tradable instruments like ETHUSD. The 'latent factor' or 'unobservable Markov chain' corresponds to an underlying, unobservable market regime (e.g., trending, mean-reverting, or volatile) that influences the characteristics of these returns. The 'filtering step' would be a Hidden Markov Model (HMM) applied to historical price data to infer these regimes. The 'optimal allocation' would involve adapting a trading strategy (e.g., turning a trend-following rule on or off) based on the inferred market regime.
* **Claim:** The paper claims that incorporating latent factors, specifically an unobservable Markov chain, can lead to improved growth rate estimation for assets, which in turn enables an optimal portfolio strategy with demonstrated performance in historical backtests.
* **Hypothesis:** A two-state Hidden Markov Model (HMM) applied to the daily log returns of ETHUSD will identify distinct market regimes. The performance of the engine's existing 20-day trend-following rule (E07) will be significantly different (e.g., positive vs. negative Sharpe ratio before costs) when applied only during periods identified by the HMM as being in one specific regime compared to another, such that trading only in the 'favorable' regime would meet the engine's audit criteria.
* **Test:** 1. **Data**: Use daily log returns of ETHUSD from the held broker bars, covering the full available history. 2. **Model Fitting**: Fit a two-state Hidden Markov Model to these daily log returns, using standard algorithms like Baum-Welch for parameter estimation. 3. **Regime Identification**: Use the Viterbi algorithm to infer the most probable sequence of states (regimes) for the entire historical period. 4. **Strategy Application**: Apply the E07 20-day trend-following rule to ETHUSD. 5. **Performance Comparison**: Calculate the Sharpe ratio (before costs) of E07 when trades are only allowed during periods identified as State 1, and separately for State 2. 6. **Null Hypothesis**: The Sharpe ratio of E07 in State 1 is not statistically different from the Sharpe ratio of E07 in State 2, after accounting for trading costs. 7. **Failure Condition**: The test fails if the performance difference between the identified states is not statistically significant, or if the 'favorable' state's performance, when traded in isolation, does not meet the engine's pass criteria (beating a random-sign null at the 99th percentile, surviving doubled costs, and most years positive). This test can be run entirely on historical data.
* **Red team, fatal:** The use of the Viterbi algorithm for regime identification on the entire historical period introduces lookahead bias, making the results of the proposed test invalid for predicting future performance in a live trading environment. Additionally, the selection bias in identifying a 'favorable' regime after the fact makes the hypothesis unfalsifiable as stated.
> We assume a general semimartingale market model where the assets' growth rate processes are driven by a latent factor.
> The motivation for incorporating latent factors is to achieve improved growth rate estimation, an otherwise notoriously difficult task.

### `regime-trend-6` Bayesian nonparametric portfolio selection with rolling maximum drawdown control

quantitative finance, [doi:10.1080/14697688.2023.2250386](https://doi.org/10.1080/14697688.2023.2250386), read: abstract. **priority 0.0**

* **Concept:** Computational methodology for portfolio selection and return predictability.
* **Market analogue:** The 'multiple risky assets' could correspond to the engine's CFD instruments (e.g., ETHUSD, AUDCAD). 'Return predictability' refers to any market anomaly or persistent pattern in asset returns that could be exploited. The paper's analogy would predict that a sophisticated statistical model can identify and exploit such patterns across these assets. The analogy could be wrong if the specific patterns identified by the HDP-HMM in the paper's context do not exist or are not robust in the engine's CFD markets, or if the 'return predictability' is too weak to overcome trading costs.
* **Claim:** The paper claims a novel approach to portfolio selection that uses a non-parametric Bayesian model (HDP-HMM) to predict multiperiod mean and covariance of returns, leading to trading strategies that outperform existing approaches in out-of-sample performance.
* **Hypothesis:** Nothing testable here. The abstract describes a general methodology for portfolio selection and return prediction using an HDP-HMM, but it does not identify or specify any particular market effect or anomaly (e.g., momentum, mean reversion, value, carry) that can be isolated and tested by the engine. It focuses on *how* to predict and manage a portfolio, not *what* specific market feature is being predicted or *why* it is predictable.
* **Test:** Not applicable.
> We present a novel approach to the portfolio selection problem for a multiperiod investor facing multiple risky assets, trading constraints, and return predictability.
> Additionally, we propose the use of a non-parametric Bayesian model, specifically the hierarchical Dirichlet process based Hidden Markov Model (HDP-HMM), to predict the multiperiod mean and covariance of returns.

### `regime-trend-7` DeepVol: volatility forecasting from high-frequency data with dilated causal convolutions

quantitative finance, [doi:10.1080/14697688.2024.2387222](https://doi.org/10.1080/14697688.2024.2387222), read: abstract. **KILLED**

* **Concept:** Deep learning (Dilated Causal Convolutions) for improved volatility forecasting using high-frequency data.
* **Market analogue:** Forecasting day-ahead volatility for CFD instruments (FX, crypto) using available high-frequency tick data, potentially for improved risk management or adaptive trading strategies.
* **Claim:** DeepVol, a model based on Dilated Causal Convolutions using high-frequency data, provides more accurate day-ahead volatility forecasts and risk measures compared to traditional methodologies.
* **Hypothesis:** This abstract describes a methodological improvement in volatility forecasting accuracy and risk measurement, but it does not propose a specific trading strategy or quantify any market effect that could generate profits after trading costs. While improved volatility forecasts could potentially be used for better risk management or adaptive position sizing in a trading strategy, the abstract does not provide enough detail to formulate a falsifiable hypothesis for the engine to test regarding profitability or risk-adjusted returns. It focuses on prediction accuracy, not trading edge.
* **Test:** Not applicable, as no specific, falsifiable trading hypothesis can be formulated from the abstract.
* **Red team, fatal:** The idea card, as presented, does not propose a specific, falsifiable trading hypothesis that quantifies a market effect and considers trading costs. It focuses solely on prediction accuracy, which the engine has repeatedly found does not translate to profitable trading after costs.
> Volatility forecasts play a central role among equity risk measures.
> Moreover, econometric studies have shown that increasing the number of daily observations with high-frequency intraday data helps to improve volatility predictions.

### `regime-trend-8` Downscaling of Daily Rainfall Occurrence over Northeast Brazil Using a Hidden Markov Model

quantitative finance, [doi:10.1175/jcli-3216.1](https://doi.org/10.1175/jcli-3216.1), read: abstract. **KILLED**

* **Concept:** A hidden Markov model (HMM) is used to describe daily rainfall occurrence... The model assumes that rainfall occurrence is governed by a few discrete states, with Markovian daily transitions between them.
* **Market analogue:** Daily price direction (positive or negative close-to-close return) for a financial instrument is governed by a few discrete hidden market regimes, with Markovian daily transitions between them.
* **Claim:** Hidden Markov Models (HMMs) can identify unobserved market regimes that influence the daily direction of an instrument's price.
* **Hypothesis:** For ETHUSD, a Hidden Markov Model (HMM) trained on the sign of daily close-to-close returns can identify at least two distinct hidden market states such that the probability of a positive return in one state is statistically significantly different from the probability of a positive return in another state.
* **Test:** 1. Data: Use daily close prices for ETHUSD from IC Markets, converting them into a binary sequence representing positive (1) or negative/zero (0) close-to-close returns. 2. Model Training: Train an HMM (e.g., with 2 to 4 hidden states, similar to the paper's 'Four hidden rainfall states') on this binary sequence for ETHUSD. 3. State Characterization: For each identified hidden state, calculate the conditional probability of a positive return. Verify if at least two states have statistically significantly different conditional probabilities of positive returns. 4. Trading Strategy Simulation: Simulate a trading strategy: at the close of each day, infer the most likely hidden state using the HMM. If the inferred state's historical conditional probability of a positive return is above 50% (or above the overall average positive return probability), take a long position for the next day. If it's below 50% (or below average), take a short position. Close the position at the next day's close. 5. Cost Application: Apply typical trading costs for ETHUSD (spread, overnight swap for D1 holding) to the simulated trades. 6. Null Hypothesis: The net profit after costs of the HMM-based trading strategy is not statistically significantly better than zero, nor does it beat a random-sign trading strategy (where long/short positions are chosen randomly each day) at the 99th percentile, over the same historical period. 7. Failure Criteria: The test fails if the HMM-based strategy does not achieve a positive net profit after costs, or if its performance (e.g., Sharpe ratio) does not significantly outperform the random-sign null. 8. Run on history: This test can be run entirely on historical data before live trading.
* **Red team, fatal:** The overnight financing charge for ETHUSD CFD is explicitly stated as 'large' and 'the biggest cost for anything held overnight'. A strategy that mandates holding positions overnight on a crypto CFD for daily directional bets is fundamentally incompatible with the account's cost structure and the engine's measured facts.
> Four “hidden” rainfall states are identified.

## Top of the research queue

| id | idea | field | priority |
|---|---|---|---|
| `2026-W40-1` | A reproducible protocol for auditing XAI-based trading policies: A case study on | statistics | 12.5 |
| `regime-trend-6` | Bayesian nonparametric portfolio selection with rolling maximum drawdown control | quantitative finance | 0.0 |
