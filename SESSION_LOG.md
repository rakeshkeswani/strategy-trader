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
