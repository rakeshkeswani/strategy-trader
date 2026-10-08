# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

**AI Strategy Trading System** — trades Rakesh's own Zerodha Kite account using rule-based
stock-selection strategies (momentum, RSI pullback, breakout, low-volatility quality, sector
strength) on the Nifty 500. ML decides which strategies get capital and tunes their settings
within fixed bounds. Rakesh approves every buy; the system manages exits through GTT stop-losses.

- Plan (canonical): https://claude.ai/code/artifact/81d40d11-41d6-4d01-9ee2-fec2ac5a846e
- Technical context: `PROJECT_CONTEXT.md` — Issue tracker: `TECH_DEBT.md` (ST- prefix)
- Personal use only. Not investment advice.

## Objective (overrides everything below it)

Minimise losses and maximise profits over a rolling 12-month forward window, applied in order:
1. Worst rolling 12-month loss <= 20% (Rs 20,000 on the Rs 1,00,000 cap) — hard reject otherwise
2. Then highest median rolling 12-month return after costs and tax, walk-forward, out-of-sample
3. Tie-break: better return-to-drawdown ratio
4. Must beat Nifty 500 buy-and-hold over the same windows

ML and code may never change this objective.

## Working Agreements (follow every session)

1. **Propose the approach and get approval BEFORE writing any code**
2. **Git: Claude provides commands only — Rakesh executes them**
3. **Ubuntu (rkneo50q) is strictly PROD — test on Windows dev first**
4. **One issue at a time** — finish and test before moving on
5. **Always check the actual DB schema before writing queries** — never assume column names
6. **ST items marked Resolved ONLY after Rakesh gives a prod sign-off date**
7. **`.env` is never committed**
8. **`TECH_DEBT.md` is the canonical issue tracker**
9. **Understand current design before enhancing** — ask "what exists now?" first
10. **Review actual changed files, not summaries**

## Trading Safety Rules (non-negotiable)

- Every order goes through the guardrail service. No other module may call Kite order APIs.
- `config/guardrails.yaml` is edited only by Rakesh. Code and ML read it; they never write it.
- Limit orders only, CNC equity only. No F&O, MTF/margin, SME or ASM/GSM stocks.
- Every holding must have a live GTT stop-loss. Stops only move up.
- No new ML model or strategy setting goes live without Rakesh's approval.
- Never log or print Kite access tokens, API secrets or Telegram tokens.
- Any change touching `execution/` needs a dry-run test against Kite before prod.

## Agreed Limits (mirror of the plan; guardrails.yaml is the enforced copy)

| Limit | Value |
|---|---|
| Capital cap | Rs 1,00,000 at cost of open positions |
| New buys | Rs 10,000 per week |
| Position size | ~Rs 10,000, max Rs 12,000 |
| Risk per trade | <= Rs 1,000 entry-to-stop |
| Per strategy / per sector | <= Rs 40,000 / <= Rs 25,000; max 10 positions |
| Loss tiers (trailing 12m) | 10% alert, 15% no new buys, 20% full halt |
| Universe | Nifty 500 |
| Holding period | Positional, 1-6 months |

## Data Rules

- MyInvestIQ's archives (UDiFF bhavcopy from 2024-01-01, index closes) are **read-only**,
  via `BHAVCOPY_ARCHIVE_DIR` / `INDEX_ARCHIVE_DIR`. Never write to them.
- Legacy bhavcopy (2014 to Jul 2024, `nsearchives.nseindia.com/content/historical/EQUITIES/`)
  lives in this project's own archive (`LEGACY_BHAVCOPY_DIR`), on rkneo50q.
- Join prices by symbol, never ISIN (see MyInvestIQ `core/bhavcopy_reader.py`).
- Returns are price return (no dividends) unless a decision changes this.
- Backtests: walk-forward only; 2024-2026 held out until a strategy's final check.
- News/LLM scores are never back-filled for backtests (look-ahead leakage).

## Code Standards

Follow MyInvestIQ's standards: specific exception types (no bare `except`), `logging` not
`print`, docstrings and type hints on new functions, parameterized SQL only, context managers
for DB connections, None-checks on fetch results.

## Environments

| | Windows dev | Ubuntu prod (rkneo50q) |
|---|---|---|
| Repo | `C:\RKOneDrive\OneDrive\Work\RKInvesting` | `/home/rakeshbk/strategy-trader` (proposed) |
| Data | reads prod share | `/home/rakeshbk/strategy-trader-data/` |
