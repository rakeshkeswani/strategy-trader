# TECH_DEBT.md — issue tracker (ST- prefix)

Status values: Open, In progress, In review, Resolved (Resolved needs a prod_confirmed date from Rakesh).

| ID | Title | Phase | Status |
|---|---|---|---|
| ST-001 | Project scaffold: CLAUDE.md, PROJECT_CONTEXT.md, TECH_DEBT.md, .gitignore, .env.example, folders | P0 | In review |
| ST-002 | Legacy bhavcopy backfill 2014 to Jul 2024 (nsearchives, throttled) + reader validated against UDiFF Jan-Jul 2024 | P0 | In review |
| ST-003 | Split/bonus adjustment for every Nifty 500 stock (corporate actions history) | P0 | Open |
| ST-004 | Point-in-time universe: top 500 by traded value per quarter, delisted stocks kept | P0 | Open |
| ST-005 | Trendlyne weekly drop folder on rkneo50q, Windows network share, importer | P0 | Open |
| ST-006 | Kite Connect app and daily login flow | P0 | Open |
| ST-007 | Mumbai cloud VM order gateway with static IP, linked over Tailscale | P0 | Open |
| ST-008 | Guardrail service + config/guardrails.yaml with agreed limits | P0 | Open |
| ST-009 | GTT stop-loss placement, trailing, daily reconciliation | P0 | Open |
| ST-010 | Baseline momentum strategy config + quick backtest | P0 | Open |
| ST-011 | Telegram proposal and approval flow | P0 | Open |
| ST-012 | Project database on existing PostgreSQL (name, schema) | P0 | Open |
| ST-013 | Symbol changes: stitch renamed symbols into one history (same ISIN, old symbol ends / new begins next session); cross-check NSE symbol-change list | P0 | Open |

## ST-001 — Project scaffold
- Opened: 2026-10-08
- Scope: documentation and folder skeleton only; no code.
- prod_confirmed: —

## ST-002 — Legacy bhavcopy backfill (2014-01-01 to 2024-07-05)
- Opened: 2026-10-08
- Decisions: start 2014; copy (not import) MyInvestIQ's UDiFF parsing; archive at
  `/home/rakeshbk/myinvestiq/data/bhavcopy_legacy/` (needs `data/bhavcopy_legacy/` in MyInvestIQ's .gitignore first).
- Code:
  - `ingestion/fetch_legacy_bhavcopy.py` — one-time downloader, validated writes, manifest.csv, refuses network-share paths
  - `core/legacy_bhavcopy_reader.py` — legacy parser/reader (EQ/BE, adds traded_value, isin)
  - `core/udiff_bhavcopy_reader.py` — copy of MyInvestIQ's UDiFF parsing (NSE only, read-only)
  - `core/prices.py` — one entry point: < 2024-01-01 legacy, >= 2024-01-01 UDiFF
  - `scripts/validate_legacy_bhavcopy.py` — overlap check (Jan-Jul 2024) + calendar check (yfinance ^NSEI)
  - `tests/test_legacy_bhavcopy.py` — 9 unit tests, synthetic files, no network
- Acceptance: validate script PASS — zero OHLC/volume mismatches in the overlap, every 404 weekday a
  Nifty non-trading day, no un-fetched weekend sessions, no ERROR/INVALID rows.
- Dev tests: 10 passed (2026-10-08)
- Prod run 2026-10-08: 2,590 legacy files OK (2014-01-01..2024-07-05), 153 weekday 404s all NSE holidays,
  1 INVALID (2020-07-13, 2-digit-year TIMESTAMP) fixed and re-fetched; 7 special weekend sessions fetched
  (2015-02-28, 2020-02-01, 2020-11-14, 2023-11-12, 2024-01-20, 2024-03-02, 2024-05-18).
- UDiFF gap 2024-01-03..2025-08-27: fetched with MyInvestIQ's fetcher, then moved out of its archive into
  data/strategy_trader/bhavcopy_udiff/ (scripts/relocate_udiff_gap.py) so MyInvestIQ's behaviour is unchanged.
- Validation PASS 2026-10-08: overlap 125 dates, 267,237 symbol-days, 0 mismatches; traded_value units equal.
- Known limitation: other weekend special sessions (e.g. Sunday Muhurat) may be missing; impact negligible.
- prod_confirmed: —
