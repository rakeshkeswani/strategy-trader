# -*- coding: utf-8 -*-
# core/demergers.py
"""
ST-019 -- demergers (spin-offs) as price factors, like splits (Rakesh, 2026-10-15, option a).

Source: demerger / scheme-of-arrangement / spin-off records (EQ series) in the stored NSE corporate-action feed
(CORPORATE_ACTIONS_DIR/raw/<year>.json, fetched by ST-003). Factor = close on the last trading day before the ex-date /
close on the first trading day on/after it (Rakesh, 2026-10-15: the ex-day OPEN is often not the discovered price --
ADANIENT 2015 opened 573 vs 637 before and closed 110; price discovery runs through the day -- so the close is used;
it also absorbs that day's genuine move, a few percent). Applied only when the price FELL by more than GAP_MIN; smaller
falls and any rise are listed, not applied (value leaving the company can only lower the price; a scheme that moves no
value would only add market noise). The reviewed list lives in config/demergers.csv (scripts/build_demergers.py writes
it; a note starting 'REVIEWED' records a decision a rebuild keeps; Rakesh approves the list).

A demerger leaves the share count unchanged, so its factor scales prices only, never volume (core/adjusted.py).
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core.config import CORPORATE_ACTIONS_DIR, REPO_ROOT

DEMERGERS_CSV = REPO_ROOT / 'config' / 'demergers.csv'
SUBJECT_RE = re.compile(r'demerg|spin[ -]?off|scheme of arrangement', re.I)
GAP_MIN = 0.05
NEXT_TRADE_DAYS = 10          # first trade on/after the ex-date must be within this many days
COLUMNS = ['symbol', 'ex_date', 'subject', 'prev_date', 'prev_close', 'ex_trade_date', 'ex_open', 'ex_close',
           'next1_close', 'next2_close', 'gap', 'factor', 'applied', 'note']


def feed_records(raw_dir: Path = CORPORATE_ACTIONS_DIR / 'raw') -> pd.DataFrame:
    """Demerger-type EQ records from the stored feed: symbol, ex_date, subject (one row per symbol and ex-date)."""
    rows = []
    for f in sorted(raw_dir.glob('*.json')):
        for r in json.loads(f.read_text(encoding='utf-8')):
            subj = ' '.join(str(r.get('subject', '')).split())
            if r.get('series') != 'EQ' or not SUBJECT_RE.search(subj):
                continue
            try:
                ex = datetime.strptime(str(r.get('exDate')), '%d-%b-%Y').date()
            except ValueError:
                continue
            rows.append({'symbol': r['symbol'], 'ex_date': ex, 'subject': subj})
    d = pd.DataFrame(rows, columns=['symbol', 'ex_date', 'subject'])
    d = d.groupby(['symbol', 'ex_date'], as_index=False)['subject'].agg(lambda s: ' | '.join(dict.fromkeys(s)))
    return d.sort_values(['ex_date', 'symbol']).reset_index(drop=True)


def price_row(row: dict) -> dict:
    """Set gap, factor and applied (falls beyond GAP_MIN only) from the ex-day close; the reason goes to `note` when
    not applied."""
    pc, ref = row['prev_close'], row['ex_close']
    row['gap'], row['factor'] = round(ref / pc - 1, 6), round(pc / ref, 6)
    if row['gap'] < -GAP_MIN:
        row['applied'] = 'Y'
    else:
        row['applied'] = 'N'
        row['note'] = (f"price rose {row['gap']:.1%} on the ex-date: no value left the company; not applied"
                       if row['gap'] > GAP_MIN else f'fall within {GAP_MIN:.0%}: not applied')
    return row


def candidates(records: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Price each record from the RAW panel (trade_date, symbol, open, close): previous close, ex-day open and close,
    the next two closes, gap = ex-day close / previous close - 1, factor = previous close / ex-day close, and applied
    (price_row); `note` says why when not applied."""
    p = panel[panel['symbol'].isin(set(records['symbol']))].sort_values('trade_date')
    by_sym = {s: g for s, g in p.groupby('symbol')}
    out = []
    for r in records.itertuples():
        row = {'symbol': r.symbol, 'ex_date': r.ex_date, 'subject': r.subject, 'prev_date': None, 'prev_close': None,
               'ex_trade_date': None, 'ex_open': None, 'ex_close': None, 'next1_close': None, 'next2_close': None,
               'gap': None, 'factor': None, 'applied': 'N', 'note': ''}
        g = by_sym.get(r.symbol)
        before = g[g['trade_date'] < r.ex_date].tail(1) if g is not None else None
        on = g[(g['trade_date'] >= r.ex_date) & (g['trade_date'] <= r.ex_date + timedelta(days=NEXT_TRADE_DAYS))].head(1) \
            if g is not None else None
        if before is None or before.empty or on is None or on.empty:
            row['note'] = 'no EQ trade around the ex-date in the panel: nothing to adjust'
        else:
            pc, cl = float(before['close'].iloc[0]), float(on['close'].iloc[0])
            nxt = g[g['trade_date'] > on['trade_date'].iloc[0]].head(2)['close'].tolist()
            row.update(prev_date=before['trade_date'].iloc[0], prev_close=pc, ex_trade_date=on['trade_date'].iloc[0],
                       ex_open=float(on['open'].iloc[0]), ex_close=cl,
                       next1_close=nxt[0] if len(nxt) > 0 else None, next2_close=nxt[1] if len(nxt) > 1 else None)
            row = price_row(row)
        out.append(row)
    return pd.DataFrame(out, columns=COLUMNS)


def merge_reviewed(fresh: pd.DataFrame, existing: pd.DataFrame | None) -> pd.DataFrame:
    """Keep reviewed decisions on a rebuild: where the existing row's note starts with 'REVIEWED', its `applied` and
    note win over the fresh values (prices and factor are always fresh)."""
    if existing is None or existing.empty:
        return fresh
    keep = existing[existing['note'].fillna('').str.startswith('REVIEWED')].copy()
    keep['ex_date'] = pd.to_datetime(keep['ex_date']).dt.date
    k = {(s, d): (a, n) for s, d, a, n in zip(keep['symbol'], keep['ex_date'], keep['applied'], keep['note'])}
    out = fresh.copy()
    for i, r in out.iterrows():
        if (r['symbol'], r['ex_date']) in k:
            out.at[i, 'applied'], out.at[i, 'note'] = k[(r['symbol'], r['ex_date'])]
    return out


def load_demergers(path: Path = DEMERGERS_CSV) -> pd.DataFrame:
    """Applied rows as actions: symbol, ex_date, factor, kind='demerger' (empty frame when the file is absent)."""
    if not path.exists():
        return pd.DataFrame(columns=['symbol', 'ex_date', 'factor', 'kind'])
    d = pd.read_csv(path)
    d = d[d['applied'].astype(str).str.upper() == 'Y']
    if d['factor'].isna().any():
        raise ValueError(f'{path}: applied row without a factor: {d[d["factor"].isna()][["symbol", "ex_date"]].values.tolist()}')
    return pd.DataFrame({'symbol': d['symbol'], 'ex_date': pd.to_datetime(d['ex_date']).dt.date,
                         'factor': d['factor'].astype(float), 'kind': 'demerger'}).reset_index(drop=True)
