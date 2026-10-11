# Data model — strategy-trader

Status: **PROPOSAL 2026-10-11 — pending Rakesh's approval.** Decided so far (Rakesh, 2026-10-11): research data in
files, operational data in PostgreSQL; the database (ST-012) is built after ST-010 and before any execution issue.

## 1. Two stores

| | Research store | Operational store |
|---|---|---|
| Holds | prices, corporate actions, renames, universe, features, backtest runs | strategies, models, signals, proposals, approvals, orders, GTT stops, positions, guardrail and audit logs, daily snapshots |
| Written by | batch jobs; everything derived can be rebuilt from raw downloads | the live system every trading day; **cannot** be rebuilt |
| Needs | fast bulk reads (years x 500 stocks) | transactions, constraints, audit trail, concurrent access |
| Home | files under `data/` (Parquet for large tables, CSV for small reviewed ones) | PostgreSQL database `strategy_trader` on rkneo50q (ST-012), own schema and roles |
| Backup | FFS Job 3 mirror + Kopia (`docs/CONFIG.md`) | `pg_dump` in the nightly chain (homelab, with ST-012) |

The research store never reads the operational store. The operational store reads research outputs only through
versioned artifacts (a strategy config, a model version, a universe as-of date).

## 2. Identifiers (used in both stores)

| Name | Meaning | Source |
|---|---|---|
| `company_key` | the company's symbol **today**; constant across renames (TIDEWATER's history -> `VEEDOL`) | `core/securities.py` (ST-013) |
| `series_id` | `company_key@YYYY-MM-DD` (first date of the series); a new series starts at a trading gap > 30 days with an ISIN change (post-insolvency relistings) | ST-004 |
| `symbol` | the NSE symbol actually traded on that date (= Kite `tradingsymbol` for live orders) | bhavcopy / Kite |
| `isin` | the day's ISIN; informational (changes at splits) | bhavcopy / Kite |
| `trade_date` | the IST trading date (`date`, no time) | — |

`company_key` can change when a company renames again. Research outputs are regenerated, so that is fine there.
Operational rows therefore store the **facts as traded** (`symbol`, `isin`, Kite `instrument_token`) and resolve
`company_key` when reading, never the other way round.

## 3. Research store (files, `data/` on prod; git-ignored)

**Raw — immutable downloads, never edited:**
`bhavcopy_legacy/`, `bhavcopy_udiff/`, `corporate_actions/raw/`, `symbol_changes/symbolchange.csv`, `trendlyne/`
(ST-005); MyInvestIQ's `data/bhavcopy/` and `data/indices/` read-only.

**Derived — rebuildable by a script, each with a validator:**

| File | Grain | Key columns | Built by |
|---|---|---|---|
| `corporate_actions/history.csv` | action | symbol, ex_date, action_type, adjustment_factor | ST-003 |
| `panel/equity_daily.parquet` | equity x trading day | trade_date, series_id, company_key, symbol, isin, series, open, high, low, close, prev_close, volume, traded_value | ST-004 |
| `universe/membership.csv` | rebalance x member | cutoff_date, effective_from, series_id, company_key, symbol, rank, median_traded_value, trading_freq | ST-004 |
| `features/<set>/<date>.parquet` | stock x day | series_id, trade_date, feature columns | ST-010 |
| `backtests/<run_id>/` | one run | `config.yaml`, `trades.parquet`, `equity_curve.parquet`, `metrics.json` | ST-010 |

Rules: prices in the panel are **raw**; split/bonus adjustment is applied at read time from `history.csv` +
`config/ca_overrides.csv`, so a corrected factor never needs a panel rebuild. Point-in-time: a row dated D uses only
data available at D's close. Parquet (pyarrow), snappy compression, partitioned by year if the file grows past ~1 GB.

**Curated, in git (`config/`):** `ca_overrides.csv`, `ca_exceptions.csv`, `symbol_changes_extra.csv`,
`symbol_exceptions.csv`, later `guardrails.yaml` and `strategies/*.yaml`. Every row has a reason.

## 4. Operational store (PostgreSQL `strategy_trader`, ST-012)

Conventions: `timestamptz` stored in UTC, shown in IST; money `numeric(14,2)` INR; prices `numeric(12,2)`; quantities
`integer`; every table has `id bigserial`, `created_at`; status changes are new rows in an events table, not silent
updates; raw broker payloads kept as `jsonb`; schema changes only through numbered SQL migrations in
`database/migrations/`.

| Table | One row per | Main columns | First used by |
|---|---|---|---|
| `strategies` | strategy version | name, version, config (jsonb), status, approved_by, approved_at | ST-010/011 |
| `models` | model version | kind (regime / allocator / ranker), version, artifact path, metrics (jsonb), gate, approved_at | ML phase |
| `signals` | stock x run | run_date, strategy_id, model_id, symbol, isin, score, rank, rationale (jsonb) | ST-011 |
| `proposals` | proposed buy | signal_id, qty, limit_price, stop_price, amount, status (pending / approved / rejected / expired), decided_at, telegram ids | ST-011 |
| `orders` | Kite order | proposal_id, kite_order_id, side, qty, price, type, status, filled_qty, avg_price, raw (jsonb) | ST-006/007 |
| `gtt_orders` | Kite GTT | position_id, kite_gtt_id, trigger_price, limit_price, status | ST-009 |
| `positions` | holding lot | symbol, isin, strategy_id, entry date/price/qty, exit date/price/qty, status, realised_pnl | ST-009 |
| `order_events` | status change | order_id / gtt_id / proposal_id, from_status, to_status, at, detail (jsonb) | ST-006+ |
| `guardrail_events` | guardrail check | rule, decision (allow / block), limits snapshot (jsonb), context (jsonb) | ST-008 |
| `daily_snapshots` | trading day | invested_at_cost, market_value, realised / unrealised pnl, rolling 12-month loss %, tier (ok / alert / no-buys / halt) | ST-008/009 |
| `reconciliations` | day x difference | Kite holdings / GTTs vs `positions` / `gtt_orders` | ST-009 |
| `audit_log` | action | actor (system / Rakesh), action, details (jsonb); append-only | all |

Read-only from MyInvestIQ (`portfolio_watch`, via a read-only role): `corporate_actions`, `fii_daily_flow` (ST-012).

## 5. Flow

```
NSE / Kite / Trendlyne --> raw files --> derived files (panel, universe, features) --> backtests
                                                   |
                         approved strategy / model version
                                                   v
             daily run --> signals --> proposals --(Rakesh approves)--> guardrails --> orders --> positions / GTT
                                                   ^                                        |
                                    daily_snapshots, reconciliations  <---------------------+
```

## 6. Open for ST-012
Exact column types and constraints, indexes, roles (app writer, read-only reporting), retention of raw broker
payloads, and whether research outputs the live run needs (the current universe, the latest features) are read from
files or loaded into the database each morning.
