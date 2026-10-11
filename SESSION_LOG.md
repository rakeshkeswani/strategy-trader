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
