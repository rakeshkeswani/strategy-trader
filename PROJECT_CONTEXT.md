# PROJECT_CONTEXT.md — AI Strategy Trading System

Single source of truth for technical context. The plan itself lives at:
https://claude.ai/code/artifact/81d40d11-41d6-4d01-9ee2-fec2ac5a846e

Last updated: 2026-10-08 (ST-001)

## Status

Phase 0 (Foundations) — scaffold only. No code, no database, no Kite app yet.

## Phases

| Phase | What | Gate to exit |
|---|---|---|
| P0, weeks 1-3 | Kite Connect app, Mumbai VM order gateway, bhavcopy backfill, guardrails + GTTs, baseline backtest | Gate 1: 1-share test orders, GTTs and reconciliation work |
| P1, from week 4 | Live on baseline momentum rule, Rs 10k/week; ML research in shadow | Gate 2: ML beats baseline in backtest and shadow |
| P2 | ML-driven proposals, baseline as fallback | Gate 3: 3 months inside loss tiers |
| P3 | Review and scale (static IP options, cap changes by Rakesh) | ongoing |

## Infrastructure

| Component | Where | Notes |
|---|---|---|
| App + jobs | rkneo50q (192.168.0.250) | Scheduled by n8n |
| Database | Existing PostgreSQL 16 on rkneo50q | Separate database for this project (name TBD, ST-012) |
| Order gateway | Small Mumbai cloud VM, static IP | Linked over Tailscale; SEBI requires static IP for API orders (ST-007) |
| Broker | Zerodha Kite Connect, Rs 500/month plan | Daily login (access token expires daily) |
| Notifications / approvals | Telegram | Proposal cards with Approve / Reject / Edit (ST-011) |

## Data Sources

| Data | Source | Location |
|---|---|---|
| Daily prices 2024-01-01 onward (UDiFF) | MyInvestIQ archive, read-only | `BHAVCOPY_ARCHIVE_DIR` (prod: myinvestiq `data/bhavcopy/`) |
| Daily prices 2024-01-03 to 2025-08-27 (UDiFF) | One-time fetch by MyInvestIQ's own fetcher on 2026-10-08, relocated out of its archive (it would have changed MyInvestIQ's Sunday price-history job) | `/home/rakeshbk/myinvestiq/data/strategy_trader/bhavcopy_udiff/` via `UDIFF_GAP_DIR`; 403 NSE + 403 BSE files + manifest.csv |
| Index closes | MyInvestIQ archive, read-only | `INDEX_ARCHIVE_DIR` (prod: myinvestiq `data/indices/`) |
| Daily prices 2014 to 2024-07-05 (legacy format) | `https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip` — verified 2026-10-08 for 2014, 2016, 2019, 2023, Jul 2024 (`archives.` host 403s on 2014) | `/home/rakeshbk/myinvestiq/data/bhavcopy_legacy/` via `LEGACY_BHAVCOPY_DIR`; one-time download, this project is the only writer (ST-002) |
| Corporate actions (splits, bonuses) | NSE corporate actions; reuse MyInvestIQ `core/corporate_actions.py` | ST-003 |
| Fundamentals, sector | Trendlyne Nifty 500 Data Downloader export, dropped weekly by Rakesh | `TRENDLYNE_DROP_DIR` on rkneo50q, network share from Windows (ST-005) |
| FII flows | MyInvestIQ `fii_daily_flow` table | read-only |

Jan-Jul 2024 exists in both formats — used to validate the legacy reader (ST-002).

## Reused from MyInvestIQ (read, don't modify)

- `core/bhavcopy_reader.py`, `core/index_reader.py`, `core/trading_calendar.py`,
  `core/corporate_actions.py` — copy or import; decision in ST-002.
- `docs/BHAVCOPY_FINDINGS.md`, `docs/INDEX_ARCHIVE_FINDINGS.md` — parsing traps already solved.
