# TODO.md — open items and resume point

Read at session start (after `TECH_DEBT.md` and the tail of `SESSION_LOG.md`). Tick/remove as done.
Last updated: 2026-10-11 (ST-001/002/014 resolved; ST-015 finishing).

## Resume here (new conversation)
1. ~~Sign-off ST-001, ST-002, ST-014~~ — all Resolved, prod confirmed 2026-10-11.
2. **ST-015 housekeeping** (branch `st/ST-015-housekeeping`):
   - [x] status changes from item 1
   - [x] CLAUDE.md file-reading rules already list `TODO.md`
   - [ ] `.gitattributes` (`* text=auto eol=lf`) and renormalise once — ends CRLF warnings and diff noise
   - [ ] CLAUDE.md: `git --no-pager`; merges with `-m`; `git branch --list` before `switch -c`
   - [ ] merge, prod pull, prod `git status` clean → Rakesh sign-off
2a. **Backup record (moved out of ST-015, 2026-10-11):** once item 3 is verified, add the mirror to `docs/CONFIG.md`
   and note it in the homelab map — under whichever ST is open then.
3. **Backup (homelab project, not here).** Paste this handover there:
   > Add strategy-trader to the backup chain on RKNeo50Q. Source `/home/rakeshbk/strategy-trader` (code on GitHub;
   > `data/` = one-time NSE downloads 2014–2025, ~300 MB, hard to replace). Exclude `venv/`, `__pycache__/`,
   > `.pytest_cache/`. Destination `/mnt/rkfspool/daily/rkneo50q/strategy-trader/` so the 01:00 Kopia snapshot
   > covers it. Suggested trigger: existing 23:30 n8n workflow after FFS Job 2 (FFS Job 3 or rsync — homelab's
   > call). Caution: `/mnt/rkfspool/daily` is the read-write rkfspool share; `.env` will later hold Kite keys —
   > plan to exclude `.env` from the mirror and back it up another way. Add a daily freshness check for the mirror
   > to `homelab-health.sh`. The map already has the strategy-trader service and a "NOT YET IN THE BACKUP CHAIN"
   > note (`patch_2026_10_08.py`); update backup line, schedules, pool folders once verified.
4. **ST-003 corporate actions — final design**, then branch `st/ST-003-corporate-actions`. Agreed so far is in
   `tech-debt/ST-003.md` (MyInvestIQ owns ongoing CA; strategy-trader fetches 2014..2025-08 history once into
   `data/corporate_actions/`; merge, MyInvestIQ wins; read-only DB role; jump scan / PREVCLOSE / yfinance checks).
5. Then ST-013 (symbol changes via ISIN) → ST-004 (point-in-time top 500) → ST-010 (baseline momentum backtest).

## Rakesh — outside this repo
- [ ] `cd ~/myinvestiq && git pull` on prod (picks up `98255d6`) if not done
- [ ] MyInvestIQ TD: daily corporate-actions fetch in the 18:00 job + backfill its table from 2025-08-26
      (its table stopped at 2025-08-29..2026-08-25, last fetched 2026-08-28 — splits since then are unadjusted
      in MyInvestIQ too)
- [ ] MyInvestIQ: TD-247 lint ERROR (status Open but merged) blocks commits — fix status or confirm the lint misread
- [ ] Optional: `sudo apt install tmux` on rkneo50q; tablet SSH = Tailscale app + Termius/JuiceSSH to
      `100.103.189.15:22` as rakeshbk
- [ ] Optional: `git config --global core.editor notepad`

## Notes to carry into later STs
- Live system (ST-008 guardrails / news): ST-003 found 6 genuine one-day crashes 2015-2020 (UNITECH, DHFL, INFIBEAM,
  JETAIRWAYS, YESBANK, IDEA; `config/ca_exceptions.csv`), all news-driven (rumours, regulator action, insolvency).
  Rakesh 2026-10-11: the final system must handle these -- e.g. gap-down / circuit handling for GTT stops, and
  news checks before buys.
- ST-004: EASTSILK (and any symbol with a capital reduction during a suspension) has an incomparable price series
  across the gap; universe filters keep penny stocks out anyway.
- ST-005 (Trendlyne): the `[strategy-trader]` Samba share is read-only (Samba default), so the weekly drop needs a
  writable path — e.g. a folder on the rkfspool share (Y:) that the importer reads.
- ST-006 (Kite): keys in `.env` → exclude `.env` from the backup mirror (see backup handover).
- ST-012: read-only Postgres role on `portfolio_watch` for `corporate_actions` and `fii_daily_flow`.
- Weekend special sessions (e.g. Sunday Muhurat) may be missing from the legacy archive — accepted, negligible.
- Plan doc (Claude doc): "AI Strategy Trading System — Research & Implementation Plan".
