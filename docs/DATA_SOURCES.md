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
- **MyInvestIQ's fetcher skips weekends, so weekend special sessions are missing from UDiFF too.** 2025-02-01
  (Budget Saturday) was absent until fetched by hand (2026-10-11). Any later weekend session in MyInvestIQ's
  archive may be missing the same way — the full-range check through `core.prices` finds them.
- MyInvestIQ's own archive holds only 5 dates before 2025-08-28; the rest of 2024–Aug 2025 is in
  strategy-trader's `data/bhavcopy_udiff/`. **Do not backfill MyInvestIQ's archive** — see vault/LEARNINGS.md 2026-10-08.

## Reading prices

`core/prices.py read_ohlcv_for_date(d)`: `d < 2024-01-01` → legacy archive; else MyInvestIQ's UDiFF archive,
then `UDIFF_GAP_DIR`. Returns `{symbol: {open, high, low, close, prev_close, volume, traded_value, isin, series, source}}`.
A missing file raises `BhavcopyDateMissingError`; a missing symbol is simply absent.

## Corporate actions (ST-003)

NSE `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`.
No cookie needed. One call per calendar year is complete (2018 Q1 from a year call = a Q1-only call, 192 records)
and history reaches 2013 (2026-10-11). strategy-trader holds 2014-01-01..2025-08-25 (`data/corporate_actions/`);
MyInvestIQ owns 2025-08-26 onward (its `corporate_actions` table, last fetched 2026-08-28 — ST-012 merges it).
Scope: BONUS `X:Y` → factor (Y+X)/Y; SPLIT face value A→B → A/B; CONSOLIDATION A→B → A/B (<1).
Traps, each hit for real (2026-10-11 unless noted):
- **The feed files past actions under the company's CURRENT symbol**; bhavcopy has the symbol in use then
  (INFIBEAM's 2021 bonus is under CCAVENUE). 55 of 805 actions 2014-2025 needed mapping back (`core/symbol_changes.py`).
- **Subjects are free text and messy before ~2019:** several actions in one subject ("Bonus 1:1 / Face Value Split
  From Rs 10/- To Rs 5/-", "... And Face Value Split ..."), "Bonus 1 : 1", "Bonus Issue", "Sub-Division From",
  "Rs.10/-", "Re.1/-", "To Face Value 2/-". MyInvestIQ's whole-subject regexes miss ~1/3 of 2014's. "Rs 10/-"
  contains "/", so subjects split into parts only on "/" not followed by "-".
- **"Bonus" that is not equity:** NCRPS, preference shares, debentures (NTPC 2015, BRITANNIA 2019/2021, TVSMOTOR
  2025). Excluded by name.
- **Capital reductions** have no automatic factor — sent to review (5 in 2014-2025, all decided in
  `config/ca_exceptions.csv`).
- **The feed can be wrong:** DVL "Bonus 1:2" 2021-08-05 never moved the price (same ISIN) — voided in
  `config/ca_overrides.csv`.
- The feed's `isin` is unreliable across splits (MyInvestIQ Q6) — join by symbol. `caBroadcastDate` is always null,
  so publication timing is unknown — store only ex_date < run date (MyInvestIQ Q7).
- Legacy bhavcopy PREVCLOSE is RAW on ex-dates (571/575), like UDiFF's — no independent factor from it.

## NSE symbol changes (ST-003; ST-013 builds on it)

`https://nsearchives.nseindia.com/content/equities/symbolchange.csv` — no header; rows are
`<company, may contain commas>,<old>,<new>,<DD-MON-YYYY>`; from that date the new symbol trades. 1,056 renames,
2003 onward (2026-10-11), mutual-fund schemes included. **Incomplete:** PHILIPCARB→PCBL (2022-01-13) and
INTEGRA→ESSENTIA (2022-03-07) are missing — found by the validator (an action never seen in prices + a drop at the
split ratio) and added to `config/symbol_changes_extra.csv` from bhavcopy first/last dates.

## Calendar cross-check

yfinance `^NSEI` daily dates — used to explain 404 weekdays, and `<SYMBOL>.NS` closes (split/bonus-adjusted) for the
ST-003 spot check (5/5 match). It lacks some real sessions
(New Year's Day, Muhurat, special sessions, a few random days); NSE's own files are the authority.
