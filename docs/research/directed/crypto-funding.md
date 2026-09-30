# Do perpetual futures funding rates predict crypto returns?

Written by `scout/reading_room.py`. Model text is labelled; every quote below was checked by code against the paper. Nothing here is a decision to trade: an idea becomes a test only by being pre-registered in `docs/programme`.

## What was read

* Harvested 41 new papers (41 quantitative finance).
* Scored all of them; 9 scored 3 or more; read 8 (0 in full text).
* Grounded: 8 of 8. Model spend: $0.17 over 20 calls.

## This week in plain words (model synthesis)

**Connections across fields**

* While all idea cards are categorized under 'quantitative finance', two cards, 'Investor attention and cryptocurrency' (crypto-funding-3) and 'Speculation and lottery-like demand in cryptocurrency markets' (crypto-funding-6), both draw heavily from the sub-field of behavioral finance. They independently identify distinct psychological mechanisms—investor attention and lottery-like demand (preference for extreme positive outcomes)—as significant drivers of cryptocurrency market characteristics, suggesting a consistent influence of non-rational investor behavior on crypto asset pricing.

**What this should change**

* The engine's current trading costs for ETHUSD CFDs and other crypto CFDs (large overnight swap, significant spread, tenfold spread widening at rollover) are the primary and binding constraint preventing profitability for virtually all proposed crypto strategies based on market inefficiencies or behavioral factors.
* The engine's previously viable ETHUSD trend rule (E07) has definitively lost its edge since September 2022, and attempts to revive or explain its past profitability are not actionable.
* Behavioral finance factors like investor attention and lottery-like demand are identified as influencing cryptocurrency characteristics, but their potential edge is consistently consumed by the engine's high trading costs for crypto CFDs.

**Gaps**

* A clear understanding of the minimum required edge for a crypto CFD strategy to be profitable after the engine's specific and high trading costs.
* The ability to access or construct robust sentiment indices for various assets beyond simple Google Trends data.
* The absence of any cards from 'different sciences' other than quantitative finance, preventing cross-disciplinary connections as per the literal interpretation of the prompt's field requirement.

**Suggested next steps**

* `crypto-funding-1, crypto-funding-2, crypto-funding-3, crypto-funding-6`: The consistent inability of proposed crypto strategies to overcome high trading costs (spreads, overnight financing, rollover widening) across multiple cards this week indicates a fundamental mismatch between the engine's current crypto CFD access and the potential edge from these strategies. Investigating alternative, lower-cost access methods or brokers for crypto instruments is a critical next step.
* `crypto-funding-4, crypto-funding-5`: The repeated attempts to revive or explain the demoted ETHUSD trend rule (E07) in these cards, despite its confirmed lack of post-cost edge, highlights a need to definitively close research on strategies based on E07's past performance and redirect resources to genuinely new, cost-aware approaches.
* `crypto-funding-8`: The inability to test the hypothesis from crypto-funding-8 due to the lack of a sentiment index highlights a specific data acquisition and processing capability gap. Developing this capability could unlock future research in behavioral finance, a recurring theme this week, and potentially other areas.

## Idea cards

### `crypto-funding-1` Crypto Carry

quantitative finance, [doi:10.1287/mnsc.2024.05069](https://doi.org/10.1287/mnsc.2024.05069), read: abstract. **KILLED**

* **Concept:** carry in crypto markets—the difference between futures and spot prices
* **Market analogue:** The 'carry' in the paper refers to the premium or discount of futures prices relative to spot prices. For the engine, the closest analogue is the perpetual funding rate for cryptocurrencies, which represents the cost or income of holding a perpetual futures position relative to the spot price. The engine's ETHUSD CFD positions incur a broker's financing (swap) cost, which is its own cost of carry for a spot-like position.
* **Claim:** Carry in crypto markets, defined as the difference between futures and spot prices, can reach exceptionally high levels, sometimes exceeding 40% per annum, with significant variation over time.
* **Hypothesis:** When the perpetual funding rate for ETH is exceptionally high and positive, indicating a substantial premium of perpetual futures over spot, the ETHUSD CFD will exhibit positive momentum over the subsequent 1 to 20 days, driven by demand from trend-chasing investors.
* **Test:** Identify periods where the daily ETH perpetual funding rate (from Binance, BitMEX, or OKX) exceeds its 90th percentile over the preceding 90 days. For each such period, calculate the average total return (including broker's swap and spread) of the ETHUSD CFD over the subsequent 1, 5, and 20 trading days. The null hypothesis is that the average return during these high-carry periods is not significantly different from zero or from returns during other periods. Failure would be if returns are not significantly positive after costs, or are negative. This test can be run on historical data.
* **Red team, fatal:** The hypothesis makes a significant leap from the paper's descriptive findings about the existence and causes of high crypto carry to a claim of profitable spot momentum after trading costs. The engine's measured costs for ETHUSD CFDs (large overnight swap, significant spread) are known to be the primary constraint for profitability, and there is no evidence from the source paper to suggest this specific strategy would overcome them. Furthermore, the recent audit (A01) found that the engine's only previously passing Ethereum trend rule had lost all its edge since 2022, indicating a broader challenge for ETH-based momentum strategies.
> We analyze the dynamics of carry in crypto markets—the difference between futures and spot prices—and document that it can reach exceptionally high levels, sometimes exceeding 40% per annum, with significant variation over time.
> This phenomenon reflects a substantial and volatile inconvenience yield associated with holding spot cryptocurrencies relative to futures.

### `crypto-funding-2` Cryptomarket discounts

quantitative finance, [doi:10.1016/j.jimonfin.2023.102963](https://doi.org/10.1016/j.jimonfin.2023.102963), read: abstract. **KILLED**

* **Concept:** Market inefficiency and arbitrage opportunities arising from price discrepancies across segmented cryptocurrency markets.
* **Market analogue:** Price discrepancies for a cryptocurrency CFD (e.g., ETHUSD) between the engine's broker (IC Markets) and a major global spot exchange.
* **Claim:** There are persistent differences in relative bitcoin prices (or discounts) across exchange-currency pairs, which revert with a half-life of 1 day and have a standard deviation of 3.9%.
* **Hypothesis:** If the price of ETHUSD CFD at IC Markets consistently deviates from a major spot exchange's ETHUSD price, and these deviations revert with a half-life of approximately one day, then a strategy of buying the relatively discounted CFD and selling the relatively premium CFD will be profitable after accounting for trading costs (spread and overnight financing).
* **Test:** 1. Collect daily closing prices for ETHUSD from IC Markets (held data) and a major spot exchange (e.g., Binance, free to add). 2. Calculate the daily price difference (IC Markets ETHUSD price - Binance ETHUSD price). 3. Analyze the statistical properties of this difference, including its mean, standard deviation, skewness, kurtosis, and estimate its half-life of mean reversion. 4. Backtest a mean-reversion strategy: buy ETHUSD CFD when the IC Markets price is at a significant discount to the spot price, and sell ETHUSD CFD when it is at a significant premium. Positions should be exited as the difference reverts towards zero. 5. Apply measured IC Markets' spread and overnight financing costs for ETHUSD to the backtest. 6. The null hypothesis is that the strategy's net profit after costs is zero or negative, or indistinguishable from a random-sign null at the 99th percentile. Failure would be if the strategy does not generate positive returns after costs, does not beat the random-sign null, fails to survive doubled costs, or does not show positive returns in most years. This test can run on historical data before spending a live slot.
* **Red team, fatal:** costs eat the effect and weak analogy
> We document persistent differences in relative bitcoin prices (or discounts), with a half-life of 1 day, and a distribution which is leptokurtic, skewed to the right, with a standard deviation of 3.9%.
> The variability of discounts is larger in countries with tighter capital controls due to the combined effect of market segmentation and local supply and demand shocks, which we relate to location-specific mining activities and investor attention.

### `crypto-funding-3` Investor attention and cryptocurrency: Evidence from the Bitcoin market

quantitative finance, [doi:10.1371/journal.pone.0246331](https://doi.org/10.1371/journal.pone.0246331), read: abstract. **KILLED**

* **Concept:** Investor attention as a behavioral finance factor influencing asset characteristics.
* **Market analogue:** {'source_concept': 'Investor attention', 'market_analogue': 'Publicly available proxies for retail investor interest or sentiment in a cryptocurrency.', 'variable_mapping': {'Bitcoin': 'ETHUSD (as the most liquid and affordable crypto CFD for the engine)', 'Return': "Daily percentage change in ETHUSD's close price", 'Realized volatility': "A daily measure of price fluctuation for ETHUSD (e.g., Parkinson's volatility or daily standard deviation of intraday returns)", 'Investor attention': "A quantifiable measure of public interest in Ethereum, such as Google Trends search volume for 'Ethereum' or 'ETH price'"}, 'analogy_prediction': 'Changes in investor attention are expected to Granger cause changes in future ETHUSD returns and volatility, potentially leading to profitable trading opportunities.', 'what_could_be_wrong': "The relationship might be specific to Bitcoin, or the 'novel investor attention' measure used in the paper might not be replicable with publicly available proxies. The effect might be too small to overcome the high trading costs (spreads, overnight financing) of ETHUSD CFDs."}
* **Claim:** Investor attention is a non-negligible pricing factor for Bitcoin asset, Granger causes changes in both return and realized volatility, and improves prediction accuracy in Bitcoin return, which can be used to generate significant economic values.
* **Hypothesis:** For ETHUSD, a quantifiable measure of investor attention (e.g., Google Trends search volume for 'Ethereum') Granger causes changes in future daily returns, and trading strategies based on this attention can generate positive economic value after accounting for CFD trading costs.
* **Test:** Use historical daily ETHUSD closing prices (held data) and historical daily Google Trends search volume for 'Ethereum' (free data). Define a specific measure of 'investor attention' from the search volume (e.g., normalized daily search index). Test for Granger causality between past investor attention and future daily ETHUSD returns and/or volatility. Construct a simple long/short strategy based on investor attention signals. The null hypothesis is that the strategy's net Sharpe ratio after estimated trading costs (spread, overnight financing) is not positive, or it fails to beat a random-sign baseline at the 99th percentile, or it fails the doubled-cost test, or most years are negative. The test can be run on historical data.
* **Red team, fatal:** The combination of the engine's extremely high trading costs for ETHUSD CFDs (spread and large overnight financing) and the lack of any quantitative evidence from the source paper that claimed 'significant economic values' survive costs, makes it highly probable that any potential edge would be entirely consumed by trading costs. This is consistent with the engine's historical experience where costs are the binding constraint, and further reinforced by the recent failure of existing ETHUSD strategies (E07/A01).
> investor attention is the granger cause to changes in Bitcoin market both in return and realized volatility.
> investor attention improves prediction accuracy in Bitcoin return.

### `crypto-funding-4` Long- and Short-Term Cryptocurrency Volatility Components: A GARCH-MIDAS Analysis

quantitative finance, [doi:10.3390/jrfm11020023](https://doi.org/10.3390/jrfm11020023), read: abstract. **KILLED**

* **Concept:** Predictive relationships between external market/economic indicators (S&P 500 realized volatility, S&P 500 volatility risk premium, Baltic Dry Index) and long-term Bitcoin volatility components.
* **Market analogue:** The 'long-term Bitcoin volatility' in the paper is analogous to long-term ETHUSD volatility for the engine. The 'S&P 500 realized volatility', 'S&P 500 volatility risk premium', and 'Baltic dry index' are direct external market analogues.
* **Claim:** Long-term cryptocurrency volatility can be predicted by external macroeconomic and market risk factors, specifically that S&P 500 realized volatility has a negative effect, S&P 500 volatility risk premium has a positive effect, and the Baltic Dry Index has a positive association.
* **Hypothesis:** When S&P 500 realized volatility is higher, long-term ETHUSD volatility is predicted to be lower, and a simple trend-following strategy on ETHUSD (like the demoted E07) will exhibit a higher Sharpe ratio after trading costs during such periods compared to periods where S&P 500 realized volatility is lower.
* **Test:** 1. Obtain daily S&P 500 realized volatility data and daily ETHUSD price data (broker D1 bars for E07 strategy). 2. Divide the historical period into two regimes: 'higher S&P 500 realized volatility' (e.g., above its historical median) and 'lower S&P 500 realized volatility' (below its historical median). 3. Run the demoted E07 trend-following strategy on ETHUSD for both regimes, calculating its Sharpe ratio after accounting for trading costs. 4. The null hypothesis is that there is no statistically significant difference in the Sharpe ratio of the E07 strategy between periods of higher S&P 500 realized volatility and periods of lower S&P 500 realized volatility. 5. Failure condition: The Sharpe ratio of the E07 strategy in periods of higher S&P 500 realized volatility is not significantly better (e.g., fails to beat the 99th percentile of a bootstrap distribution of the 'lower volatility' regime's Sharpe ratio) or is negative after costs. This test can be run entirely on historical data.
* **Red team, fatal:** The proposed test attempts to revive a strategy (E07) that has been explicitly demoted due to its inability to generate returns above costs in the recent past. The engine's core problem is that costs eat the edge. If E07 no longer has an edge that survives costs, conditioning it on external factors related to volatility is unlikely to change this fundamental issue, especially given the questionable logical link between predicted lower volatility and improved trend-following performance. This is a direct contradiction of Audit A01's findings.
> We use the GARCH-MIDAS model to extract the long- and short-term volatility components of cryptocurrencies.
> S&P 500 realized volatility has a negative and highly significant effect on long-term Bitcoin volatility.

### `crypto-funding-5` On the efficiency and its drivers in the cryptocurrency market: the case of Bitcoin and Ethereum

quantitative finance, [doi:10.1186/s40854-023-00566-3](https://doi.org/10.1186/s40854-023-00566-3), read: abstract. **KILLED**

* **Concept:** Time-varying market efficiency and its drivers.
* **Market analogue:** The 'adjusted market inefficiency magnitude (AMIMs)' measure can be analogized to the profitability or edge of a simple trend-following trading strategy on ETHUSD. The 'driving factors' are external variables that influence this strategy's performance over time.
* **Claim:** There is time variation in the market efficiency of Bitcoin and Ethereum, driven by global financial stress and cryptocurrency liquidity.
* **Hypothesis:** The profitability of the engine's ETHUSD 20-day trend rule (E07) is positively correlated with cryptocurrency liquidity and negatively correlated with global financial stress.
* **Test:** Calculate the daily PnL of the ETHUSD 20-day trend rule (E07) over its historical period (2016-2023). Obtain daily values for a global financial stress index (e.g., FRED's Financial Stress Index) and daily average spread for ETHUSD as a proxy for cryptocurrency liquidity. Perform a regression or correlation analysis between the daily PnL of the trend rule and the daily values of the financial stress index and liquidity proxy. The null hypothesis is that there is no statistically significant correlation between the daily PnL and these drivers. Failure would be a statistically significant negative correlation between daily PnL and the global financial stress index, AND a statistically significant positive correlation between daily PnL and the ETHUSD daily average spread, at the 99th percentile. This test can be run on historical data.
* **Red team, fatal:** The hypothesis seeks to explain the profitability of a strategy (E07) that has been demoted due to the disappearance of its edge since September 2022 (Audit A01). This makes the proposed correlational study a post-mortem analysis rather than a test of a new, actionable trading hypothesis for the engine.
> Most previous studies on the market efficiency of cryptocurrencies consider time evolution but do not provide insights into the potential driving factors.
> The results show evidence of time variation in the levels of market (in)efficiency for Bitcoin and Ethereum.

### `crypto-funding-6` Speculation and lottery-like demand in cryptocurrency markets

quantitative finance, [doi:10.1016/j.intfin.2021.101289](https://doi.org/10.1016/j.intfin.2021.101289), read: abstract. **KILLED**

* **Concept:** Lottery-like demand and the MAX measure from behavioral finance and asset pricing literature, typically applied to stock markets.
* **Market analogue:** The concept of 'lottery-like demand' can be transferred to cryptocurrency CFDs. The 'daily log-returns from the previous week' directly corresponds to daily log-returns of the engine's crypto CFD instruments. The 'MAX measure' would be the maximum daily log-return over the past week. 'Portfolio sorts' imply ranking instruments, which can be done with the engine's limited crypto CFD universe. The analogy predicts that crypto CFDs with high recent maximum daily returns will underperform those with low recent maximum daily returns over the subsequent week.
* **Claim:** Cryptocurrencies exhibiting 'lottery-like demand', as measured by a modified MAX measure, show significant underperformance. Specifically, the average raw and risk-adjusted return differences between cryptocurrencies in the lowest and highest MAX quintiles exceed 1.50% per week.
* **Hypothesis:** Among the available crypto CFD instruments (ETHUSD, ADAUSD, BCHUSD, LTCUSD), the instrument with the highest maximum daily log-return over the previous five trading days (highest MAX measure) will, on average, underperform the instrument with the lowest maximum daily log-return over the same period (lowest MAX measure) over the subsequent week, after accounting for trading costs. A weekly rebalanced long-short strategy, shorting the highest MAX instrument and longing the lowest MAX instrument, will generate positive net returns.
* **Test:** For each available crypto CFD (ETHUSD, ADAUSD, BCHUSD, LTCUSD), at the close of each Friday (21:00 UTC D1 bar close), calculate the 'MAX measure' as the maximum daily log-return observed within the preceding five trading days. Rank the four instruments by their MAX measure. Form a long-short portfolio: go long the instrument with the lowest MAX measure and short the instrument with the highest MAX measure. Hold this position for one week, closing at the next Friday's 21:00 UTC D1 bar close. Calculate the weekly raw and cost-adjusted returns, including spread and significant overnight financing costs for crypto CFDs. The null hypothesis is that the average weekly cost-adjusted return of this strategy is zero or negative. Failure would be if the strategy's Sharpe ratio is not significantly positive (e.g., fails to beat a random-sign null at the 99th percentile) or if the average weekly cost-adjusted returns are negative. This test can be run on historical data.
* **Red team, fatal:** The engine's measured trading costs, particularly the large overnight financing for crypto CFDs and the tenfold spread widening at rollover, are highly likely to consume any potential edge from this weekly holding strategy. This is consistent with the engine's binding constraint being the cost of trading.
> This is the first paper that explores lottery-like demand in cryptocurrency markets.
> we modify Bali, Cakici and Whitelaw’s (2011) and Bali, Brown, Murray, and Tang’s (2017) MAX measure and employ a weekly forecast horizon and daily log-returns from the previous week to calculate the metric for our portfolio sorts.

### `crypto-funding-7` Stablecoin devaluation risk

quantitative finance, [doi:10.1080/1351847x.2025.2505757](https://doi.org/10.1080/1351847x.2025.2505757), read: abstract. **KILLED**

* **Concept:** Stablecoin devaluation risk under a pegged exchange rate regime.
* **Market analogue:** The engine does not trade stablecoins or traditional currencies under pegged exchange rate regimes. Its instruments (free-floating FX pairs and cryptocurrencies) do not experience 'devaluation risk' in the sense of a broken peg. Therefore, there is no direct market analogue for the core concept of the paper.
* **Claim:** Stablecoin issuers' reliance on centralized custodians introduces a devaluation risk, analogous to traditional currencies under pegged exchange rate regimes. This risk can be measured using market data, with probabilities for full or partial default, and is influenced by factors like market volatility, transaction velocity, and elevated interest rates.
* **Hypothesis:** Nothing testable here. The paper's core concept of 'stablecoin devaluation risk' and its analogy to 'traditional currencies under pegged exchange rate regimes' does not apply to the engine's tradeable instruments, which are free-floating cryptocurrencies and major FX pairs. The identified risk factors (market volatility, transaction velocity, elevated interest rates) are discussed in the specific context of stablecoin peg stability, not general price movements of unpegged assets.
* **Test:** 
* **Red team, fatal:** The core concept and mechanism of 'stablecoin devaluation risk' and its analogy to pegged exchange rate regimes are entirely inapplicable to the engine's free-floating instruments.
> Reliance of stablecoin issuers on centralized custodians introduces devaluation risk similar to that observed in traditional currencies under pegged exchange rate regimes.
> We construct market-based measures of stablecoin devaluation risk using spot and futures prices for Tether.

### `crypto-funding-8` The impact of macroeconomic news on Bitcoin returns

quantitative finance, [doi:10.1080/1351847x.2020.1737168](https://doi.org/10.1080/1351847x.2020.1737168), read: abstract. **KILLED**

* **Concept:** The concept of macroeconomic news sentiment influencing asset prices, specifically applied to cryptocurrencies.
* **Market analogue:** The potential for sentiment derived from US macroeconomic news announcements (GDP, unemployment, CPI, durable goods) to inversely impact the returns of cryptocurrency CFDs available to the engine (e.g., ETHUSD, ADAUSD, BCHUSD, LTCUSD), by analogy with Bitcoin.
* **Claim:** The paper claims that macroeconomic news, specifically the sentiment around unemployment rates and durable goods announcements, has a statistically significant inverse impact on Bitcoin returns.
* **Hypothesis:** The engine cannot test the specific hypothesis presented in this paper because it lacks the capability to construct or acquire a "sentiment index based on news stories" for macroeconomic announcements. Without this sentiment index, the core variable linking macroeconomic news to Bitcoin returns, as described in the paper, cannot be observed or replicated by the engine.
* **Test:** Not applicable, as the primary variable required for testing (the sentiment index) is unavailable and its construction is beyond the engine's current data acquisition and processing capabilities.
* **Red team, fatal:** The engine cannot test the specific hypothesis presented in this paper because it lacks the capability to construct or acquire a 'sentiment index based on news stories' for macroeconomic announcements. Without this sentiment index, the core variable linking macroeconomic news to Bitcoin returns, as described in the paper, cannot be observed or replicated by the engine.
> We construct a sentiment index based on news stories that follow the announcements of four macroeconomic indicators: GDP, unemployment, Consumer Price Index (CPI) and durable goods.
> Increases in positive news after unemployment and durable goods announcements result in a decrease in Bitcoin returns.

## Top of the research queue

| id | idea | field | priority |
|---|---|---|---|
| `2026-W40-1` | A reproducible protocol for auditing XAI-based trading policies: A case study on | statistics | 12.5 |
