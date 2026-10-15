# -*- coding: utf-8 -*-
# scripts/build_demergers.py
"""
ST-019 -- build config/demergers.csv from the stored NSE feed and the RAW price panel, then check it.

Build: every EQ demerger / scheme-of-arrangement / spin-off record (core.demergers.feed_records), priced from the panel:
previous close, ex-day close, gap, factor = previous close / ex-day close; applied when |gap| > 5%. Rows that already
carry a review note in the existing file keep their note and their `applied` value (a rebuild never undoes a review).

Check (Done-when 1, Rakesh 2026-10-15): for every applied row, no adjusted one-day move beyond +/-10% on the ex-date or
the 2 trading days after it, unless the row's note explains it (e.g. a circuit run); and no row with a gap beyond 5%
left unapplied without a note.

Writes config/demergers.csv (unless --check) and logs to LOG_DIR. Exit code 0 only when RESULT: PASS.
Usage (repo root): python -m scripts.build_demergers [--check]
"""

import argparse
import logging
import sys
from datetime import date

import pandas as pd

from core.config import LOG_DIR
from core.demergers import COLUMNS, DEMERGERS_CSV, GAP_MIN, candidates, feed_records, merge_reviewed
from core.panel import read_panel

logger = logging.getLogger('build_demergers')
MOVE_MAX = 0.10


def moves(r) -> list[float]:
    """Adjusted one-day moves on the ex-date and the next two trading days (NaN where a close is missing)."""
    ex = r.ex_close / (r.prev_close / r.factor) - 1
    return [ex, r.next1_close / r.ex_close - 1, r.next2_close / r.next1_close - 1]


def check(d: pd.DataFrame) -> list[str]:
    """Done-when 1 problems: applied rows with an adjusted move beyond MOVE_MAX around the ex-date and no note;
    unexplained skipped gaps."""
    problems = []
    app = d[(d['applied'].astype(str).str.upper() == 'Y') & (d['note'].fillna('').str.strip() == '')]
    for r in app.itertuples():
        big = [f'{m:+.1%}' for m in moves(r) if abs(m) > MOVE_MAX]
        if big:
            problems.append(f'{r.symbol} {r.ex_date}: adjusted moves beyond {MOVE_MAX:.0%}: {big} (no note)')
    skipped = d[(d['applied'].astype(str).str.upper() != 'Y') & (d['gap'].abs() > GAP_MIN)
                & (d['note'].fillna('').str.strip() == '')]
    problems += [f'{r.symbol} {r.ex_date}: gap {r.gap:+.1%} not applied and no note' for r in skipped.itertuples()]
    return problems


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='only check the existing file')
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LOG_DIR / f'build_demergers_{date.today():%Y%m%d}.log',
                                                      encoding='utf-8')])
    if args.check:
        d = pd.read_csv(DEMERGERS_CSV)
    else:
        recs = feed_records()
        panel = read_panel(columns=['trade_date', 'symbol', 'open', 'close'])
        fresh = candidates(recs, panel)
        existing = pd.read_csv(DEMERGERS_CSV) if DEMERGERS_CSV.exists() else None
        d = merge_reviewed(fresh, existing)[COLUMNS]
        d.to_csv(DEMERGERS_CSV, index=False, float_format='%.6g')
        logger.info(f'{len(recs)} feed records -> {DEMERGERS_CSV}')
    app = d['applied'].astype(str).str.upper() == 'Y'
    logger.info(f'rows {len(d)}; applied {int(app.sum())}; not applied {int((~app).sum())} '
                f'(no prices {int(d["prev_close"].isna().sum())})')
    problems = check(d)
    for p in problems:
        logger.warning(p)
    logger.info('RESULT: ' + (f'FAIL -- {len(problems)} rows' if problems else 'PASS'))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
