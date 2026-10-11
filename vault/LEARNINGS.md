# LEARNINGS.md — append-only, newest at the bottom

## 2026-10-08 — "themes" meant two different things
The first plan defined a theme as a sector/narrative basket (defence, railways). Rakesh meant a stock-selection
recipe built from criteria like momentum and RSI. The trade term is **strategy** (rule-based/systematic);
momentum, quality, low-vol are **factors**. Plan rewritten around a strategy library; sectors became a filter.

## 2026-10-08 — the old bhavcopy URL was "dead" only for dates it never had
MyInvestIQ's BHAVCOPY_FINDINGS.md recorded the legacy `cm…bhav.csv.zip` path as dead — but it was probed with a
2026 date, which never existed in that format. Probing pre-2024 dates showed `nsearchives.` serves 2014 onward
(`archives.` 403s on 2014). **A negative probe only covers what it actually asked for.**

## 2026-10-08 — a validation passed on 5 dates
The overlap check passed comparing 5 dates because MyInvestIQ's archive held only 5 dates before 2025-08-28.
"No mismatches" over almost no data looked like success. Now the check fails below 100 dates.
**A pass needs a minimum amount of evidence, not just zero failures.**

## 2026-10-08 — backfilling MyInvestIQ's archive would have changed MyInvestIQ
To fill the Jan 2024–Aug 2025 gap, MyInvestIQ's own fetcher was run into its own archive. Rakesh then asked
whether the archive's start date was a rule. It was not written as one, but `ensure_price_history()` (Sunday) would
have started writing raw 2024–25 rows into `stock_price_history` next to old yfinance-adjusted rows, and the
adjusted view's floor and MyInvestIQ's corporate actions (from 2025-08-29) would not have covered them. The files
and their manifest rows were moved out the same evening, before Sunday. **More data in a shared folder is a
behaviour change for every reader of that folder.** Led to the rule: each project's folder is its own;
shared data is read-only.

## 2026-10-08 — NSE date formats are not consistent
One legacy file (2020-07-13) prints `13-Jul-20` where every other prints `02-JAN-2014`. The fetcher's string
comparison rejected a good file. Dates are now parsed and compared as dates.

## 2026-10-08 — process slips in the first session
Commits went straight to `main` and used `git add .`, against MyInvestIQ's practice. ST-002's Done-when had no
falsifying clause. Corrected under ST-014: branch per ST, explicit file staging, Done-when with a fail condition.

## 2026-10-08 — a commit check that looked like a missing-files bug
`git show HEAD --name-only` in PowerShell listed 22 of 27 files: the pager cut the output. The commit was complete.
Verification commands must not page: use `git --no-pager show`. Also `git merge --no-ff` without `-m` opens vim.

## 2026-10-08 — backups follow the pool, not the app
Kopia snapshots only `/mnt/rkfspool/daily`; apps reach it via a nightly mirror (n8n → pg_dump → FFS). A new app
folder is NOT backed up until something mirrors it there. The homelab project owns that chain.

## 2026-10-11 — a validator PASS that covered half the range
`validate_legacy_bhavcopy` passed (0 gaps, 0 weekend sessions missing), but its weekend check only looked at the
legacy archive (2014..Jul 2024). ST-002's Done-when said "any trading day 2014..today", which no script checked.
Running every yfinance ^NSEI date through `core.prices.read_ohlcv_for_date()` found Saturday 2025-02-01 (Budget
session) missing from the UDiFF gap set — MyInvestIQ's fetcher skips weekends. **Check the Done-when through the
same entry point the rest of the code uses, over the whole range it promises.**

## 2026-10-11 — a branch that already existed put a commit on main
`git switch -c st/ST-015-housekeeping` failed because the branch existed (made and merged at the last session
close); the next commands ran on `main`. Fixed before push with `git branch -f` + `git reset --keep origin/main`.
Separately, three uncommitted edits in the Windows working copy reverted to their committed text with no conflict
copy (cause unknown; OneDrive suspected). **Check the branch name in the output before committing, and confirm
`git status` lists every file expected before `git add`.**
