# -*- coding: utf-8 -*-
# ingestion/fetch_legacy_bhavcopy.py
"""
ST-002 -- one-time download of NSE legacy-format CM bhavcopy, 2014-01-01 to 2024-07-05.

Source (verified 2026-10-08 on rkneo50q for 2014, 2016, 2019, 2023 and Jul 2024; the
`archives.` host 403s on 2014, so only `nsearchives.` is used):
  https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip

Writes RAW zips byte-for-byte to <LEGACY_BHAVCOPY_DIR>/<YYYY>/ plus manifest.csv at the root.
This script is the ONLY writer of that directory. It is not a daily job: current data comes
from MyInvestIQ's own 18:00 bhavcopy job.

Safety:
  - Every file is content-validated (zip magic, CSV member, required columns, every TIMESTAMP ==
    requested date, row floor) before it is written. NSE/BSE can return error pages with HTTP 200.
  - Refuses to write to a network-share path (//host/... or \\\\host\\...) so a dev box can never
    write into prod's archive. Run it on rkneo50q.
  - ~1 request/second; retries with backoff; aborts after 10 consecutive refusals (403/429).
  - Re-runs skip dates already OK. 404 weekdays are recorded as 404_UNKNOWN (holiday or gap --
    scripts/validate_legacy_bhavcopy.py explains them) and skipped unless --retry-404.

Usage (on rkneo50q, from the repo root):
  python -m ingestion.fetch_legacy_bhavcopy                    # full range
  python -m ingestion.fetch_legacy_bhavcopy --start 2014-01-01 --end 2014-01-31   # trial month
  python -m ingestion.fetch_legacy_bhavcopy --dates 2020-02-01 # specific dates, e.g. special sessions
"""

import argparse
import csv
import hashlib
import logging
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from core.config import LEGACY_BHAVCOPY_DIR, LOG_DIR
from core.legacy_bhavcopy_reader import (
    LAST_LEGACY_DATE, MONTHS, BhavcopyFormatError, count_rows, extract_csv_text,
    legacy_filename, legacy_path, parse_legacy_csv,
)

logger = logging.getLogger('fetch_legacy_bhavcopy')

URL_TMPL = ('https://nsearchives.nseindia.com/content/historical/EQUITIES/'
            '{yyyy}/{mon}/{filename}')
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
    'Accept': '*/*',
}
DEFAULT_START = date(2014, 1, 1)
DEFAULT_END = LAST_LEGACY_DATE
MIN_ROW_COUNT = 500
REQUEST_GAP_SECONDS = 1.0
RETRY_BACKOFF_SECONDS = (5, 15, 45)
MAX_CONSECUTIVE_REFUSALS = 10
TIMEOUT_SECONDS = 30
MANIFEST_FIELDS = ['date', 'filename', 'bytes', 'sha256', 'row_count', 'equity_rows',
                   'outcome', 'http_status', 'detail', 'fetched_at']
RESOLVED = {'OK'}


class AbortRun(Exception):
    """Raised when NSE keeps refusing requests; stop rather than risk a block."""


def url_for(d: date) -> str:
    """Return the nsearchives legacy URL for date `d`."""
    return URL_TMPL.format(yyyy=d.year, mon=MONTHS[d.month - 1], filename=legacy_filename(d))


def validate_payload(raw: bytes, d: date) -> tuple[int, int]:
    """Validate downloaded bytes as a legacy bhavcopy for date `d`.

    Returns:
        (row_count over all series, equity_rows in EQ/BE).

    Raises:
        BhavcopyFormatError: anything that is not a real, complete file for `d`.
    """
    if not raw.startswith(b'PK'):
        head = raw[:16]
        raise BhavcopyFormatError(f'not a zip (starts {head!r}) -- likely an HTML error page')
    csv_text = extract_csv_text(raw)
    equity = parse_legacy_csv(csv_text, expected_date=d)
    rows = count_rows(csv_text)
    if rows < MIN_ROW_COUNT:
        raise BhavcopyFormatError(f'only {rows} rows (< {MIN_ROW_COUNT}) -- truncated?')
    return rows, len(equity)


def weekdays(start: date, end: date) -> list[date]:
    """Return every Monday-Friday date in [start, end]."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def load_manifest(path: Path) -> dict:
    """Load manifest.csv into {iso_date: row}; empty dict when absent."""
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8') as f:
        return {r['date']: r for r in csv.DictReader(f)}


def write_manifest(path: Path, rows: dict) -> None:
    """Write the manifest atomically (temp file + replace), sorted by date."""
    tmp = path.with_suffix('.csv.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for key in sorted(rows):
            w.writerow({k: rows[key].get(k, '') for k in MANIFEST_FIELDS})
    tmp.replace(path)


def fetch_one(session: requests.Session, d: date, archive_dir: Path) -> dict:
    """Download, validate and store one date. Returns its manifest row; never raises."""
    row = {'date': d.isoformat(), 'filename': legacy_filename(d), 'bytes': '', 'sha256': '',
           'row_count': '', 'equity_rows': '', 'outcome': 'ERROR', 'http_status': '',
           'detail': '', 'fetched_at': datetime.now().isoformat(timespec='seconds')}
    url = url_for(d)
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            row['detail'] = f'{type(e).__name__}: {e}'
            resp = None
        if resp is not None:
            row['http_status'] = str(resp.status_code)
            if resp.status_code == 404:
                row['outcome'], row['detail'] = '404_UNKNOWN', 'not found (holiday or gap)'
                return row
            if resp.status_code == 200:
                try:
                    rows, eq_rows = validate_payload(resp.content, d)
                except BhavcopyFormatError as e:
                    row['outcome'], row['detail'] = 'INVALID', str(e)
                    return row
                out_path = legacy_path(d, archive_dir)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = out_path.with_suffix('.tmp')
                tmp.write_bytes(resp.content)
                tmp.replace(out_path)
                row.update(bytes=str(len(resp.content)),
                           sha256=hashlib.sha256(resp.content).hexdigest(),
                           row_count=str(rows), equity_rows=str(eq_rows),
                           outcome='OK', detail='')
                return row
            row['detail'] = f'HTTP {resp.status_code}'
        if attempt < len(RETRY_BACKOFF_SECONDS):
            wait = RETRY_BACKOFF_SECONDS[attempt]
            logger.warning(f'{d}: {row["detail"]} -- retry {attempt + 1} in {wait}s')
            time.sleep(wait)
    return row


def run(dates: list[date], archive_dir: Path, retry_404: bool, force: bool) -> dict:
    """Fetch every date not already resolved; returns outcome counts."""
    manifest_path = archive_dir / 'manifest.csv'
    manifest = load_manifest(manifest_path)
    skip = set(RESOLVED) | (set() if retry_404 else {'404_UNKNOWN'})
    todo = [d for d in dates if force or manifest.get(d.isoformat(), {}).get('outcome') not in skip]
    logger.info(f'{len(dates)} dates requested, {len(todo)} to fetch, archive={archive_dir}')

    counts: dict = {}
    refusals = 0
    session = requests.Session()
    try:
        for i, d in enumerate(todo, 1):
            row = fetch_one(session, d, archive_dir)
            manifest[d.isoformat()] = row
            counts[row['outcome']] = counts.get(row['outcome'], 0) + 1
            if row['outcome'] == 'OK':
                refusals = 0
            elif row['http_status'] in ('403', '429'):
                refusals += 1
                if refusals >= MAX_CONSECUTIVE_REFUSALS:
                    raise AbortRun(f'{refusals} consecutive refusals (last {d}) -- stopping')
            if row['outcome'] not in ('OK', '404_UNKNOWN'):
                logger.warning(f"{d}: {row['outcome']} {row['detail']}")
            if i % 25 == 0:
                write_manifest(manifest_path, manifest)
                logger.info(f'{i}/{len(todo)} done {counts}')
            time.sleep(REQUEST_GAP_SECONDS + random.uniform(0, 0.5))
    finally:
        write_manifest(manifest_path, manifest)
    return counts


def _setup_logging() -> None:
    """Log to stdout and logs/fetch_legacy_bhavcopy_<date>.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_DIR / f'fetch_legacy_bhavcopy_{date.today():%Y%m%d}.log')])


def _is_network_share(p: Path) -> bool:
    """True for UNC-style paths (//host/share or \\\\host\\share)."""
    s = str(p).replace('\\', '/')
    return s.startswith('//')


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', type=date.fromisoformat, default=DEFAULT_START)
    ap.add_argument('--end', type=date.fromisoformat, default=DEFAULT_END)
    ap.add_argument('--dates', type=date.fromisoformat, nargs='+',
                    help='explicit dates (any weekday or weekend), overrides --start/--end')
    ap.add_argument('--retry-404', action='store_true', help='re-try dates recorded as 404_UNKNOWN')
    ap.add_argument('--force', action='store_true', help='re-fetch even dates already OK')
    args = ap.parse_args()
    _setup_logging()

    archive_dir = LEGACY_BHAVCOPY_DIR
    if _is_network_share(archive_dir):
        logger.critical(f'Refusing to write to a network share: {archive_dir}. Run on rkneo50q.')
        return 2
    if args.end > LAST_LEGACY_DATE:
        logger.critical(f'--end {args.end} is after the last legacy-format date {LAST_LEGACY_DATE}')
        return 2
    archive_dir.mkdir(parents=True, exist_ok=True)

    dates = sorted(set(args.dates)) if args.dates else weekdays(args.start, args.end)
    try:
        counts = run(dates, archive_dir, args.retry_404, args.force)
    except AbortRun as e:
        logger.critical(str(e))
        return 3
    logger.info(f'Finished: {counts}')
    return 0 if not counts.get('ERROR') and not counts.get('INVALID') else 1


if __name__ == '__main__':
    sys.exit(main())
