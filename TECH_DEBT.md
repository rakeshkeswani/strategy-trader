# Issue Index — strategy-trader (ST- prefix)

**This file is the index and the ONLY place status lives.** Full detail for each issue is in
`tech-debt/ST-NNN.md` (frontmatter mirrors this table; if they disagree, this table is right).
Workflow, status values and gates: `CLAUDE.md` → "Change workflow".

| ST | Title | Pri | Status | Since | Area | Next action |
|---|---|---|---|---|---|---|
| [ST-001](tech-debt/ST-001.md) | Project scaffold | High | Moved to Prod — pending verification | 2026-10-08 | repo | Rakesh: prod sign-off |
| [ST-002](tech-debt/ST-002.md) | Legacy bhavcopy 2014–Jul 2024 + UDiFF gap + validated readers | High | Moved to Prod — pending verification | 2026-10-08 | data | Rakesh: prod sign-off (validation PASS 2026-10-08) |
| [ST-003](tech-debt/ST-003.md) | Split/bonus adjustment (corporate actions) | High | Design proposed | 2026-10-08 | data | Claude: final design after ST-014 |
| [ST-004](tech-debt/ST-004.md) | Point-in-time top-500 universe | High | Not started | 2026-10-08 | data | after ST-003, ST-013 |
| [ST-005](tech-debt/ST-005.md) | Trendlyne weekly drop + importer | Med | Not started | 2026-10-08 | data | — |
| [ST-006](tech-debt/ST-006.md) | Kite Connect app + daily login | High | Not started | 2026-10-08 | execution | — |
| [ST-007](tech-debt/ST-007.md) | Mumbai VM order gateway (static IP, Tailscale) | High | Not started | 2026-10-08 | execution | — |
| [ST-008](tech-debt/ST-008.md) | Guardrail service + guardrails.yaml | High | Not started | 2026-10-08 | execution | — |
| [ST-009](tech-debt/ST-009.md) | GTT stops, trailing, daily reconciliation | High | Not started | 2026-10-08 | execution | — |
| [ST-010](tech-debt/ST-010.md) | Baseline momentum strategy + quick backtest | High | Not started | 2026-10-08 | strategy | — |
| [ST-011](tech-debt/ST-011.md) | Telegram proposal and approval flow | High | Not started | 2026-10-08 | notify | — |
| [ST-012](tech-debt/ST-012.md) | Project database + read-only role on MyInvestIQ DB | Med | Not started | 2026-10-08 | database | — |
| [ST-013](tech-debt/ST-013.md) | Symbol changes (stitch renames via ISIN) | High | Not started | 2026-10-08 | data | before ST-004 |
| [ST-014](tech-debt/ST-014.md) | Workflow + docs (MyInvestIQ-style), own prod folder + X: share | High | In progress — branch st/ST-014-workflow-docs | 2026-10-08 | repo | Rakesh: review branch |
