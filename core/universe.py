# -*- coding: utf-8 -*-
# core/universe.py
"""
ST-004 -- point-in-time top-500 universe, the backtest stand-in for the Nifty 500 (plan doc: removes survivorship bias).

Aligned to NSE's Nifty 500 review (niftyindices.com factsheet; Rakesh 2026-10-11):
  - cut-off: the last trading day of January and July;
  - window: the six months ending at the cut-off (trading days after the same date six months earlier);
  - eligible: an equity series that is EQ on the cut-off day, traded on >= MIN_TRADING_FREQ of the window's sessions,
    close >= MIN_PRICE on the cut-off day;
  - rank: median daily traded value over the window (NSE ranks by full market cap; we have no free history of shares
    outstanding, so traded value is the proxy -- overlap with the real index is measured by the validator);
  - membership takes effect from the first trading day of April / October (after NSE's four-week notice) and holds
    until the next review takes effect.
Point-in-time: a review uses only panel rows dated on or before its cut-off.

Members are price series (`series_id`), so a post-insolvency relisting is a different member from its old self.
Membership file: UNIVERSE_DIR/membership.csv (one row per review x member).
"""

import csv
from datetime import date
from pathlib import Path

import pandas as pd

from core.config import UNIVERSE_DIR

MEMBERSHIP_FILE = 'membership.csv'
SIZE = 500
MIN_TRADING_FREQ = 0.90
MIN_PRICE = 10.0
CUTOFF_MONTHS = (1, 7)
EFFECTIVE_MONTH = {1: 4, 7: 10}
WINDOW_MONTHS = 6
FIELDS = ['cutoff_date', 'effective_from', 'rank', 'series_id', 'company_key', 'symbol', 'median_traded_value',
          'trading_freq', 'close']
PANEL_COLUMNS = ['trade_date', 'series_id', 'company_key', 'symbol', 'series', 'close', 'traded_value']


def review_calendar(trading_days: list[date]) -> list[tuple[date, date]]:
    """Return [(cutoff_date, effective_from)] for every review that has a full window and an effective day in data.

    A review needs trading data covering six months before its cut-off, and the first trading day of the effective
    month must exist in `trading_days`.
    """
    days = sorted(set(trading_days))
    if not days:
        return []
    first = days[0]
    out = []
    for year in range(first.year, days[-1].year + 1):
        for m in CUTOFF_MONTHS:
            month_days = [d for d in days if d.year == year and d.month == m]
            if not month_days:
                continue
            cutoff = month_days[-1]
            window_start = _months_before(cutoff, WINDOW_MONTHS)
            if window_start < first:
                continue
            eff_month = EFFECTIVE_MONTH[m]
            eff = next((d for d in days if d.year == year and d.month == eff_month), None)
            if eff is None:
                continue
            out.append((cutoff, eff))
    return out


def _months_before(d: date, months: int) -> date:
    """Return the same calendar day `months` earlier (clamped to the month's last day)."""
    y, m = d.year, d.month - months
    while m < 1:
        m += 12
        y -= 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def build_review(panel: pd.DataFrame, cutoff: date, effective_from: date) -> tuple[pd.DataFrame, dict]:
    """Rank one review from panel rows; rows dated after `cutoff` are ignored (point-in-time).

    `panel` needs PANEL_COLUMNS. Returns (members as a DataFrame with FIELDS, counts dict).
    """
    start = _months_before(cutoff, WINDOW_MONTHS)
    w = panel[(panel['trade_date'] > start) & (panel['trade_date'] <= cutoff)]
    sessions = w['trade_date'].nunique()
    on_cutoff = w[w['trade_date'] == cutoff].set_index('series_id')
    stats = w.groupby('series_id').agg(days=('trade_date', 'nunique'), median_tv=('traded_value', 'median'))
    stats['trading_freq'] = stats['days'] / sessions if sessions else 0.0
    stats = stats.join(on_cutoff[['company_key', 'symbol', 'series', 'close']], how='inner')
    counts = {'cutoff': cutoff, 'sessions': sessions, 'traded_on_cutoff': len(stats)}
    stats = stats[stats['series'] == 'EQ']
    counts['eq_on_cutoff'] = len(stats)
    stats = stats[stats['trading_freq'] >= MIN_TRADING_FREQ]
    counts['freq_ok'] = len(stats)
    stats = stats[stats['close'] >= MIN_PRICE]
    counts['eligible'] = len(stats)
    top = stats.sort_values(['median_tv', 'company_key'], ascending=[False, True]).head(SIZE).reset_index()
    top['rank'] = range(1, len(top) + 1)
    top['cutoff_date'] = cutoff
    top['effective_from'] = effective_from
    top = top.rename(columns={'median_tv': 'median_traded_value'})
    counts['members'] = len(top)
    return top[FIELDS], counts


def write_membership(members: pd.DataFrame, path: Path | None = None) -> Path:
    """Write all reviews' members to membership.csv atomically."""
    path = path or (UNIVERSE_DIR / MEMBERSHIP_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.csv.tmp')
    out = members.sort_values(['cutoff_date', 'rank'])
    out.to_csv(tmp, index=False, columns=FIELDS, float_format='%.2f')
    tmp.replace(path)
    return path


def load_membership(path: Path | None = None) -> pd.DataFrame:
    """Load membership.csv with dates as datetime.date.

    Raises:
        FileNotFoundError: membership not built (run ingestion.build_universe first).
    """
    path = path or (UNIVERSE_DIR / MEMBERSHIP_FILE)
    with path.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    df = pd.DataFrame(rows)
    for col in ('cutoff_date', 'effective_from'):
        df[col] = pd.to_datetime(df[col]).dt.date
    df['rank'] = df['rank'].astype(int)
    for col in ('median_traded_value', 'trading_freq', 'close'):
        df[col] = df[col].astype(float)
    return df


def rebalance_dates(membership: pd.DataFrame) -> list[date]:
    """Return the effective dates of all reviews, ascending."""
    return sorted(membership['effective_from'].unique())


def members_on(membership: pd.DataFrame, on: date) -> pd.DataFrame:
    """Return the members in force on `on` (the latest review with effective_from <= on); empty before the first."""
    eff = [d for d in rebalance_dates(membership) if d <= on]
    if not eff:
        return membership.iloc[0:0]
    return membership[membership['effective_from'] == eff[-1]].reset_index(drop=True)
