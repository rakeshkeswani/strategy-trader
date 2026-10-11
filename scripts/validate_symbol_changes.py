# -*- coding: utf-8 -*-
# scripts/validate_symbol_changes.py
"""
ST-013 acceptance checks: renames proved against prices, 2014-01-01..today. Read-only.

Streams every trading day through core.prices (equities only, core.securities.is_equity) and records each symbol's
RUNS -- stretches of trading with no gap over RUN_BREAK_DAYS -- with first/last date, close and ISIN.

1. LISTED RENAMES (NSE snapshot + config/symbol_changes_extra.csv) dated in range: the new symbol's first run near
   the rename date must follow the old symbol's last run within RUN_BREAK_DAYS, with the ISIN unchanged or the
   change explained by a stored split/bonus at the stitch, and the ADJUSTED close-to-close move across the stitch
   within +/-STITCH_LIMIT. Renames where neither symbol trades as an equity in range (MF schemes, pre-2014, SME) are
   counted only. Renames seen on one side only are listed for information.
2. CONTINUITY CANDIDATES (renames NSE's list may miss): symbol A's run ends and, within CONTINUITY_SESSIONS trading
   sessions, symbol B's run starts with A's last ISIN. Each must be a known rename (same company key via
   core.securities) or a 'not_rename' row in config/symbol_exceptions.csv. A true miss belongs in
   config/symbol_changes_extra.csv.

config/symbol_exceptions.csv columns: kind, old, new, date, reason
  not_rename -- a continuity candidate that is not a rename (date = B's first date)
  rename_ok  -- a listed rename that fails a stitch check for a reviewed reason (date = rename date)

Writes logs/validate_symbol_changes_<date>.csv. Exit code 0 only when RESULT: PASS.
Usage: python -m scripts.validate_symbol_changes [--start 2014-01-01 --end <today>]
"""

import argparse
import csv
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from core.config import LOG_DIR, REPO_ROOT
from core.corporate_actions import cumulative_factor, load_history
from core.prices import BhavcopyDateMissingError, read_ohlcv_for_date
from core.securities import Securities, is_equity

logger = logging.getLogger('validate_symbol_changes')
EXCEPTIONS_FILE = REPO_ROOT / 'config' / 'symbol_exceptions.csv'
DEFAULT_START = date(2014, 1, 1)
RUN_BREAK_DAYS = 30          # no close for more than this many calendar days ends a run
CONTINUITY_SESSIONS = 5      # B must start within this many trading sessions after A's last close
STITCH_LIMIT = 0.30
RENAME_WINDOW_DAYS = 30      # the new symbol's run must start within this many days of the listed rename date


def load_exceptions(path: Path = EXCEPTIONS_FILE) -> dict:
    """Load config/symbol_exceptions.csv into {(kind, old, new, iso_date): reason}; empty when absent."""
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8') as f:
        return {(r['kind'], r['old'], r['new'], r['date']): r['reason'] for r in csv.DictReader(f)}


def scan_runs(start: date, end: date) -> tuple[dict, list]:
    """Return ({symbol: [run, ...]}, trading days). A run is a dict of first_/last_ date, close, isin."""
    runs: dict = {}
    days: list = []
    d = start
    while d <= end:
        try:
            day = read_ohlcv_for_date(d)
        except BhavcopyDateMissingError:
            d += timedelta(days=1)
            continue
        days.append(d)
        if len(days) % 250 == 0:
            logger.info(f'scanned {len(days)} trading days (to {d})')
        for symbol, rec in day.items():
            close, isin = rec.get('close'), rec.get('isin')
            if not close or not is_equity(symbol, isin):
                continue
            lst = runs.setdefault(symbol, [])
            if lst and (d - lst[-1]['last_date']).days <= RUN_BREAK_DAYS:
                lst[-1].update(last_date=d, last_close=close, last_isin=isin)
            else:
                lst.append({'first_date': d, 'first_close': close, 'first_isin': isin,
                            'last_date': d, 'last_close': close, 'last_isin': isin})
        d += timedelta(days=1)
    return runs, days


def check_renames(secs: Securities, runs: dict, table: dict, start: date, end: date,
                  exceptions: dict, issues: list) -> dict:
    """Prove every listed rename dated in [start, end] against the runs; append issue rows; return counts."""
    c = {'in_range': 0, 'confirmed': 0, 'not_seen': 0, 'one_side': 0, 'gap': 0,
         'outside_limit': 0, 'isin_unexplained': 0, 'excepted': 0}
    edges = sorted((d, old, new) for old, lst in secs.fwd.items() for d, new in lst if start <= d <= end)
    for d, old, new in edges:
        c['in_range'] += 1
        old_runs, new_runs = runs.get(old, []), runs.get(new, [])
        if not old_runs and not new_runs:
            c['not_seen'] += 1
            continue
        nr = next((r for r in new_runs if abs((r['first_date'] - d).days) <= RENAME_WINDOW_DAYS), None)
        orun = None
        if nr:
            orun = next((r for r in reversed(old_runs) if r['last_date'] < nr['first_date']), None)
        if nr is None or orun is None:
            c['one_side'] += 1
            seen = 'old only' if old_runs and not nr else ('new only' if nr else 'new not near rename date')
            issues.append(['rename_one_side', old, new, d.isoformat(), '', '', seen])
            continue
        gap = (nr['first_date'] - orun['last_date']).days
        factor = (cumulative_factor(table, old, orun['last_date'], nr['first_date'])
                  * cumulative_factor(table, new, orun['last_date'], nr['first_date']))
        adj = nr['first_close'] / orun['last_close'] * factor
        isin_same = orun['last_isin'] == nr['first_isin']
        detail = (f"{old} {orun['last_date']} {orun['last_close']} {orun['last_isin']} -> "
                  f"{new} {nr['first_date']} {nr['first_close']} {nr['first_isin']}")
        problem = None
        if gap > RUN_BREAK_DAYS:
            c['gap'] += 1
            problem = 'rename_gap'
        elif not isin_same and factor == 1.0:
            problem = 'rename_isin_unexplained'
        elif abs(adj - 1) > STITCH_LIMIT:
            problem = 'rename_outside_limit'
        if problem is None:
            c['confirmed'] += 1
            continue
        reason = exceptions.get(('rename_ok', old, new, d.isoformat()))
        if reason:
            c['excepted'] += 1
            issues.append(['rename_excepted', old, new, d.isoformat(), f'{adj:.4f}', f'{gap}d', f'{detail} | {reason}'])
            continue
        if problem == 'rename_isin_unexplained':
            c['isin_unexplained'] += 1
        elif problem == 'rename_outside_limit':
            c['outside_limit'] += 1
        issues.append([problem, old, new, d.isoformat(), f'{adj:.4f}', f'{gap}d', detail])
    return c


def find_candidates(secs: Securities, runs: dict, days: list, exceptions: dict, issues: list) -> dict:
    """Find A-ends/B-starts pairs with the same ISIN; append issue rows; return counts."""
    index = {d: i for i, d in enumerate(days)}
    starts: dict = {}
    for symbol, lst in runs.items():
        for r in lst:
            starts.setdefault(r['first_isin'], []).append((r['first_date'], symbol, r))
    c = {'candidates': 0, 'known_rename': 0, 'excepted': 0, 'unresolved': 0}
    for a, lst in runs.items():
        for r in lst:
            last_i = index[r['last_date']]
            if last_i >= len(days) - 1:
                continue
            for first, b, rb in starts.get(r['last_isin'], ()):
                if b == a or not 0 < index[first] - last_i <= CONTINUITY_SESSIONS:
                    continue
                c['candidates'] += 1
                detail = (f"{a} last {r['last_date']} {r['last_close']} -> {b} first {first} {rb['first_close']} "
                          f"ISIN {r['last_isin']}")
                if secs.key_on(a, r['last_date']) == secs.key_on(b, first):
                    c['known_rename'] += 1
                    continue
                reason = exceptions.get(('not_rename', a, b, first.isoformat()))
                if reason:
                    c['excepted'] += 1
                    issues.append(['candidate_not_rename', a, b, first.isoformat(), '', '', f'{detail} | {reason}'])
                else:
                    c['unresolved'] += 1
                    issues.append(['candidate_unresolved', a, b, first.isoformat(), '', '', detail])
    return c


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', type=date.fromisoformat, default=DEFAULT_START)
    ap.add_argument('--end', type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])

    secs = Securities.load()
    table = load_history()
    exceptions = load_exceptions()
    runs, days = scan_runs(args.start, args.end)
    issues: list = []
    ren = check_renames(secs, runs, table, args.start, days[-1] if days else args.end, exceptions, issues)
    cand = find_candidates(secs, runs, days, exceptions, issues)

    logger.info(f'SCAN: {len(days)} trading days {args.start}..{days[-1] if days else None}, '
                f'{len(runs)} equity symbols, {sum(len(v) for v in runs.values())} runs')
    logger.info(f'RENAMES: {ren}')
    logger.info(f'CANDIDATES: {cand}')
    out = LOG_DIR / f'validate_symbol_changes_{date.today():%Y%m%d}.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['check', 'old', 'new', 'date', 'adj_move', 'gap', 'detail'])
        w.writerows(issues)
    logger.info(f'{len(issues)} issue rows -> {out}')

    failed = []
    if ren['outside_limit']:
        failed.append(f"{ren['outside_limit']} stitches outside +/-{STITCH_LIMIT:.0%}")
    if ren['isin_unexplained']:
        failed.append(f"{ren['isin_unexplained']} renames with an unexplained ISIN change")
    if cand['unresolved']:
        failed.append(f"{cand['unresolved']} unresolved continuity candidates")
    logger.info('RESULT: ' + ('FAIL -- ' + '; '.join(failed) if failed else 'PASS'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
