# -*- coding: utf-8 -*-
# ingestion/build_price_panel.py
"""
ST-004 -- build or extend the price panel (core/panel.py; schema in docs/DATA_MODEL.md).

Reads every trading day through core.prices (the same entry point as the validators), keeps equities only
(core.securities.is_equity), tags company_key (ST-013) and series_id, and writes one Parquet file per year under
PANEL_DIR/equity_daily/. Prices stay RAW.

Modes:
  default  -- append: from the day after the panel's last date to --end; rewrites only the years touched; each
              company continues its current series (core.panel.last_rows).
  --full   -- rebuild every year from --start (default 2014-01-01). Use after a reader fix, a new rename in
              config/symbol_changes_extra.csv, or a change to the series rule.

Refuses a network-share target (run on rkneo50q). Not yet scheduled (a daily append comes with the live run).

Usage (on rkneo50q, from the repo root):
  python -m ingestion.build_price_panel --full
  python -m ingestion.build_price_panel                 # append new days
  python -m ingestion.build_price_panel --full --start 2021-01-01 --end 2021-12-31   # trial
"""

import argparse
import logging
import shutil
import sys
import time
from datetime import date, timedelta

import pandas as pd

from core.config import LOG_DIR, PANEL_DIR
from core.panel import assign_series, day_frame, last_rows, partition_path, read_panel, table_dir, write_year
from core.prices import BhavcopyDateMissingError, read_ohlcv_for_date
from core.securities import Securities, is_equity

logger = logging.getLogger('build_price_panel')
DEFAULT_START = date(2014, 1, 1)


def collect(start: date, end: date, secs: Securities) -> tuple[pd.DataFrame, int]:
    """Read every trading day in [start, end]; return (rows without series_id, trading days read)."""
    frames, days = [], 0
    d = start
    while d <= end:
        try:
            day = read_ohlcv_for_date(d)
        except BhavcopyDateMissingError:
            d += timedelta(days=1)
            continue
        eq = {s: r for s, r in day.items() if is_equity(s, r.get('isin')) and r.get('close')}
        frames.append(day_frame(eq, d, secs.key_on))
        days += 1
        if days % 250 == 0:
            logger.info(f'read {days} trading days (to {d})')
        d += timedelta(days=1)
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return rows, days


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--full', action='store_true', help='rebuild from --start instead of appending')
    ap.add_argument('--start', type=date.fromisoformat, default=DEFAULT_START)
    ap.add_argument('--end', type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LOG_DIR / f'build_price_panel_{date.today():%Y%m%d}.log')])
    if str(PANEL_DIR).replace('\\', '/').startswith('//'):
        logger.critical(f'Refusing to write to a network share: {PANEL_DIR}. Run on rkneo50q.')
        return 2

    t0 = time.time()
    secs = Securities.load()
    if args.full:
        start, context = args.start, None
        if table_dir().exists():
            shutil.rmtree(table_dir())
            logger.info(f'--full: removed {table_dir()}')
    else:
        context = last_rows()
        if context.empty:
            logger.critical('panel is empty -- run with --full first')
            return 2
        start = max(context['trade_date']) + timedelta(days=1)
    if start > args.end:
        logger.info(f'nothing to do: panel already ends {start - timedelta(days=1)}')
        return 0

    rows, days = collect(start, args.end, secs)
    if rows.empty:
        logger.info(f'no trading days in {start}..{args.end}')
        return 0
    rows = assign_series(rows, context)
    rows['year'] = pd.to_datetime(rows['trade_date']).dt.year
    for year, part in rows.groupby('year'):
        part = part.drop(columns='year')
        if not args.full and partition_path(year).exists():
            part = pd.concat([read_panel(date(year, 1, 1), date(year, 12, 31)), part], ignore_index=True)
        path = write_year(part, year)
        logger.info(f'{year}: {len(part):,} rows -> {path} ({path.stat().st_size / 1e6:.1f} MB)')

    total = read_panel(columns=['trade_date', 'series_id', 'company_key'])
    size = sum(f.stat().st_size for f in table_dir().glob('year=*/part-0.parquet'))
    breaks = total.groupby('company_key')['series_id'].nunique()
    logger.info(f'PANEL: {len(total):,} rows, {total["trade_date"].nunique()} trading days '
                f'{total["trade_date"].min()}..{total["trade_date"].max()}, {total["company_key"].nunique()} companies, '
                f'{total["series_id"].nunique()} series, {size / 1e6:.1f} MB; read {days} days in {time.time() - t0:.0f}s')
    multi = breaks[breaks > 1]
    logger.info(f'SERIES BREAKS: {len(multi)} companies with more than one series: {sorted(multi.index)[:40]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
