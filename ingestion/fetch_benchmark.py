# -*- coding: utf-8 -*-
# ingestion/fetch_benchmark.py
"""
ST-010 -- Nifty 500 index history (the benchmark) to BENCHMARK_DIR/nifty500.csv (trade_date, close).

Source: Yahoo Finance `^CRSLDX` (Nifty 500 price index; 2013-12-02 onward, verified 2026-10-14). Cross-checked against
MyInvestIQ's daily NSE index files (INDEX_ARCHIVE_DIR or MyInvestIQ's data/indices next to its bhavcopy archive,
`ind_close_all_DDMMYYYY.csv`, row "Nifty 500", 2024 onward): every overlapping day must agree within MAX_DIFF.
The file is built on the PANEL's trading calendar: NSE's value where an NSE file exists (official), else Yahoo's; every
panel trading day must have a value. Yahoo lacks NSE's special sessions (Muhurat, Budget Saturdays, 1 January -- 13
days 2014-2024, found 2026-10-14): a single missing day carries the previous close (source 'ffill'; the period return
is unchanged); two missing days in a row, or more than MAX_FILLED in all, fail. Price index without
dividends -- like for like with the backtest, which has no dividends either. Re-run to extend; it rewrites the file.

Refuses a network-share target (run on rkneo50q).
Usage (on rkneo50q, from the repo root): python -m ingestion.fetch_benchmark
"""

import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from core.config import BENCHMARK_DIR, BHAVCOPY_ARCHIVE_DIR, INDEX_ARCHIVE_DIR
from core.panel import read_panel

logger = logging.getLogger('fetch_benchmark')
TICKER = '^CRSLDX'
START = '2013-12-01'
MAX_DIFF = 0.005
MAX_FILLED = 20
INDEX_NAME = 'Nifty 500'


def nse_index_closes(folder: Path) -> dict:
    """Read {date: close} for INDEX_NAME from MyInvestIQ's ind_close_all_*.csv files."""
    out = {}
    for f in sorted(folder.glob('ind_close_all_*.csv')):
        with f.open(newline='', encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                if (r.get('Index Name') or '').strip() == INDEX_NAME:
                    try:
                        d = datetime.strptime(r['Index Date'].strip(), '%d-%m-%Y').date()
                        out[d] = float(r['Closing Index Value'])
                    except (KeyError, ValueError):
                        continue
    return out


def fetch_yahoo(end: date) -> pd.DataFrame:
    """Download daily closes for TICKER; return DataFrame (trade_date, close)."""
    import yfinance as yf
    df = yf.download(TICKER, start=START, end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                     progress=False, auto_adjust=False)
    s = df['Close'].iloc[:, 0].dropna()
    return pd.DataFrame({'trade_date': [t.date() for t in s.index], 'close': s.values.astype(float)})


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    if str(BENCHMARK_DIR).replace('\\', '/').startswith('//'):
        logger.critical(f'Refusing to write to a network share: {BENCHMARK_DIR}. Run on rkneo50q.')
        return 2
    yahoo = fetch_yahoo(date.today())
    if yahoo.empty:
        logger.critical(f'{TICKER}: no data')
        return 1
    folder = INDEX_ARCHIVE_DIR or (BHAVCOPY_ARCHIVE_DIR.parent / 'indices' if BHAVCOPY_ARCHIVE_DIR else None)
    nse = nse_index_closes(folder) if folder and folder.exists() else {}
    ydict = dict(zip(yahoo['trade_date'], yahoo['close']))
    both = [d for d in nse if d in ydict]
    diffs = sorted(((abs(ydict[d] / nse[d] - 1), d) for d in both), reverse=True)
    worst = diffs[0] if diffs else (0.0, None)
    days = sorted(read_panel(columns=['trade_date'])['trade_date'].unique())
    days = [d for d in days if d >= yahoo['trade_date'].min()]
    rows, from_nse, from_yahoo, gaps, run_gaps = [], 0, 0, [], []
    prev_missing = False
    for d in days:
        if d in nse:
            rows.append((d, nse[d], 'nse'))
            from_nse += 1
            prev_missing = False
        elif d in ydict:
            rows.append((d, ydict[d], 'yahoo'))
            from_yahoo += 1
            prev_missing = False
        else:
            gaps.append(d)
            if prev_missing or not rows:
                run_gaps.append(d)
            else:
                rows.append((d, rows[-1][1], 'ffill'))
            prev_missing = True
    yahoo_only = sorted(set(ydict) - set(days))
    logger.info(f'{TICKER}: {len(yahoo)} days {yahoo["trade_date"].min()}..{yahoo["trade_date"].max()}; NSE files '
                f'{len(nse)} days from {folder}; both {len(both)}, worst diff {worst[0]:.4%} on {worst[1]}')
    logger.info(f'calendar: {len(days)} panel trading days; from NSE {from_nse}, from Yahoo {from_yahoo}, '
                f'missing {len(gaps)} {gaps[:12]}; Yahoo days not in the panel {len(yahoo_only)} {yahoo_only[:5]}')
    if not nse:
        logger.critical('no NSE index files found for the cross-check')
        return 1
    if run_gaps or len(gaps) > MAX_FILLED or worst[0] > MAX_DIFF:
        logger.critical(f'FAILED: gaps {len(gaps)} (consecutive or leading: {run_gaps}); worst diff {worst}')
        return 1
    logger.info(f'filled from the previous close: {[str(d) for d in gaps]}')
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    path = BENCHMARK_DIR / 'nifty500.csv'
    tmp = path.with_suffix('.csv.tmp')
    pd.DataFrame(rows, columns=['trade_date', 'close', 'source']).to_csv(tmp, index=False, float_format='%.2f')
    tmp.replace(path)
    logger.info(f'RESULT: OK -> {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
