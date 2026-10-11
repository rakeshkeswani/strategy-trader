# -*- coding: utf-8 -*-
# scripts/validate_corporate_actions.py
"""
ST-003 acceptance checks for the corporate-actions history (2014-01-01..2025-08-25). Read-only.

1. FEED: raw/<YYYY>.json present for every year with >= 1 record; re-parsed with core.corporate_actions,
   0 unclassified subjects. REVIEW items (capital reductions) each need a decision row in config/ca_exceptions.csv.
2. JUMP SCAN: streams every trading day through core.prices (the same entry point the rest of the code uses) and
   tracks each symbol's last close. Equities only: ISIN starting INE (or IN9, DVR shares), symbol not ending
   -RE / -RE<n> (ETFs/gold units have INF ISINs and their unit splits are not in this feed; rights entitlements
   collapse by design). Skipped
   symbols are counted by ISIN prefix so the filter cannot hide anything unexpected. For every stored action, the ADJUSTED move from the last close before ex_date
   to the first close on/after it must be within +/-30% (fail otherwise: wrong or unapplied factor). Every RAW
   one-day move worse than -35% with no stored action between the two closes must be explained: automatically when
   the feed holds any record for that symbol between the two dates (demerger, rights, ...), as a tick move when the
   previous close is below Rs 1, as a suspension gap when the two closes are more than SUSPENSION_GAP_DAYS apart
   AND the ISIN is unchanged (a changed ISIN across a gap may hide a split, so it is never auto-explained), or by a
   'drop' row in config/ca_exceptions.csv. Feed actions are corrected in
   config/ca_overrides.csv (VOID/ADD, applied by core.corporate_actions.load_history).
3. PREVCLOSE PROBE (legacy files only): on an ex_date, is the file's PREVCLOSE the NSE-adjusted previous close?
   Reported as a share of actions; when it is, last close / PREVCLOSE is an independent factor and mismatches
   > 2% are listed.
4. SPOT CHECK: a few known events against yfinance's own split/bonus-adjusted closes (scale-free move compare).

Writes logs/validate_corporate_actions_<date>.csv. Exit code 0 only when RESULT: PASS.

Usage: python -m scripts.validate_corporate_actions [--start 2021-01-01 --end 2021-12-31] [--skip-spot]
"""

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from core.config import CORPORATE_ACTIONS_DIR, LOG_DIR, REPO_ROOT
from core.corporate_actions import classify_records, cumulative_factor, load_history, load_overrides
from core.prices import BhavcopyDateMissingError, read_ohlcv_for_date
from core.symbol_changes import load_changes, symbol_on
from ingestion.fetch_corporate_actions_history import HISTORY_END, HISTORY_START

logger = logging.getLogger('validate_corporate_actions')
EXCEPTIONS_FILE = REPO_ROOT / 'config' / 'ca_exceptions.csv'
ACTION_MOVE_LIMIT = 0.30
DROP_THRESHOLD = 0.65          # raw close / previous close below this = a drop worse than -35%
PENNY_PRICE = 1.0              # previous close below Rs 1: a one-tick move can be -50%
SUSPENSION_GAP_DAYS = 30       # longest normal NSE closure is ~5 days; > 30 calendar days without a close = suspension
_RIGHTS_ENTITLEMENT = re.compile(r'-RE\d*$')
PREVCLOSE_TOLERANCE = 0.02
SPOT_EVENTS = [                 # (symbol, ex_date) -- known events; yfinance closes are split/bonus-adjusted
    ('AJANTPHARM', date(2015, 3, 20)), ('SRF', date(2021, 10, 13)), ('NYKAA', date(2022, 11, 10)),
    ('VBL', date(2024, 9, 12)), ('BAJFINANCE', date(2025, 6, 16)),
]


def load_exceptions(path: Path = EXCEPTIONS_FILE) -> dict:
    """Load config/ca_exceptions.csv into {(kind, symbol, iso_date): reason}; empty when absent."""
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8') as f:
        return {(r['kind'], r['symbol'], r['date']): r['reason'] for r in csv.DictReader(f)}


def check_feed(raw_dir: Path, issues: list, changes: dict) -> tuple[dict, dict]:
    """Per-year counts and a re-parse of every record.

    Returns (summary, feed index {symbol in use on ex_date: [(ex_date, subject)]}).
    """
    summary = {'years_missing': [], 'years_empty': [], 'records': 0}
    records: list = []
    for year in range(HISTORY_START.year, HISTORY_END.year + 1):
        path = raw_dir / f'{year}.json'
        if not path.exists():
            summary['years_missing'].append(year)
            continue
        recs = json.loads(path.read_bytes())
        if not recs:
            summary['years_empty'].append(year)
        records += recs
    summary['records'] = len(records)
    _, parse_issues, counts = classify_records(records, HISTORY_END + timedelta(days=1), changes)
    summary.update({k: counts[k] for k in ('BONUS', 'SPLIT', 'CONSOLIDATION', 'excluded', 'review', 'unclassified')})
    for kind, symbol, ex_date, detail in parse_issues:
        if kind in ('review', 'unclassified'):
            issues.append(['feed_' + kind, symbol, ex_date, '', '', '', detail])
    index: dict = {}
    for rec in records:
        try:
            d = datetime.strptime(rec.get('exDate') or '', '%d-%b-%Y').date()
        except ValueError:
            continue
        if rec.get('symbol'):
            index.setdefault(symbol_on(changes, rec['symbol'], d), []).append((d, (rec.get('subject') or '').strip()))
    return summary, index


def is_equity(symbol: str, isin: str | None) -> bool:
    """True for a listed equity: ISIN starting INE or IN9 (DVR), and not a -RE/-RE<n> rights entitlement."""
    return bool(isin) and isin[:3] in ('INE', 'IN9') and not _RIGHTS_ENTITLEMENT.search(symbol)


def scan_prices(table: dict, start: date, end: date, watch: set | None = None) -> tuple[dict, list, int, dict]:
    """Stream every trading day over equities.

    `watch` is a set of (symbol, date) whose first move on/after that date is recorded even with no stored action
    (capital reductions under review). Returns (moves {(symbol, ex_date): row} for stored actions and watched
    items, raw drops [row], trading days, skipped {isin prefix: symbols}).
    """
    last: dict = {}
    moves: dict = {}
    drops: list = []
    skipped: dict = {}
    watch_by_symbol: dict = {}
    for s, wd in watch or ():
        watch_by_symbol.setdefault(s, []).append(wd)
    days = 0
    d = start
    while d <= end:
        try:
            day = read_ohlcv_for_date(d)
        except BhavcopyDateMissingError:
            d += timedelta(days=1)
            continue
        days += 1
        if days % 250 == 0:
            logger.info(f'scanned {days} trading days (to {d})')
        for symbol, rec in day.items():
            if not is_equity(symbol, rec.get('isin')):
                prefix = 'RE' if _RIGHTS_ENTITLEMENT.search(symbol) else (rec.get('isin') or 'NONE')[:3]
                skipped.setdefault(prefix, set()).add(symbol)
                continue
            close = rec.get('close')
            if not close:
                continue
            if symbol in last:
                prev_date, prev_close, prev_isin = last[symbol]
                raw = close / prev_close
                factor = cumulative_factor(table, symbol, prev_date, d)
                row = {'symbol': symbol, 'prev_date': prev_date, 'prev_close': prev_close, 'date': d,
                       'close': close, 'raw': raw, 'factor': factor, 'adj': raw * factor,
                       'prevclose_field': rec.get('prev_close'), 'source': rec.get('source'),
                       'isin_changed': prev_isin != rec.get('isin')}
                if factor != 1.0:
                    for ex_date, _ in table.get(symbol, ()):
                        if prev_date < ex_date <= d:
                            moves[(symbol, ex_date)] = row
                elif raw < DROP_THRESHOLD:
                    drops.append(row)
                for wd in watch_by_symbol.get(symbol, ()):
                    if prev_date < wd <= d:
                        moves[(symbol, wd)] = row
            last[symbol] = (d, close, rec.get('isin'))
        d += timedelta(days=1)
    return moves, drops, days, skipped


def spot_check(table: dict, moves: dict, issues: list) -> dict:
    """Compare our adjusted ex-date move with yfinance's (closes already split/bonus-adjusted) for SPOT_EVENTS."""
    try:
        import yfinance as yf
    except ImportError:
        return {'spot': 'skipped (no yfinance)'}
    ok = bad = 0
    for symbol, ex_date in SPOT_EVENTS:
        ours = moves.get((symbol, ex_date))
        if ours is None:
            issues.append(['spot_not_scanned', symbol, ex_date.isoformat(), '', '', '', 'outside scan range or no move'])
            continue
        try:
            df = yf.download(f'{symbol}.NS', start=(ours['prev_date'] - timedelta(days=3)).isoformat(),
                             end=(ours['date'] + timedelta(days=3)).isoformat(), progress=False, auto_adjust=False)
            closes = {ts.date(): float(v) for ts, v in df['Close'].iloc[:, 0].items()}
            theirs = closes[ours['date']] / closes[ours['prev_date']]
        except (KeyError, IndexError, ValueError) as e:
            issues.append(['spot_unavailable', symbol, ex_date.isoformat(), '', '', '', f'yfinance: {e}'])
            continue
        diff = abs(ours['adj'] / theirs - 1)
        if diff <= PREVCLOSE_TOLERANCE:
            ok += 1
        else:
            bad += 1
            issues.append(['spot_mismatch', symbol, ex_date.isoformat(), f"{ours['adj']:.4f}", f'{theirs:.4f}', '',
                           'our adjusted move vs yfinance'])
    return {'spot_ok': ok, 'spot_mismatch': bad}


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', type=date.fromisoformat, default=HISTORY_START)
    ap.add_argument('--end', type=date.fromisoformat, default=HISTORY_END)
    ap.add_argument('--skip-spot', action='store_true')
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    full_range = args.start == HISTORY_START and args.end == HISTORY_END

    issues: list = []
    exceptions = load_exceptions()
    feed, feed_index = check_feed(CORPORATE_ACTIONS_DIR / 'raw', issues, load_changes())
    logger.info(f'FEED: {feed}')
    table = load_history(CORPORATE_ACTIONS_DIR / 'history.csv')
    stored = [(s, ex) for s, lst in table.items() for ex, _ in lst if args.start <= ex <= args.end]

    watch = {(i[1], date.fromisoformat(i[2])) for i in issues if i[0] == 'feed_review'}
    moves, drops, days, skipped = scan_prices(table, args.start, args.end, watch)

    # 2a. every stored action's adjusted move
    act = {'actions_in_range': len(stored), 'observed': 0, 'not_observed': 0, 'outside_limit': 0}
    probe = {'legacy_checked': 0, 'prevclose_adjusted': 0, 'prevclose_raw': 0, 'factor_mismatch': 0}
    for symbol, ex_date in stored:
        m = moves.get((symbol, ex_date))
        key = ('not_observed', symbol, ex_date.isoformat())
        if m is None:
            act['not_observed'] += 1
            reason = exceptions.get(key, '')
            issues.append(['action_not_observed', symbol, ex_date.isoformat(), '', '', '',
                           reason or 'symbol not traded around ex_date (missed rename?)'])
            if not reason:
                act['not_observed_unexplained'] = act.get('not_observed_unexplained', 0) + 1
            continue
        act['observed'] += 1
        if abs(m['adj'] - 1) > ACTION_MOVE_LIMIT:
            act['outside_limit'] += 1
            issues.append(['action_outside_limit', symbol, ex_date.isoformat(), f"{m['raw']:.4f}", f"{m['adj']:.4f}",
                           f"{m['factor']:.4f}", f"{m['prev_date']} {m['prev_close']} -> {m['date']} {m['close']}"])
        # 3. PREVCLOSE probe: legacy rows, first close on the ex_date itself
        if m['source'] != 'NSE_UDIFF' and m['date'] == ex_date and m['prevclose_field']:
            probe['legacy_checked'] += 1
            expected_adj = m['prev_close'] / m['factor']
            if abs(m['prevclose_field'] / expected_adj - 1) <= PREVCLOSE_TOLERANCE:
                probe['prevclose_adjusted'] += 1
            elif abs(m['prevclose_field'] / m['prev_close'] - 1) <= PREVCLOSE_TOLERANCE:
                probe['prevclose_raw'] += 1
            else:
                probe['factor_mismatch'] += 1
                issues.append(['prevclose_factor_mismatch', symbol, ex_date.isoformat(),
                               f"{m['prev_close'] / m['prevclose_field']:.4f}", f"{m['factor']:.4f}", '',
                               'implied factor (last close / PREVCLOSE) vs stored'])

    # 2b. raw drops with no stored action
    drop = {'raw_drops': len(drops), 'explained_by_feed': 0, 'tick_move': 0, 'suspension_gap': 0,
            'explained_by_exception': 0, 'unexplained': 0}
    for m in drops:
        key = ('drop', m['symbol'], m['date'].isoformat())
        feed_hits = [s for d, s in feed_index.get(m['symbol'], ()) if m['prev_date'] < d <= m['date']]
        if feed_hits:
            drop['explained_by_feed'] += 1
            kind, why = 'drop_feed', '; '.join(feed_hits)[:200]
        elif m['prev_close'] < PENNY_PRICE:
            drop['tick_move'] += 1
            kind, why = 'drop_tick', f'previous close below Rs {PENNY_PRICE:g}'
        elif (m['date'] - m['prev_date']).days > SUSPENSION_GAP_DAYS and not m['isin_changed']:
            drop['suspension_gap'] += 1
            kind, why = 'drop_gap', f'no close for {(m["date"] - m["prev_date"]).days} days, ISIN unchanged'
        elif key in exceptions:
            drop['explained_by_exception'] += 1
            kind, why = 'drop_exception', exceptions[key]
        else:
            drop['unexplained'] += 1
            kind, why = 'drop_unexplained', ''
        isin_note = 'ISIN CHANGED' if m['isin_changed'] else 'ISIN same'
        issues.append([kind, m['symbol'], m['date'].isoformat(), f"{m['raw']:.4f}", isin_note,
                       f"{(m['date'] - m['prev_date']).days}d",
                       f"{m['prev_date']} {m['prev_close']} -> {m['date']} {m['close']} {why}".strip()])

    # 1b. review items need a decision: an ADD override, or a 'review' row in ca_exceptions.csv (no scale change)
    added = {(o['symbol'], o['ex_date'].isoformat()) for o in load_overrides() if o['kind'] == 'ADD'}
    review_open = [i for i in issues if i[0] == 'feed_review'
                   and ('review', i[1], i[2]) not in exceptions and (i[1], i[2]) not in added]
    for i in issues:
        if i[0] == 'feed_review':
            m = moves.get((i[1], date.fromisoformat(i[2])))
            i[3] = (f"raw {m['raw']:.4f} ({m['prev_date']} {m['prev_close']} -> {m['date']} {m['close']}, "
                    f"{'ISIN CHANGED' if m['isin_changed'] else 'ISIN same'})") if m else 'not traded around date'
    spot = {} if args.skip_spot else spot_check(table, moves, issues)

    logger.info(f'SCAN: {days} trading days {args.start}..{args.end}; skipped non-equity symbols by ISIN prefix: '
                f'{ {k: len(v) for k, v in sorted(skipped.items())} }')
    odd = {k: sorted(v)[:15] for k, v in skipped.items() if k not in ('INF', 'RE')}
    if odd:
        logger.warning(f'skipped symbols with unexpected ISIN prefixes (check these): {odd}')
    logger.info(f'ACTIONS: {act}')
    logger.info(f'PREVCLOSE PROBE: {probe}')
    logger.info(f'DROPS: {drop}')
    logger.info(f"REVIEW: {feed['review']} capital reductions, {len(review_open)} without a decision")
    if spot:
        logger.info(f'SPOT: {spot}')

    out = LOG_DIR / f'validate_corporate_actions_{date.today():%Y%m%d}.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['check', 'symbol', 'date', 'value1', 'value2', 'factor', 'detail'])
        w.writerows(issues)
    logger.info(f'{len(issues)} issue rows -> {out}')

    failed = []
    if full_range and (feed['years_missing'] or feed['years_empty']):
        failed.append('years missing/empty')
    if feed['unclassified']:
        failed.append('unclassified subjects')
    if act.get('not_observed_unexplained'):
        failed.append(f"{act['not_observed_unexplained']} stored actions never observed (missed rename?)")
    if act['outside_limit']:
        failed.append(f"{act['outside_limit']} actions outside +/-{ACTION_MOVE_LIMIT:.0%}")
    if drop['unexplained']:
        failed.append(f"{drop['unexplained']} unexplained drops")
    if review_open:
        failed.append(f'{len(review_open)} review items without a decision')
    if spot.get('spot_mismatch'):
        failed.append('spot mismatch')
    logger.info('RESULT: ' + ('FAIL -- ' + '; '.join(failed) if failed else 'PASS'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
