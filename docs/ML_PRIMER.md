# ML_PRIMER.md — how the ML in strategy-trader works (learning notes)

From the 2026-10-09 learning discussion. Present tense; update if the design changes.
Design source: the plan doc and `tech-debt/ST-0xx.md`.

## The one-line version
The ML manages strategies; it does not invent trades. Strategies (momentum leaders, RSI pullback, 52-week breakout,
low-vol quality, sector strength) are fixed, readable rules. ML decides **how much** to invest, **which strategies**
get the week's money and **how tight** stops are. Guardrails sit outside the ML; every buy needs Rakesh's approval.

## Generic ML pipeline → strategy-trader
| # | Generic step | What it means | In strategy-trader |
|---|---|---|---|
| 1 | Historical data | past examples with known outcomes | bhavcopy 2014→today, index closes, VIX, FII flows (ST-002/003/004/013) |
| 2 | Features + labels | inputs known at that moment + what happened next | RSI, trend, momentum, volatility, volume, breadth → next 4-week return vs Nifty 500 |
| 3 | Training | find the feature→label relationship with fewest mistakes | 3 models: regime (HMM/boosted), allocator (LightGBM rank), stock ranker (boosted trees) |
| 4 | Validation | test on unseen data | walk-forward (train 2014–18, test 2019, roll); 2024–26 held out; Objective rules; Gate 2 = beat baseline |
| 5 | Predictions | trained model scores new cases, no learning | Monday scoring → guardrails → Telegram approval cards |
| 6 | Monitoring | compare predictions with reality; drift → retrain | live vs backtest, champion/challenger, weekly/monthly retrain, Rakesh approves promotions |

## The three models
- **Regime (monthly)** — breadth, VIX, flows, rates, INR, crude → bull/sideways/bear probabilities → overall
  exposure. Hidden Markov Model: a Markov chain is states + transition probabilities; "hidden" because the state is
  inferred from symptoms. Good for regimes; useless for predicting single stock prices; lags turns by weeks.
- **Allocator (weekly)** — learning-to-rank on each strategy's recent and regime-specific performance → share of
  the ₹10k per strategy. Target: forward return with a drawdown penalty (Objective built in).
- **Stock ranking + stops (daily)** — ranks a funded strategy's candidates; ATR-based stop sizes risk to ~₹1,000.

## Historical data — what "good" means
Enough examples; variety of conditions (2018, 2020, 2022 included); point-in-time only (no look-ahead, no restated
values); no survivorship bias (delisted stocks kept — why NSE files, not Kite); consistent (splits/bonuses adjusted,
renames stitched); accurate (ST-002: 267,237 stock-days, 0 mismatches); time order kept (never shuffle). Limit: the
future may not rhyme with the past → drift monitoring, rolling retrain, fixed guardrails.

## From OHLCV to signal
Features computed from OHLCV/index/VIX: multi-horizon returns, distance from 50/200 DMA, RSI, 52-week-high distance,
volatility/ATR, volume vs average, traded value, relative strength and beta vs index, gaps, breadth, VIX.
Beating the noise: rank stocks against each other on the same date (cross-sectional — market mood cancels out);
ranks not raw values; weeks-to-months horizons, not days; many small bets. Realistic skill: information
coefficient (rank correlation of predicted vs actual) ~0.03–0.08 is good. Bigger claims usually mean overfitting.

## Standard models
Rule-based factors (baseline, hard to beat) · linear/logistic regression · random forests · **gradient-boosted
trees (LightGBM — our main choice for tabular data)** · learning-to-rank · HMM (regimes) · GARCH (volatility) ·
clustering · deep learning (LSTM/Transformers — needs far more data; skipped for now).

## Tooling
Python on rkneo50q, no GPU: pandas (features), LightGBM / hmmlearn / scikit-learn (models), MLflow (versions,
parameters, scores — every trade traceable to the model that proposed it).

## Until the ML earns its place (Gate 2)
All three layers are simple rules: invest the full ₹10k, momentum strategy, fixed ATR-multiple stops. ML runs on
paper in the background and takes over only if it beats those rules out of sample.
