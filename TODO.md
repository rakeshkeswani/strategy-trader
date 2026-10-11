# TODO.md — open items and resume point

Read at session start (after `TECH_DEBT.md` and the tail of `SESSION_LOG.md`). Tick/remove as done.
Last updated: 2026-10-11 evening (session close: ST-001/002/003/013/014/015 resolved; ST-004 waiting on the data model).

## Resume here (new conversation)
1. **Rakesh: review and approve `docs/DATA_MODEL.md`** (proposal, commit `fa316fb`). Two stores (research files /
   operational Postgres), shared identifiers (company_key, series_id, symbol, isin, trade_date), research file
   schemas, 12 Postgres tables. ST-004 code waits on it.
2. **ST-004 point-in-time universe** — branch `st/ST-004-universe` (open). Design in `tech-debt/ST-004.md` (Nifty 500
   review alignment: cut-off last trading day Jan/Jul, 6 months, >= 90% trading days, effective April/October;
   rank by median traded value; overlap threshold agreed after measuring). First step: `ingestion/build_price_panel.py`
   (Parquet). pyarrow 26.0.0 installed on prod venv and laptop (2026-10-11); pandas 3.0.6 prod / 3.0.1 laptop.
   Uncommitted on the branch: `requirements.txt` (+pandas, +pyarrow) — commit with the panel builder.
3. Then ST-010 (baseline momentum backtest) → ST-012 (database; before any execution issue) → ST-006/007/008/009/011.
4. Prod SSH paste glitch: `^[[200~` breaks the first/last pasted line. Fix once on prod:
   `echo 'set enable-bracketed-paste off' >> ~/.inputrc` (new session), or update PuTTY.
2a. ~~Backup record~~ — recorded in `docs/CONFIG.md` "Backup" 2026-10-11 (homelab verified 8 checks).
   Done 2026-10-11: `.env` excluded and mirrored copy removed; freshness check 4 in `homelab-health.sh`; mirror
   complete. **Still open (homelab owns, 2026-10-12):** Kopia 01:00 snapshot contains all four data folders and a
   `history.csv` restore matches SHA-256. Record the result in CONFIG.md "Backup" when Rakesh reports it.
3. ~~Backup (homelab project)~~ — done 2026-10-11 (FFS Job 3). Original handover kept for reference:
   > Add strategy-trader to the backup chain on RKNeo50Q. Source `/home/rakeshbk/strategy-trader` (code on GitHub;
   > `data/` = one-time NSE downloads 2014–2025, ~300 MB, hard to replace; since 2026-10-11 also
   > `data/corporate_actions/` and `data/symbol_changes/`, small and re-fetchable). Exclude `venv/`, `__pycache__/`,
   > `.pytest_cache/`. Destination `/mnt/rkfspool/daily/rkneo50q/strategy-trader/` so the 01:00 Kopia snapshot
   > covers it. Suggested trigger: existing 23:30 n8n workflow after FFS Job 2 (FFS Job 3 or rsync — homelab's
   > call). Caution: `/mnt/rkfspool/daily` is the read-write rkfspool share; `.env` will later hold Kite keys —
   > plan to exclude `.env` from the mirror and back it up another way. Add a daily freshness check for the mirror
   > to `homelab-health.sh`. The map already has the strategy-trader service and a "NOT YET IN THE BACKUP CHAIN"
   > note (`patch_2026_10_08.py`); update backup line, schedules, pool folders once verified.
Done 2026-10-11: ST-015 (merge `1a66fc2`), ST-003 corporate actions (merge `bf2f689`), ST-013 rename stitching
(merge `c8a2c77`) — all prod confirmed.

## Rakesh — outside this repo
- [x] MyInvestIQ prod includes `98255d6` (prod HEAD `47c82fb`, pulled 2026-10-10)
- [ ] **MyInvestIQ TD-251 (High, raised 2026-10-11):** daily corporate-actions fetch + backfill from 2025-08-26.
      Their table today: 100 rows, ex_date 2025-08-29..2026-08-25, last fetched 2026-08-28, so **2025-08-26..28 is in
      neither source** until TD-251's backfill. Our history findings are recorded there as design inputs.
      ST-012 depends on it (merge + freshness check).
- [x] MyInvestIQ TD-247 lint: fixed 2026-10-09; lint on main 0 errors, `--no-verify` no longer needed
- [ ] Optional: `sudo apt install tmux` on rkneo50q; tablet SSH = Tailscale app + Termius/JuiceSSH to
      `100.103.189.15:22` as rakeshbk
- [ ] Optional: `git config --global core.editor notepad`

## Notes to carry into later STs
- Live system (ST-008 guardrails / news): ST-003 found 6 genuine one-day crashes 2015-2020 (UNITECH, DHFL, INFIBEAM,
  JETAIRWAYS, YESBANK, IDEA; `config/ca_exceptions.csv`), all news-driven (rumours, regulator action, insolvency).
  Rakesh 2026-10-11: the final system must handle these -- e.g. gap-down / circuit handling for GTT stops, and
  news checks before buys.
- ST-004: EASTSILK (and any symbol with a capital reduction during a suspension) has an incomparable price series
  across the gap; universe filters keep penny stocks out anyway. ST-013 found the same for post-insolvency relistings
  (INDOSOLAR->WAAREEINDO, SPENTEX->CLCIND, NTL->NEUEON): start a new series at a run gap > 30 days with an ISIN change.
  Identities come from `core/securities.py` (key = today's symbol).
- ST-005 (Trendlyne): the `[strategy-trader]` Samba share is read-only (Samba default), so the weekly drop needs a
  writable path — e.g. a folder on the rkfspool share (Y:) that the importer reads.
- ST-006 (Kite): keys in `.env` → exclude `.env` from the backup mirror (see backup handover).
- ST-012: read-only Postgres role on `portfolio_watch` for `corporate_actions` and `fii_daily_flow`.
- Weekend special sessions (e.g. Sunday Muhurat) may be missing from the legacy archive — accepted, negligible.
- Plan doc (Claude doc): "AI Strategy Trading System — Research & Implementation Plan".
