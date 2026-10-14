# ML_PRIMER.md — how the ML in stratrad works (learning notes)

From the 2026-10-09 learning discussion. Present tense; update if the design changes.
Design source: the plan doc and `tech-debt/ST-0xx.md`.

## The one-line version
The ML manages strategies; it does not invent trades. Strategies (momentum leaders, RSI pullback, 52-week breakout,
low-vol quality, sector strength) are fixed, readable rules. ML decides **how much** to invest, **which strategies**
get the week's money and **how tight** stops are. Guardrails sit outside the ML; every buy needs Rakesh's approval.

## Generic ML pipeline → stratrad
| # | Generic step | What it means | In stratrad |
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

## The strategy allocator — features and labels (2026-10-11)

**Question it answers each week:** which strategies get this week's ₹10,000?
**One row = one strategy in one week** (not a stock). Prerequisite: every strategy is run over history
(ST-010 backtest engine) to produce a weekly track record — holdings, returns, drawdowns.
Size: ~5 strategies × ~600 weeks (2014–2026) ≈ **3,000 rows** — small, which shapes the design.

**Features — known at Friday's close, before the week starts**

| Group | Features | Why |
|---|---|---|
| Strategy's own record | return over last 4 / 13 / 26 weeks; Sharpe; current drawdown from peak; hit rate of recent picks | strategies have hot and cold streaks |
| What the strategy sees now | number of qualifying stocks (signal breadth); average signal strength of top picks; their average volatility; sector concentration | 3 weak candidates ≠ 40 strong ones |
| Market context (same for all strategies that week) | regime probabilities; % of stocks above 200 DMA; India VIX level and 4-week change; Nifty 500 3-month return; FII flows 4 weeks; cross-sectional return dispersion | each strategy suits different conditions |

Gradient-boosted trees find interactions on their own (e.g. momentum works when breadth is high AND VIX is low).

**Label — what happened next:** the strategy's next 4-week return, after costs, minus the Nifty 500 over the same
4 weeks (skill, not market), minus a penalty for the worst drawdown inside those 4 weeks (the Objective's
"loss first"). It is a ranking model, so the order within each week is what matters (rank 1..5).

**Illustrative week (made-up numbers)**

| Week of 6 Jan 2020 | 13-wk return | Qualifying stocks | VIX | Breadth | Label (next 4 wks vs Nifty, less DD penalty) |
|---|---|---|---|---|---|
| Momentum leaders | +9% | 42 | 12 | 68% | +2.1% (rank 1) |
| RSI pullback | +3% | 18 | 12 | 68% | +0.4% (rank 3) |
| 52-week breakout | +6% | 25 | 12 | 68% | +1.2% (rank 2) |
| Low-vol quality | +1% | 60 | 12 | 68% | −0.3% (rank 4) |
| Sector strength | +4% | 30 | 12 | 68% | −0.8% (rank 5) |

**Live use:** each Monday score all strategies, fund the top one or two, within the ₹40,000-per-strategy cap.

**Traps specific to the allocator**
- **Overlapping labels:** each 4-week label overlaps the next three weeks' labels → purge a gap between training
  and test periods so the model cannot peek through neighbouring weeks.
- **Small data:** short feature list, shallow trees, and it must beat a **rule-based allocator** ("fund the
  strategy with the best 13-week return per unit of risk"). If it cannot, the rule stays — an honest, likely outcome.
- **Look-ahead:** features use data up to Friday's close only; the label starts from the next trading day.

## Until the ML earns its place (Gate 2)
All three layers are simple rules: invest the full ₹10k, momentum strategy, fixed ATR-multiple stops. ML runs on
paper in the background and takes over only if it beats those rules out of sample.
