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
