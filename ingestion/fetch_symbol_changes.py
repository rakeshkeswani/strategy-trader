# -*- coding: utf-8 -*-
# ingestion/fetch_symbol_changes.py
"""
ST-003 -- save a snapshot of NSE's symbol-change list to SYMBOL_CHANGES_DIR/symbolchange.csv.

Source: https://nsearchives.nseindia.com/content/equities/symbolchange.csv (verified 2026-10-11: 1,064 rows,
2003 onward). Saved byte-for-byte; the previous snapshot is kept as symbolchange_<date>.csv when replaced.
Refuses a network-share target (run on rkneo50q). Not a daily job.

Usage (on rkneo50q, from the repo root): python -m ingestion.fetch_symbol_changes
"""

import logging
import shutil
import sys
from datetime import date
from pathlib import Path

import requests

from core.config import SYMBOL_CHANGES_DIR
from core.symbol_changes import SNAPSHOT_NAME, parse_rows

logger = logging.getLogger('fetch_symbol_changes')
URL = 'https://nsearchives.nseindia.com/content/equities/symbolchange.csv'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
    'Accept': '*/*',
    'Referer': 'https://www.nseindia.com/',
}
MIN_ROWS = 900


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    out_dir: Path = SYMBOL_CHANGES_DIR
    if str(out_dir).replace('\\', '/').startswith('//'):
        logger.critical(f'Refusing to write to a network share: {out_dir}. Run on rkneo50q.')
        return 2
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=(10, 60))
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.critical(f'fetch failed: {e}')
        return 3
    rows = parse_rows(resp.content.decode('latin-1'))
    if len(rows) < MIN_ROWS:
        logger.critical(f'only {len(rows)} parseable rows (< {MIN_ROWS}) -- not saved')
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SNAPSHOT_NAME
    if path.exists():
        shutil.copy2(path, out_dir / f'symbolchange_{date.today():%Y%m%d}.csv')
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(resp.content)
    tmp.replace(path)
    newest = max(d for _, _, d in rows)
    logger.info(f'saved {len(resp.content):,} bytes, {len(rows)} renames (newest {newest}) -> {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
