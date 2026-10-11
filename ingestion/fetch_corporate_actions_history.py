# -*- coding: utf-8 -*-
# ingestion/fetch_corporate_actions_history.py
"""
ST-003 -- one-time fetch of NSE corporate actions 2014-01-01..2025-08-25 (bonus/split/consolidation history).

Source: https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=...
One call per calendar year. Verified 2026-10-11: a year call is complete (2018's Q1 from the year call equals a
Q1-only call, 192 records) and history reaches 2013. No session cookie needed (MyInvestIQ findings Q1).

Writes, under CORPORATE_ACTIONS_DIR (prod: <repo>/data/corporate_actions/):
  raw/<YYYY>.json   the feed's response byte-for-byte, so it can be re-parsed without re-fetching
  history.csv       parsed BONUS/SPLIT/CONSOLIDATION rows (core.corporate_actions.HISTORY_FIELDS)
and to LOG_DIR: fetch_corporate_actions_history_<date>.log and ..._issues_<date>.csv (excluded / review /
unclassified items).

Ongoing corporate actions (2025-08-26 onward) are MyInvestIQ's (single source of truth); this script never fetches
past HISTORY_END. It is not a daily job.

Safety: refuses a network-share target (run on rkneo50q); a year already in raw/ is reused, not re-fetched, unless
--force; ~2 s between calls with retries. Exit code 0 only if every year returned >= 1 record and nothing is
UNCLASSIFIED. REVIEW items (capital reductions) are logged; scripts/validate_corporate_actions.py decides them.

Usage (on rkneo50q, from the repo root):
  python -m ingestion.fetch_corporate_actions_history                # 2014..2025
  python -m ingestion.fetch_corporate_actions_history --years 2018   # one year (trial)
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from core.config import CORPORATE_ACTIONS_DIR, LOG_DIR
from core.corporate_actions import classify_records, write_history

logger = logging.getLogger('fetch_corporate_actions_history')

URL_TMPL = ('https://www.nseindia.com/api/corporates-corporateActions'
            '?index=equities&from_date={frm}&to_date={to}')
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.nseindia.com/',
}
HISTORY_START = date(2014, 1, 1)
HISTORY_END = date(2025, 8, 25)   # MyInvestIQ owns 2025-08-26 onward
REQUEST_GAP_SECONDS = 2.0
RETRY_BACKOFF_SECONDS = (5, 15, 45)
TIMEOUT = (10, 90)


class FetchError(Exception):
    """A year could not be fetched as a JSON list after all retries."""


def year_window(year: int) -> tuple[date, date]:
    """Return the [from, to] dates fetched for `year`, clipped to HISTORY_START..HISTORY_END."""
    return max(date(year, 1, 1), HISTORY_START), min(date(year, 12, 31), HISTORY_END)


def fetch_year(session: requests.Session, year: int) -> bytes:
    """GET one year's records and return the raw body, after checking it is a JSON list.

    Raises:
        FetchError: network failure, non-200, or a body that is not a JSON list, after all retries.
    """
    frm, to = year_window(year)
    url = URL_TMPL.format(frm=frm.strftime('%d-%m-%Y'), to=to.strftime('%d-%m-%Y'))
    detail = ''
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = json.loads(resp.content)
                if isinstance(data, list):
                    return resp.content
                detail = f'JSON is {type(data).__name__}, not a list'
            else:
                detail = f'HTTP {resp.status_code}'
        except (requests.RequestException, ValueError) as e:
            detail = f'{type(e).__name__}: {e}'
        if attempt < len(RETRY_BACKOFF_SECONDS):
            wait = RETRY_BACKOFF_SECONDS[attempt]
            logger.warning(f'{year}: {detail} -- retry {attempt + 1} in {wait}s')
            time.sleep(wait)
    raise FetchError(f'{year}: {detail}')


def load_or_fetch(years: list[int], raw_dir: Path, force: bool) -> dict:
    """Return {year: records}, reading raw/<YYYY>.json when present (unless force), else fetching and saving it."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    out: dict = {}
    for year in years:
        path = raw_dir / f'{year}.json'
        if path.exists() and not force:
            body = path.read_bytes()
            logger.info(f'{year}: reusing {path.name}')
        else:
            body = fetch_year(session, year)
            tmp = path.with_suffix('.tmp')
            tmp.write_bytes(body)
            tmp.replace(path)
            logger.info(f'{year}: fetched {len(body):,} bytes')
            time.sleep(REQUEST_GAP_SECONDS)
        out[year] = json.loads(body)
    return out


def _in_window(rec: dict) -> bool:
    """True when the record's exDate parses and lies in HISTORY_START..HISTORY_END."""
    try:
        d = datetime.strptime(rec.get('exDate') or '', '%d-%b-%Y').date()
    except ValueError:
        return True   # keep it: classify_records reports it as a bad record if it is in scope
    return HISTORY_START <= d <= HISTORY_END


def _setup_logging() -> None:
    """Log to stdout and logs/fetch_corporate_actions_history_<date>.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_DIR / f'fetch_corporate_actions_history_{date.today():%Y%m%d}.log')])


def _is_network_share(p: Path) -> bool:
    """True for UNC-style paths (//host/share or \\\\host\\share)."""
    return str(p).replace('\\', '/').startswith('//')


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--years', type=int, nargs='+',
                    help=f'years to fetch (default {HISTORY_START.year}..{HISTORY_END.year})')
    ap.add_argument('--force', action='store_true', help='re-fetch years already saved in raw/')
    args = ap.parse_args()
    _setup_logging()

    out_dir = CORPORATE_ACTIONS_DIR
    if _is_network_share(out_dir):
        logger.critical(f'Refusing to write to a network share: {out_dir}. Run on rkneo50q.')
        return 2
    years = sorted(set(args.years or range(HISTORY_START.year, HISTORY_END.year + 1)))
    bad = [y for y in years if not HISTORY_START.year <= y <= HISTORY_END.year]
    if bad:
        logger.critical(f'years outside {HISTORY_START.year}..{HISTORY_END.year}: {bad}')
        return 2

    try:
        by_year = load_or_fetch(years, out_dir / 'raw', args.force)
    except FetchError as e:
        logger.critical(f'fetch failed -- {e}')
        return 3

    records: list = []
    empty_years = []
    for year in years:
        recs = [r for r in by_year[year] if _in_window(r)]
        rows, _, counts = classify_records(recs, HISTORY_END + timedelta(days=1))
        logger.info(f"{year}: {len(by_year[year])} records, BONUS {counts['BONUS']}, SPLIT {counts['SPLIT']}, "
                    f"CONSOL {counts['CONSOLIDATION']}, excluded {counts['excluded']}, review {counts['review']}, "
                    f"unclassified {counts['unclassified']}")
        if not by_year[year]:
            empty_years.append(year)
        records += recs

    rows, issues, counts = classify_records(records, HISTORY_END + timedelta(days=1))
    write_history(out_dir / 'history.csv', rows)
    issues_path = LOG_DIR / f'fetch_corporate_actions_history_issues_{date.today():%Y%m%d}.csv'
    with issues_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['kind', 'symbol', 'ex_date', 'detail'])
        w.writerows(issues)
    logger.info(f'TOTAL {counts} -> {out_dir / "history.csv"} ({len(rows)} rows); issues -> {issues_path}')
    for row in issues:
        logger.info('  ' + ' | '.join(row))

    failed = False
    if empty_years:
        logger.error(f'years with 0 records: {empty_years}')
        failed = True
    if counts['unclassified'] or counts['bad_record']:
        logger.error(f"{counts['unclassified']} unclassified, {counts['bad_record']} bad records -- "
                     f'extend the parser before using history.csv')
        failed = True
    logger.info('RESULT: ' + ('FAIL' if failed else 'OK'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
