# -*- coding: utf-8 -*-
# core/indicators.py
"""
ST-010 -- price indicators per price series, computed on split/bonus-adjusted closes (core/adjusted.py).

All windows count the series' own trading rows (a suspended stock's window spans its suspension). Every value at row t
uses only rows up to t (no lookahead). Indicators are ratios, so back-adjustment cannot leak a later split into them.

  ret_<n>   close_t / close_{t-n} - 1          (ret_126 = ~6-month return)
  sma_<n>   simple average of the last n closes (sma_200 = 200-day average)
  rsi_<n>   Wilder's RSI over n rows (rsi_14), 0..100
"""

import numpy as np
import pandas as pd


def _by_series(df: pd.DataFrame) -> pd.core.groupby.SeriesGroupBy:
    """Group adjusted closes by series in trade_date order (df must already be sorted that way)."""
    return df.groupby('series_id', sort=False)['close']


def add_indicators(df: pd.DataFrame, ret_n: int = 126, sma_n: int = 200, rsi_n: int = 14) -> pd.DataFrame:
    """Return `df` (needs series_id, trade_date, adjusted close) sorted by series/date with indicator columns added.

    Rows without enough history get NaN for that indicator.
    """
    out = df.sort_values(['series_id', 'trade_date'], kind='stable').reset_index(drop=True)
    g = _by_series(out)
    out[f'ret_{ret_n}'] = out['close'] / g.shift(ret_n) - 1
    out[f'sma_{sma_n}'] = g.transform(lambda s: s.rolling(sma_n, min_periods=sma_n).mean())
    out[f'rsi_{rsi_n}'] = g.transform(lambda s: wilder_rsi(s, rsi_n))
    return out


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI: average gain / average loss smoothed with alpha = 1/n; NaN until n changes exist.

    RSI = 100 when there are no losses in the window, 0 when there are no gains.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return rsi.where(avg_gain.notna())
