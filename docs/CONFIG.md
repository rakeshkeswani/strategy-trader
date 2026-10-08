# CONFIG.md — environments, paths, shares, settings

Present tense: how things are set up NOW. Update in the same commit as any change.
Last updated: 2026-10-08 (ST-014)

## Machines

| | Windows dev | Ubuntu prod |
|---|---|---|
| Machine | Rakesh's laptop | `rkneo50q` — 192.168.0.250 (LAN), 100.103.189.15 (Tailscale) |
| Repo | `C:\RKOneDrive\OneDrive\Work\RKInvesting` | `/home/rakeshbk/strategy-trader` |
| Python | 3.14 (user site-packages) | 3.12.3 in venv `~/strategy-trader/venv` (needs `python3.12-venv`) |
| Run things | `python -m <module>` from repo root | `cd ~/strategy-trader && source venv/bin/activate && python -m <module>` |
| GitHub | `git@github.com:rakeshkeswani/strategy-trader.git` (private), branch `main` | same, `git pull` only |

`(venv)` in the prod prompt = the venv is active in that shell; `deactivate` leaves it. MyInvestIQ uses
`/usr/bin/python3`, not this venv — run MyInvestIQ scripts with the venv deactivated.

## Folder layout on prod

```
/home/rakeshbk/strategy-trader/          repo (code)
├── data/                                git-ignored — ALL strategy-trader data
│   ├── bhavcopy_legacy/                 NSE legacy CM bhavcopy 2014-01-01..2024-07-05, <YYYY>/cm…bhav.csv.zip + manifest.csv
│   ├── bhavcopy_udiff/                  NSE+BSE UDiFF 2024-01-03..2025-08-27 + manifest.csv (one-time, read-only)
│   ├── corporate_actions/               (ST-003)
│   └── trendlyne/                       (ST-005)
└── logs/                                git-ignored — fetch/validate logs and issue CSVs
```

**Rule (Rakesh, 2026-10-08):** each project's folder belongs to that project. strategy-trader never writes under
`/home/rakeshbk/myinvestiq/`; it only reads MyInvestIQ's shared data. MyInvestIQ may read strategy-trader's data
read-only under its own TD.

## Read-only dependencies on MyInvestIQ

| What | Where | Used for |
|---|---|---|
| UDiFF bhavcopy (NSE+BSE), daily 18:00 job | `/home/rakeshbk/myinvestiq/data/bhavcopy/` | prices from 2025-08-28 (+5 probe dates in 2024) |
| Index closes | `/home/rakeshbk/myinvestiq/data/indices/` | breadth, benchmarks (later) |
| `corporate_actions` table | DB `portfolio_watch` | ongoing splits/bonuses (ST-003; needs read-only role, ST-012) |
| `fii_daily_flow` table | DB `portfolio_watch` | regime model (later) |

## Windows shares

| Drive | UNC | Prod path | Samba section |
|---|---|---|---|
| Z: | `\\100.103.189.15\myinvestiq` | `/home/rakeshbk/myinvestiq` | `[myinvestiq]` |
| X: | `\\100.103.189.15\strategy-trader` | `/home/rakeshbk/strategy-trader` | `[strategy-trader]` (added 2026-10-08) |
| Y: | rkfspool | — | `[rkfspool]` (not this project) |

`[strategy-trader]` in `/etc/samba/smb.conf`: `path = /home/rakeshbk/strategy-trader`, `valid users = rakeshbk`,
`create mask = 0644` — identical settings to `[myinvestiq]`. Mapped with
`net use X: \\100.103.189.15\strategy-trader /persistent:yes`.
Fetchers refuse to write to a `//host/...` path, so Windows can never write into prod's archives.

## Environment variables (`.env`, never committed; template `.env.example`)

| Var | Default (unset) | Prod value | Read by |
|---|---|---|---|
| `BHAVCOPY_ARCHIVE_DIR` | none — required | `/home/rakeshbk/myinvestiq/data/bhavcopy` | `core/udiff_bhavcopy_reader.py` |
| `UDIFF_GAP_DIR` | none | `/home/rakeshbk/strategy-trader/data/bhavcopy_udiff` | `core/udiff_bhavcopy_reader.py` |
| `LEGACY_BHAVCOPY_DIR` | `<repo>/data/bhavcopy_legacy` | default (may be set explicitly) | legacy reader + fetcher |
| `INDEX_ARCHIVE_DIR` | none | (not yet used) | — |
| `LOG_DIR` | `<repo>/logs` | default | fetch + validate scripts |
| `TRENDLYNE_DROP_DIR`, `KITE_*`, `DB_*`, `TELEGRAM_*`, `ANTHROPIC_API_KEY` | — | not yet set | later STs |

Windows dev reading prod data: set `BHAVCOPY_ARCHIVE_DIR=//100.103.189.15/myinvestiq/data/bhavcopy`,
`LEGACY_BHAVCOPY_DIR=//100.103.189.15/strategy-trader/data/bhavcopy_legacy`,
`UDIFF_GAP_DIR=//100.103.189.15/strategy-trader/data/bhavcopy_udiff` (forward slashes — dotenv does not unescape `\`).

## Database

Not yet created (ST-012). MyInvestIQ prod DB: PostgreSQL 16, `portfolio_watch`, user `portfolio_rk`;
always `psql -h localhost` (peer auth fails on the Unix socket).

## Scheduled jobs

None yet. (n8n at http://192.168.0.250:5678 runs MyInvestIQ only.)

## One-off operations already run (do not repeat)

| Date | What | Script / command |
|---|---|---|
| 2026-10-08 | Legacy bhavcopy 2014-01-01..2024-07-05 + 7 weekend sessions | `python -m ingestion.fetch_legacy_bhavcopy` |
| 2026-10-08 | UDiFF 2024-01-01..2025-08-27 fetched with MyInvestIQ's fetcher, then moved out of its archive and its manifest rows removed (backup `manifest.csv.bak_<time>` in MyInvestIQ's archive) | `scripts/relocate_udiff_gap.py --go` (paths in it are now historical) |
| 2026-10-08 | Both data folders moved from `myinvestiq/data/` to `strategy-trader/data/`; X: share added | manual `mv`, smb.conf edit |
