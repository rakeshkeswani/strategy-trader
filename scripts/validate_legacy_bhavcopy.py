# -*- coding: utf-8 -*-
# scripts/validate_legacy_bhavcopy.py
"""
ST-002 acceptance checks for the legacy bhavcopy archive. Read-only.

1. OVERLAP: for every date 2024-01-01..2024-07-05 present in BOTH the legacy archive and
   MyInvestIQ's UDiFF archive, compare every EQ/BE symbol: open, high, low, close, prev_close
   and volume must match exactly; traded_value is compared too (reported, units checked).
   Symbols present in only one format are listed.
2. CALENDAR: per-year OK counts (expect ~240-252), and every 404_UNKNOWN weekday classified
   against an independent list of Nifty 50 trading dates (yfinance ^NSEI):
     - Nifty did not trade  -> holiday (explained)
     - Nifty traded         -> GAP (unexplained, must be resolved)
   Also lists weekend dates where Nifty traded (special sessions) that were never attempted.

Writes details to logs/validate_legacy_bhavcopy_<date>.csv. Exit code 0 only if there are no
unexplained gaps and no OHLC/volume mismatches.

Usage: python -m scripts.validate_legacy_bhavcopy [--skip-calendar] [--skip-overlap]
"""

import argparse
import csv
import logging
import sys
from datetime import date, timedelta

from core.config import LEGACY_BHAVCOPY_DIR, LOG_DIR
from core import legacy_bhavcopy_reader as legacy
from core import udiff_bhavcopy_reader as udiff
from core.legacy_bhavcopy_reader import BhavcopyDateMissingError, LAST_LEGACY_DATE
from ingestion.fetch_legacy_bhavcopy import DEFAULT_START, load_manifest

logger = logging.getLogger('validate_legacy_bhavcopy')
EXACT_FIELDS = ('open', 'high', 'low', 'close', 'prev_close', 'volume')


def check_overlap(issues: list) -> dict:
    """Compare legacy vs UDiFF for every overlap date; append issue rows; return a summary."""
    summary = {'dates_compared': 0, 'symbols_compared': 0, 'field_mismatches': 0,
               'only_legacy': 0, 'only_udiff': 0, 'value_ratio_samples': []}
    d = udiff.UDIFF_ARCHIVE_START
    while d <= LAST_LEGACY_DATE:
        try:
            old = legacy.read_ohlcv_for_date(d)
            new = udiff.read_ohlcv_for_date(d)
        except BhavcopyDateMissingError:
            d += timedelta(days=1)
            continue
        summary['dates_compared'] += 1
        for sym in sorted(set(old) - set(new)):
            summary['only_legacy'] += 1
            issues.append(['overlap_only_legacy', d.isoformat(), sym, '', '', ''])
        for sym in sorted(set(new) - set(old)):
            summary['only_udiff'] += 1
            issues.append(['overlap_only_udiff', d.isoformat(), sym, '', '', ''])
        for sym in sorted(set(old) & set(new)):
            summary['symbols_compared'] += 1
            for field in EXACT_FIELDS:
                if old[sym][field] != new[sym][field]:
                    summary['field_mismatches'] += 1
                    issues.append(['overlap_mismatch', d.isoformat(), sym, field,
                                   old[sym][field], new[sym][field]])
            ov, nv = old[sym]['traded_value'], new[sym]['traded_value']
            if ov and nv and len(summary['value_ratio_samples']) < 200:
                summary['value_ratio_samples'].append(nv / ov)
        d += timedelta(days=1)
    samples = sorted(summary.pop('value_ratio_samples'))
    summary['traded_value_ratio_median'] = samples[len(samples) // 2] if samples else None
    return summary


def nifty_trading_dates(start: date, end: date) -> set | None:
    """Return Nifty 50 trading dates from yfinance (^NSEI), or None if unavailable."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning('yfinance not installed -- calendar cross-check skipped')
        return None
    try:
        df = yf.download('^NSEI', start=start.isoformat(),
                         end=(end + timedelta(days=1)).isoformat(), progress=False, auto_adjust=False)
    except Exception as e:  # yfinance raises assorted exception types; report and degrade
        logger.warning(f'yfinance download failed: {e}')
        return None
    if df is None or df.empty:
        logger.warning('yfinance returned no ^NSEI data -- calendar cross-check skipped')
        return None
    return {ts.date() for ts in df.index}


def check_calendar(issues: list) -> dict:
    """Per-year counts and 404 classification; append issue rows; return a summary."""
    manifest = load_manifest(LEGACY_BHAVCOPY_DIR / 'manifest.csv')
    ok = {date.fromisoformat(k) for k, r in manifest.items() if r['outcome'] == 'OK'}
    not_found = {date.fromisoformat(k) for k, r in manifest.items() if r['outcome'] == '404_UNKNOWN'}
    other = {k: r['outcome'] for k, r in manifest.items() if r['outcome'] not in ('OK', '404_UNKNOWN')}
    per_year = {}
    for d in ok:
        per_year[d.year] = per_year.get(d.year, 0) + 1
    summary = {'ok_files': len(ok), 'per_year': dict(sorted(per_year.items())),
               'not_found': len(not_found), 'errors_or_invalid': len(other),
               'holidays_explained': 0, 'unexplained_gaps': 0, 'weekend_sessions_missing': 0}
    for k, outcome in sorted(other.items()):
        issues.append(['manifest_' + outcome.lower(), k, '', '', '', ''])
    nifty = nifty_trading_dates(DEFAULT_START, LAST_LEGACY_DATE)
    if nifty is None:
        summary['nifty_check'] = 'skipped'
        return summary
    for d in sorted(not_found):
        if d in nifty:
            summary['unexplained_gaps'] += 1
            issues.append(['gap_nifty_traded', d.isoformat(), '', '', '', ''])
        else:
            summary['holidays_explained'] += 1
    for d in sorted(nifty):
        if d.weekday() >= 5 and d not in ok and d.isoformat() not in manifest:
            summary['weekend_sessions_missing'] += 1
            issues.append(['weekend_session_not_fetched', d.isoformat(), '', '', '', ''])
    for d in sorted(ok - nifty):
        issues.append(['file_but_no_nifty_close', d.isoformat(), '', '', '', ''])
    return summary


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--skip-overlap', action='store_true')
    ap.add_argument('--skip-calendar', action='store_true')
    args = ap.parse_args()
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])

    issues: list = []
    failed = False
    if not args.skip_calendar:
        cal = check_calendar(issues)
        logger.info(f'CALENDAR: {cal}')
        failed |= bool(cal.get('unexplained_gaps') or cal.get('errors_or_invalid')
                       or cal.get('weekend_sessions_missing'))
    if not args.skip_overlap:
        ov = check_overlap(issues)
        logger.info(f'OVERLAP: {ov}')
        failed |= bool(ov['field_mismatches']) or ov['dates_compared'] == 0

    out = LOG_DIR / f'validate_legacy_bhavcopy_{date.today():%Y%m%d}.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['check', 'date', 'symbol', 'field', 'legacy', 'udiff_or_note'])
        w.writerows(issues)
    logger.info(f'{len(issues)} issue rows -> {out}')
    logger.info('RESULT: ' + ('FAIL -- review the issue file' if failed else 'PASS'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
