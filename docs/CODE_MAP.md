# CODE_MAP.md — modules and what calls what

Present tense. Update when a module, entry point or call chain changes.

## Entry points

| Command | Purpose | Writes |
|---|---|---|
| `python -m ingestion.fetch_legacy_bhavcopy [--start --end --dates --retry-404 --force]` | one-time legacy bhavcopy download | `LEGACY_BHAVCOPY_DIR` (only writer), `LOG_DIR` |
| `python -m scripts.validate_legacy_bhavcopy [--skip-overlap --skip-calendar]` | ST-002 acceptance checks | `LOG_DIR` |
| `python -m scripts.relocate_udiff_gap [--go]` | historical one-off (2026-10-08) — do not re-run | — |
| `python -m ingestion.fetch_symbol_changes` | snapshot of NSE's symbol-change list (run before the CA fetch) | `SYMBOL_CHANGES_DIR` |
| `python -m ingestion.fetch_corporate_actions_history [--years Y.. --force]` | one-time CA history 2014..2025-08-25; reuses `raw/` | `CORPORATE_ACTIONS_DIR`, `LOG_DIR` |
| `python -m scripts.validate_corporate_actions [--start --end --skip-spot]` | ST-003 acceptance checks (jump scan over prices) | `LOG_DIR` |
| `python -m pytest -q tests` | unit tests (no network) | — |

## Modules

| Module | Role |
|---|---|
| `core/config.py` | loads `.env`; all paths (`LEGACY_BHAVCOPY_DIR`, `BHAVCOPY_ARCHIVE_DIR`, `UDIFF_GAP_DIR`, `LOG_DIR`, `CORPORATE_ACTIONS_DIR`, `SYMBOL_CHANGES_DIR`) |
| `core/legacy_bhavcopy_reader.py` | parse/read legacy zips; `BhavcopyDateMissingError`, `BhavcopyFormatError` |
| `core/udiff_bhavcopy_reader.py` | parse/read UDiFF zips (copied from MyInvestIQ); MyInvestIQ archive first, then gap dir |
| `core/prices.py` | `read_ohlcv_for_date()` — routes by date |
| `ingestion/fetch_legacy_bhavcopy.py` | downloader; `validate_payload()` gates every write |
| `scripts/validate_legacy_bhavcopy.py` | overlap + calendar checks |
| `core/symbol_changes.py` | `load_changes()` (NSE snapshot + `config/symbol_changes_extra.csv`), `symbol_on(changes, symbol, date)` |
| `core/corporate_actions.py` | `parse_subject()`, `classify_records()` (feed → rows under the symbol in use on ex_date), `write_history()`, `load_history()` (+ `config/ca_overrides.csv`), `cumulative_factor()`, `adjust_price()`, `adjust_volume()` |
| `ingestion/fetch_symbol_changes.py` | downloads `symbolchange.csv`; keeps the previous snapshot |
| `ingestion/fetch_corporate_actions_history.py` | one call per year, raw JSON kept, `history.csv` written; fails on unclassified subjects |
| `scripts/validate_corporate_actions.py` | feed re-parse, jump scan (equities), PREVCLOSE probe, yfinance spot check; reads `config/ca_exceptions.csv` |

## Curated config files (in git, every row has a reason)

| File | Read by | Purpose |
|---|---|---|
| `config/ca_overrides.csv` | `load_history()` | VOID a feed action that did not change the equity scale / ADD a missing factor; a stale VOID raises |
| `config/symbol_changes_extra.csv` | `load_changes()` | renames missing from NSE's list (same 4-column format) |
| `config/ca_exceptions.csv` | validator only | explains genuine crashes (`drop`) and records capital-reduction decisions (`review`) |

## Call chain

```
core.prices.read_ohlcv_for_date(d)
  ├─ d < 2024-01-01 → core.legacy_bhavcopy_reader.read_ohlcv_for_date → parse_legacy_csv
  └─ else           → core.udiff_bhavcopy_reader.read_ohlcv_for_date → _find_file (MyInvestIQ, then gap) → parse_udiff_csv

fetch_corporate_actions_history: raw/<YYYY>.json → classify_records(records, as_of, load_changes())
  → parse_subject (per "/"-part) → symbol_on (feed symbol → symbol on ex_date) → write_history(history.csv)

adjusting a price: load_history() [history.csv + ca_overrides.csv] → cumulative_factor(table, symbol, from, to)
  → adjust_price = price / factor ; adjust_volume = volume * factor   (price dated before ex_date is divided)
```
