# -*- coding: utf-8 -*-
# ingestion/build_universe.py
"""
ST-004 -- build the point-in-time top-500 universe for every Nifty 500 review the panel covers (core/universe.py).

Reads the price panel (core/panel.py), ranks each review using only rows up to its cut-off, and writes
UNIVERSE_DIR/membership.csv. Rebuilds every review on each run (seconds); re-run after the panel is rebuilt or
appended past a new cut-off.

Usage (on rkneo50q, from the repo root): python -m ingestion.build_universe
"""

import logging
import sys
import time
from datetime import date

import pandas as pd

from core.config import LOG_DIR
from core.panel import read_panel
from core.universe import PANEL_COLUMNS, SIZE, UNIVERSE_DIR, build_review, review_calendar, write_membership

logger = logging.getLogger('build_universe')


def main() -> int:
    """CLI entry point."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LOG_DIR / f'build_universe_{date.today():%Y%m%d}.log')])
    if str(UNIVERSE_DIR).replace('\\', '/').startswith('//'):
        logger.critical(f'Refusing to write to a network share: {UNIVERSE_DIR}. Run on rkneo50q.')
        return 2
    t0 = time.time()
    panel = read_panel(columns=PANEL_COLUMNS)
    if panel.empty:
        logger.critical('panel is empty -- run python -m ingestion.build_price_panel --full first')
        return 2
    calendar = review_calendar(list(panel['trade_date'].unique()))
    logger.info(f'panel {len(panel):,} rows; {len(calendar)} reviews from {calendar[0][0]} to {calendar[-1][0]}')

    reviews, prev = [], None
    for cutoff, effective in calendar:
        members, c = build_review(panel, cutoff, effective)
        keys = set(members['series_id'])
        turnover = '' if prev is None else f', turnover {len(keys - prev)} in / {len(prev - keys)} out'
        logger.info(f"{cutoff} -> {effective}: sessions {c['sessions']}, traded {c['traded_on_cutoff']}, "
                    f"EQ {c['eq_on_cutoff']}, freq>=90% {c['freq_ok']}, price>=10 {c['eligible']}, "
                    f"members {c['members']}{turnover}")
        if c['members'] < SIZE and c['eligible'] > SIZE:
            logger.error(f'{cutoff}: {c["members"]} members while {c["eligible"]} eligible')
        reviews.append(members)
        prev = keys
    path = write_membership(pd.concat(reviews, ignore_index=True))
    logger.info(f'UNIVERSE: {len(calendar)} reviews, {sum(len(r) for r in reviews):,} rows -> {path} '
                f'({time.time() - t0:.0f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
