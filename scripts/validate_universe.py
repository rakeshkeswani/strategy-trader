# -*- coding: utf-8 -*-
# scripts/validate_universe.py
"""
ST-004 acceptance checks for the price panel and the point-in-time universe. Read-only (one GET to NSE).

1. PANEL COVERAGE: every trading day from the panel's first day to the latest available bhavcopy is in the panel, with
   exactly as many rows as that day's equities (core.prices + core.securities.is_equity); SAMPLE_ROWS random panel
   rows match the raw files exactly.
2. NO LOOKAHEAD: every review is rebuilt from a panel cut at its cut-off date and must equal membership.csv exactly
   (series_id and rank). A review with < 500 members while > 500 were eligible fails.
3. SURVIVORSHIP: each named company is a member of at least one review in force before its event date; and every review
   with a cut-off before AUTO_SURVIVOR_BEFORE has >= 1 member whose series no longer trades (last close more than
   STALE_DAYS before the panel's last day).
4. FIDELITY: the review in force today vs NSE's current Nifty 500 list (ind_nifty500list.csv): overlap >= MIN_OVERLAP
   of the real list and >= MIN_TOP100 of our top 100 in it (Rakesh, 2026-10-14).

Writes logs/validate_universe_<date>.csv. Exit code 0 only when RESULT: PASS.
Usage: python -m scripts.validate_universe [--skip-coverage]
"""

import argparse
import csv
import io
import logging
import random
import sys
from datetime import date, timedelta

import pandas as pd
import requests

from core.config import LOG_DIR
from core.panel import read_panel
from core.prices import BhavcopyDateMissingError, read_ohlcv_for_date
from core.securities import is_equity
from core.universe import PANEL_COLUMNS, build_review, load_membership, members_on, review_calendar

logger = logging.getLogger('validate_universe')
SAMPLE_ROWS = 1000
NSE_LIST_URL = 'https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv'
HEADERS = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
           'Referer': 'https://www.nseindia.com/'}
MIN_OVERLAP = 0.80
MIN_TOP100 = 95
AUTO_SURVIVOR_BEFORE = date(2024, 1, 1)
STALE_DAYS = 30
# company_key -> event date: must be a member of a review in force before this date
SURVIVORS = {
    'JETAIRWAYS': date(2019, 4, 17),   # grounded; insolvency June 2019
    'DHFL': date(2018, 9, 21),         # crash; later insolvency
    'YESBANK': date(2020, 3, 5),       # RBI moratorium
    'HDFC': date(2023, 7, 13),         # merged into HDFCBANK; symbol gone
    'IDEA': date(2019, 10, 24),        # AGR judgment
}


def check_coverage(panel: pd.DataFrame, issues: list) -> dict:
    """Compare panel rows per day with each day's raw bhavcopy, and SAMPLE_ROWS random rows field by field."""
    first, last_panel = panel['trade_date'].min(), panel['trade_date'].max()
    per_day = panel.groupby('trade_date').size().to_dict()
    random.seed(20261014)
    sample = panel.sample(SAMPLE_ROWS, random_state=20261014)
    sample_by_day: dict = {}
    for r in sample.itertuples(index=False):
        sample_by_day.setdefault(r.trade_date, []).append(r)
    c = {'days_checked': 0, 'days_missing_in_panel': 0, 'days_count_mismatch': 0, 'panel_days_without_file': 0,
         'sample_rows': len(sample), 'sample_mismatch': 0, 'last_file_day': None}
    d = first
    while d <= date.today():
        try:
            day = read_ohlcv_for_date(d)
        except BhavcopyDateMissingError:
            if d in per_day:
                c['panel_days_without_file'] += 1
                issues.append(['panel_day_without_file', d.isoformat(), '', ''])
            d += timedelta(days=1)
            continue
        c['days_checked'] += 1
        c['last_file_day'] = d
        eq = {s: r for s, r in day.items() if is_equity(s, r.get('isin')) and r.get('close')}
        n = per_day.get(d)
        if n is None:
            c['days_missing_in_panel'] += 1
            issues.append(['day_missing_in_panel', d.isoformat(), len(eq), ''])
        elif n != len(eq):
            c['days_count_mismatch'] += 1
            issues.append(['day_count_mismatch', d.isoformat(), len(eq), n])
        for r in sample_by_day.get(d, ()):
            raw = eq.get(r.symbol)
            if raw is None or any(raw.get(f) != getattr(r, f) for f in ('close', 'volume', 'traded_value', 'isin')):
                c['sample_mismatch'] += 1
                issues.append(['sample_mismatch', d.isoformat(), r.symbol, ''])
        d += timedelta(days=1)
    c['panel_last_day'] = last_panel
    return c


def check_no_lookahead(panel: pd.DataFrame, membership: pd.DataFrame, issues: list) -> dict:
    """Rebuild each review from a panel cut at its cut-off and compare with membership.csv."""
    c = {'reviews': 0, 'identical': 0, 'different': 0, 'short': 0}
    stored = {k: g for k, g in membership.groupby('cutoff_date')}
    for cutoff, effective in review_calendar(list(panel['trade_date'].unique())):
        c['reviews'] += 1
        rebuilt, counts = build_review(panel[panel['trade_date'] <= cutoff], cutoff, effective)
        mine = stored.get(cutoff)
        same = mine is not None and list(rebuilt['series_id']) == list(mine.sort_values('rank')['series_id'])
        c['identical' if same else 'different'] += 1
        if not same:
            issues.append(['review_differs', cutoff.isoformat(), len(rebuilt), 0 if mine is None else len(mine)])
        if counts['members'] < 500 and counts['eligible'] > 500:
            c['short'] += 1
            issues.append(['review_short', cutoff.isoformat(), counts['members'], counts['eligible']])
    c['stored_reviews'] = len(stored)
    return c


def check_survivorship(panel: pd.DataFrame, membership: pd.DataFrame, issues: list) -> dict:
    """Named spot checks plus the automatic 'members that no longer trade' count per review."""
    c = {'named_ok': 0, 'named_missing': 0, 'reviews_checked': 0, 'reviews_without_dead_member': 0}
    for key, event in SURVIVORS.items():
        hits = membership[(membership['company_key'] == key) & (membership['effective_from'] < event)]
        if hits.empty:
            c['named_missing'] += 1
            issues.append(['survivor_missing', key, event.isoformat(), ''])
        else:
            c['named_ok'] += 1
            issues.append(['survivor_ok', key, f"{len(hits)} reviews", f"last effective {hits['effective_from'].max()}"])
    last_day = panel['trade_date'].max()
    last_seen = panel.groupby('series_id')['trade_date'].max()
    dead = set(last_seen[last_seen < last_day - timedelta(days=STALE_DAYS)].index)
    for cutoff, g in membership.groupby('cutoff_date'):
        if cutoff >= AUTO_SURVIVOR_BEFORE:
            continue
        c['reviews_checked'] += 1
        gone = sorted(set(g['series_id']) & dead)
        issues.append(['review_dead_members', cutoff.isoformat(), len(gone), ' '.join(s.split('@')[0] for s in gone[:12])])
        if not gone:
            c['reviews_without_dead_member'] += 1
    return c


def check_fidelity(membership: pd.DataFrame, issues: list) -> dict:
    """Overlap of the review in force today with NSE's current Nifty 500 list."""
    resp = requests.get(NSE_LIST_URL, headers=HEADERS, timeout=(10, 60))
    resp.raise_for_status()
    real = pd.read_csv(io.BytesIO(resp.content))
    theirs = set(real['Symbol'].astype(str).str.strip())
    cur = members_on(membership, date.today())
    ours = set(cur['company_key'])
    top = set(cur[cur['rank'] <= 100]['company_key'])
    c = {'effective_from': cur['effective_from'].iloc[0] if len(cur) else None, 'real': len(theirs),
         'ours': len(ours), 'overlap': len(ours & theirs), 'overlap_pct': round(len(ours & theirs) / len(theirs), 4),
         'top100_in_real': len(top & theirs)}
    issues.append(['fidelity_only_real', '', len(theirs - ours), ' '.join(sorted(theirs - ours)[:40])])
    issues.append(['fidelity_only_ours', '', len(ours - theirs), ' '.join(sorted(ours - theirs)[:40])])
    return c


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--skip-coverage', action='store_true', help='skip the slow raw-file comparison (trials only)')
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    issues: list = []
    panel = read_panel(columns=PANEL_COLUMNS + ['isin', 'volume'])
    membership = load_membership()
    failed = []

    if not args.skip_coverage:
        cov = check_coverage(panel, issues)
        logger.info(f'COVERAGE: {cov}')
        if cov['days_missing_in_panel'] or cov['days_count_mismatch'] or cov['panel_days_without_file'] \
                or cov['sample_mismatch']:
            failed.append('panel coverage')
    else:
        failed.append('coverage skipped')
    look = check_no_lookahead(panel, membership, issues)
    logger.info(f'NO LOOKAHEAD: {look}')
    if look['different'] or look['short'] or look['stored_reviews'] != look['reviews']:
        failed.append('review rebuild differs / short / count mismatch')
    surv = check_survivorship(panel, membership, issues)
    logger.info(f'SURVIVORSHIP: {surv}')
    if surv['named_missing'] or surv['reviews_without_dead_member']:
        failed.append('survivorship')
    try:
        fid = check_fidelity(membership, issues)
        logger.info(f'FIDELITY: {fid}')
        if fid['overlap_pct'] < MIN_OVERLAP or fid['top100_in_real'] < MIN_TOP100:
            failed.append(f"fidelity {fid['overlap_pct']:.1%} / top100 {fid['top100_in_real']}")
    except (requests.RequestException, KeyError, ValueError) as e:
        failed.append(f'fidelity not checked: {e}')

    out = LOG_DIR / f'validate_universe_{date.today():%Y%m%d}.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['check', 'key', 'value1', 'value2'])
        w.writerows(issues)
    logger.info(f'{len(issues)} rows -> {out}')
    logger.info('RESULT: ' + ('FAIL -- ' + '; '.join(failed) if failed else 'PASS'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
