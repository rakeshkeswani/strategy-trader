# -*- coding: utf-8 -*-
# core/adjusted.py
"""
ST-010 -- split/bonus-adjusted prices at read time (docs/DATA_MODEL.md: the panel stays raw).

Each corporate action (core.corporate_actions.load_history: symbol in use on ex_date, history.csv + ca_overrides.csv) is
attached to the price SERIES that traded under that symbol on the ex-date (the first panel row on/after the ex-date,
within MATCH_DAYS). A row dated d is then divided by the product of that series' factors with ex_date > d (volume is
multiplied) -- every price is put on the scale of the latest date.

Point-in-time: indicators built from these prices are ratios (returns, moving-average ratios, RSI), which a later split
scales equally at both ends, so back-adjustment adds no lookahead. Anything that needs the actual price level (lot size,
the Rs 10 floor) must use RAW prices.
"""

import numpy as np
import pandas as pd

PRICE_COLS = ['open', 'high', 'low', 'close', 'prev_close']
# An ex-date attaches to the symbol's first panel row on/after it within this many calendar days. 10 missed two real
# actions (RAIREKMOH 2014, VERTOZ 2025 consolidation: next trade > 10 days later); 45 sits above the panel's 30-day
# series-break gap, so the next row of the same symbol is still the same company.
MATCH_DAYS = 45


def actions_frame(table: dict) -> pd.DataFrame:
    """Flatten load_history()'s {symbol: [(ex_date, factor)]} into a DataFrame (symbol, ex_date, factor)."""
    rows = [(s, d, f) for s, lst in table.items() for d, f in lst]
    return pd.DataFrame(rows, columns=['symbol', 'ex_date', 'factor'])


def series_factors(panel: pd.DataFrame, actions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach each action to the series trading its symbol on the ex-date.

    `panel` needs trade_date, series_id, symbol. Returns (matched: series_id, ex_date, factor; unmatched actions).
    """
    if actions.empty:
        return pd.DataFrame(columns=['series_id', 'ex_date', 'factor']), actions
    rows = panel[['symbol', 'trade_date', 'series_id']].drop_duplicates(['symbol', 'trade_date'])
    rows = rows.assign(td=pd.to_datetime(rows['trade_date'])).sort_values('td')
    acts = actions.assign(ed=pd.to_datetime(actions['ex_date'])).sort_values('ed')
    m = pd.merge_asof(acts, rows[['symbol', 'td', 'series_id']], left_on='ed', right_on='td', by='symbol',
                      direction='forward', tolerance=pd.Timedelta(days=MATCH_DAYS))
    matched = m[m['series_id'].notna()][['series_id', 'ex_date', 'factor']]
    matched = matched.groupby(['series_id', 'ex_date'], as_index=False)['factor'].prod()
    return matched.reset_index(drop=True), m[m['series_id'].isna()][['symbol', 'ex_date', 'factor']]


def adjust(panel: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `panel` with PRICE_COLS divided and volume multiplied by each row's cumulative later factor.

    Adds column `adj_factor` (1.0 where no later action).
    """
    out = panel.copy()
    out['adj_factor'] = 1.0
    if factors.empty:
        return out
    td = pd.to_datetime(out['trade_date']).values
    for sid, g in factors.groupby('series_id'):
        idx = np.flatnonzero(out['series_id'].values == sid)
        if not len(idx):
            continue
        ex = pd.to_datetime(g['ex_date']).values
        f = g['factor'].values.astype(float)
        order = np.argsort(ex)
        ex, f = ex[order], f[order]
        # cumulative product of factors strictly after each row's date
        suffix = np.cumprod(f[::-1])[::-1]               # suffix[k] = prod(f[k:])
        pos = np.searchsorted(ex, td[idx], side='right')  # first action with ex_date > d
        cum = np.where(pos < len(ex), suffix[np.minimum(pos, len(ex) - 1)], 1.0)
        out.loc[out.index[idx], 'adj_factor'] = cum
    for c in PRICE_COLS:
        if c in out:
            out[c] = out[c] / out['adj_factor']
    if 'volume' in out:
        out['volume'] = out['volume'] * out['adj_factor']
    return out
