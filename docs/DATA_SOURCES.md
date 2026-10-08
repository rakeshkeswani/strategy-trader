# DATA_SOURCES.md — where data comes from, and its traps

Present tense. Each trap here was hit for real; the date says when.

## NSE CM bhavcopy — legacy format (until 2024-07-05)

- URL: `https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip`
  (MON uppercase, e.g. `JAN`). Plain GET with a browser User-Agent, no cookies.
- `archives.nseindia.com` (no `ns` prefix) returns **403 for 2014** — use `nsearchives.` only (2026-10-08).
- Columns: `SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN`
  (+ trailing empty column). `TOTTRDVAL` is in rupees.
- `TIMESTAMP` is normally `02-JAN-2014` but **2020-07-13 prints `13-Jul-20`** — parse dates, never compare strings (2026-10-08).
- A missing date (holiday, weekend, bad URL) returns 404. Weekend special sessions exist (Budget Saturdays,
  some Muhurat, 2024 Saturday sessions) — the weekday sweep does not try them; fetch with `--dates`.
- Equity series used: `EQ`, `BE`. Raw prices — not adjusted for splits/bonuses.

## NSE CM bhavcopy — UDiFF format (from 2024-01-01)

- URL: `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`
- Column map from legacy: SYMBOL→`TckrSymb`, SERIES→`SctySrs`, OPEN→`OpnPric`, HIGH→`HghPric`, LOW→`LwPric`,
  CLOSE→`ClsPric`, PREVCLOSE→`PrvsClsgPric`, TOTTRDQTY→`TtlTradgVol`, TOTTRDVAL→`TtlTrfVal`.
- Verified identical to legacy over 2024-01-01..2024-07-05: 125 dates, 267,237 symbol-days, 0 mismatches,
  same traded-value units (2026-10-08).
- `PrvsClsgPric` is the RAW previous close — not adjusted across an ex-date (MyInvestIQ BHAVCOPY_FINDINGS.md).
- BSE's file for a holiday is an **HTML page with HTTP 200** — MyInvestIQ's fetcher records it as ERROR; harmless.
- MyInvestIQ's own archive holds only 5 dates before 2025-08-28; the rest of 2024–Aug 2025 is in
  strategy-trader's `data/bhavcopy_udiff/`. **Do not backfill MyInvestIQ's archive** — see vault/LEARNINGS.md 2026-10-08.

## Reading prices

`core/prices.py read_ohlcv_for_date(d)`: `d < 2024-01-01` → legacy archive; else MyInvestIQ's UDiFF archive,
then `UDIFF_GAP_DIR`. Returns `{symbol: {open, high, low, close, prev_close, volume, traded_value, isin, series, source}}`.
A missing file raises `BhavcopyDateMissingError`; a missing symbol is simply absent.

## Corporate actions (ST-003 — design)

NSE `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`.
History reaches at least 2015 (MyInvestIQ CORPORATE_ACTIONS_FINDINGS.md). Traps: NCRPS "Bonus" subjects are not
equity; the feed's `isin` is unreliable across splits; store only ex_date < today.
MyInvestIQ's `corporate_actions` table covered only 2025-08-29..2026-08-25 (100 rows), last fetched 2026-08-28.

## Calendar cross-check

yfinance `^NSEI` daily dates — used only to explain 404 weekdays. It lacks some real sessions
(New Year's Day, Muhurat, special sessions, a few random days); NSE's own files are the authority.
