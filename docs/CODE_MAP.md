# CODE_MAP.md — modules and what calls what

Present tense. Update when a module, entry point or call chain changes.

## Entry points

| Command | Purpose | Writes |
|---|---|---|
| `python -m ingestion.fetch_legacy_bhavcopy [--start --end --dates --retry-404 --force]` | one-time legacy bhavcopy download | `LEGACY_BHAVCOPY_DIR` (only writer), `LOG_DIR` |
| `python -m scripts.validate_legacy_bhavcopy [--skip-overlap --skip-calendar]` | ST-002 acceptance checks | `LOG_DIR` |
| `python -m scripts.relocate_udiff_gap [--go]` | historical one-off (2026-10-08) — do not re-run | — |
| `python -m pytest -q tests` | unit tests (no network) | — |

## Modules

| Module | Role |
|---|---|
| `core/config.py` | loads `.env`; all paths (`LEGACY_BHAVCOPY_DIR`, `BHAVCOPY_ARCHIVE_DIR`, `UDIFF_GAP_DIR`, `LOG_DIR`) |
| `core/legacy_bhavcopy_reader.py` | parse/read legacy zips; `BhavcopyDateMissingError`, `BhavcopyFormatError` |
| `core/udiff_bhavcopy_reader.py` | parse/read UDiFF zips (copied from MyInvestIQ); MyInvestIQ archive first, then gap dir |
| `core/prices.py` | `read_ohlcv_for_date()` — routes by date |
| `ingestion/fetch_legacy_bhavcopy.py` | downloader; `validate_payload()` gates every write |
| `scripts/validate_legacy_bhavcopy.py` | overlap + calendar checks |

## Call chain

```
core.prices.read_ohlcv_for_date(d)
  ├─ d < 2024-01-01 → core.legacy_bhavcopy_reader.read_ohlcv_for_date → parse_legacy_csv
  └─ else           → core.udiff_bhavcopy_reader.read_ohlcv_for_date → _find_file (MyInvestIQ, then gap) → parse_udiff_csv
```
