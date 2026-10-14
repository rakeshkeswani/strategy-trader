# SESSION_LOG.md — one entry per session, newest at the bottom

## 2026-10-08 — project start
- Plan written (Claude doc "AI Strategy Trading System — Research & Implementation Plan"); decisions: ₹10k/week,
  ₹1L cap at cost, loss tiers 10/15/20%, positional 1–6 months, Nifty 500, Mumbai VM gateway, new repo,
  model changes need Rakesh's approval, objective = minimise loss / maximise profit over rolling 12 months.
- ST-001 scaffold: `ca79aa3` (main). ST-002: `9eb9bb0`, `8916d84`, `b038a42`, `a17e2aa`, `657a093` (main).
- Prod: legacy bhavcopy 2014–Jul 2024 downloaded; UDiFF gap fetched and relocated; validation PASS.
- MyInvestIQ touched (Rakesh committed): `.gitignore` lines for strategy-trader data (`d4e13fc`, `8810a50`) —
  removed again under ST-014.
- Data moved to `/home/rakeshbk/strategy-trader/data/`; Samba `[strategy-trader]` → X:.
- ST-014 on branch `st/ST-014-workflow-docs`.
- Status at close: ST-001, ST-002 Moved to Prod — pending verification; ST-003 Design proposed; ST-014 In progress.

## 2026-10-08 (evening) → 2026-10-11 — ST-014 merged, homelab, ML learning; conversation closed
- ST-014 merged to main `2869ebb` (branch commit `80325ce`, 27 files verified with `git --no-pager show`). Pulled on prod.
  Fail-check passed: `find ~/myinvestiq -path '*strategy*' -o -name bhavcopy_legacy` printed nothing.
- MyInvestIQ `.gitignore` strategy-trader lines removed: `98255d6` (Rakesh, `--no-verify` because of the unrelated
  TD-247 lint ERROR). Prod `~/myinvestiq` pull still to be confirmed.
- Prod data now in `/home/rakeshbk/strategy-trader/data/{bhavcopy_legacy,bhavcopy_udiff}`, logs in `.../logs/`.
  Samba `[strategy-trader]` (read-only) → Windows X:. `.env` holds BHAVCOPY_ARCHIVE_DIR + LEGACY/UDIFF overrides.
- Homelab map: `C:\RKOneDrive\OneDrive\Work\homelab\patch_2026_10_08.py` added the strategy-trader service, the
  share and X:, marked "NOT YET IN THE BACKUP CHAIN"; lint 0 errors; `homelab_infra.html` rebuilt.
- Backup: how MyInvestIQ is backed up (n8n 23:30 pg_dump + FFS Job 2 → `/mnt/rkfspool/daily/rkneo50q/myinvestiq`,
  Kopia 01:00 snapshots `/mnt/rkfspool/daily`). strategy-trader mirror to be set up from the homelab project
  (handover text in TODO.md). Checked 2026-10-09: `Y:\rkneo50q` holds only myinvestiq.
- Access: Claude can read X:/Y:/Z: through the laptop (Windows-MCP PowerShell) while it is on; cannot run commands on prod.
- Learning (no code): how the ML works, generic ML pipeline mapped to the project, historical data quality,
  features/noise/standard models. Captured in `docs/ML_PRIMER.md`.
- Process notes: merges given with `-m` (no editor); `git --no-pager` for show/log; CRLF noise → `.gitattributes` (ST-015).
- Status at close: ST-001, ST-002, ST-014 Moved to Prod — pending verification (await Rakesh "prod confirmed");
  ST-003 Design proposed; ST-015 Not started. Open items: `TODO.md`.
- Conversation moved: this chat is kept for learning; work resumes in a new conversation from `TODO.md`.

## 2026-10-11 — ST-001/002/014/015 closed; ST-003 and ST-013 built and closed; ST-004 designed
- Sign-offs (prod confirmed 2026-10-11): ST-001, ST-002 (2025-02-01 Budget Saturday fetched; full-range check
  `missing 0`), ST-014, ST-015 (merge `1a66fc2`: .gitattributes LF, git conventions, rule 11 = every command block
  says laptop/prod + full path).
- ST-003 corporate actions 2014..2025-08-25 (merge `bf2f689`): multi-part subject parser, 805 actions, 55 mapped to
  the symbol in use on the ex-date (feed uses today's symbol), DVL voided, 6 news-confirmed crashes, 5 capital
  reductions decided, automatic suspension-gap rule; validator PASS on prod (763/763, spot 5/5).
- ST-013 rename stitching (merge `c8a2c77`): `core/securities.py` (company key = today's symbol), rename validator;
  8 renames missing from NSE's list now in `config/symbol_changes_extra.csv`; 282 confirmed, PASS on prod.
- Backup: homelab added FFS Job 3 + Kopia + freshness check; `.env` excluded. Recorded in `docs/CONFIG.md`.
  Open (homelab, 2026-10-12): Kopia snapshot with all data folders + `history.csv` restore.
- MyInvestIQ: TD-251 raised (daily CA fetch + backfill from 2025-08-26); TD-247 lint fixed; prod has `98255d6`.
- Slips: a commit landed on main (branch already existed) — moved with `git branch -f` + `reset --keep`;
  `config/*.csv` silently ignored by `*.csv` — fixed in `.gitignore`. Both in `vault/LEARNINGS.md` / CONFIG.md.
- Decided: universe aligned to Nifty 500 semi-annual review; research data in files (Parquet), operational data in
  Postgres; DB (ST-012) after ST-010, before execution. `docs/DATA_MODEL.md` proposed (`fa316fb`), awaiting approval.
- Status at close: ST-004 Design proposed on `st/ST-004-universe` (uncommitted `requirements.txt`). Resume: `TODO.md`.

## 2026-10-14 — ST-004 closed; ST-016 rename done (checks pending); data model approved; ST-010 engine built
- Day start: ST-004 index status fixed (was "Not started"). Data model reviewed with Rakesh and approved (stratrad DB,
  sectors, guardrails twice, exit path, charges per order via Kite's virtual contract note, position adjustments).
- ST-016 rename strategy-trader -> stratrad, one step at a time: GitHub repo, prod folder + venv + .env + Samba share,
  laptop X: (Claude desktop app restarted to re-resolve the drive), homelab Job 3/health/map; prod proof PASS. Open:
  Kopia + restore checks 15 Oct, temp backup deletion, sign-off.
- ST-004: panel 5,399,886 rows / 165 MB (9 relisting series breaks); universe 25 Nifty 500-aligned reviews; validator
  PASS (coverage 3,156 days, no lookahead 25/25, survivorship, fidelity 82.6% / top-100 99). Resolved, merge `1fe1a08`.
- Decisions: lots per weekly buy with own GTT stops; multiple strategies per stock; Rakesh's holdings = strategy
  `manual` in the same Zerodha account; per-stock cap 8% of capital cap (soft); new listings conservative; fidelity
  alarm 80% / 95; time exit after >12 months (LTCG); ST-017 dashboards and ST-018 trades-to-sheet logged.
- ST-010: design approved (costs and tax verified from zerodha.com/charges and incometaxindia.gov.in); pieces 1-3 built
  (adjusted prices 762/763, benchmark NSE+Yahoo with 13 special sessions filled, engine, 86 tests). Rakesh's own rule
  (top 4 by 1-year gain, gain-weighted, average-based exits) added. Preliminary trial 2014-10..2023-12: Nifty 500 12.8%/yr;
  baseline 2.0%; rakesh_top4 faithful 19.4% (max DD -56%); within limits 8.4%. Not yet validated.
- Slips: a commit landed on main again (branch switch refused); moved with merge + `reset --keep`.
