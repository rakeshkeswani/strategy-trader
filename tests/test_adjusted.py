# -*- coding: utf-8 -*-
"""ST-010 unit tests for core.adjusted -- factors attach to the right series and scale prices correctly."""

from datetime import date

import pandas as pd
import pytest

from core import adjusted as adj


def _panel(rows):
    """rows: (date, series_id, symbol, close)."""
    return pd.DataFrame([{'trade_date': d, 'series_id': s, 'symbol': sym, 'open': c, 'high': c, 'low': c,
                          'close': c, 'prev_close': c, 'volume': 100} for d, s, sym, c in rows])


def test_split_scales_earlier_rows_only():
    """A 1:5 split on 2020-01-03: rows before are divided by 5, volume multiplied; the ex-day and after unchanged."""
    p = _panel([(date(2020, 1, 1), 'X@2014', 'X', 500.0), (date(2020, 1, 2), 'X@2014', 'X', 510.0),
                (date(2020, 1, 3), 'X@2014', 'X', 102.0)])
    f, unmatched = adj.series_factors(p, pd.DataFrame([('X', date(2020, 1, 3), 5.0)],
                                                      columns=['symbol', 'ex_date', 'factor']))
    out = adj.adjust(p, f)
    assert list(out['close']) == [100.0, 102.0, 102.0] and list(out['volume']) == [500, 500, 100]
    assert unmatched.empty


def test_two_actions_multiply_and_holiday_ex_date():
    """Bonus 1:1 then split 2:1; an ex-date on a holiday attaches to the next trading row."""
    p = _panel([(date(2020, 1, 1), 'Y@2014', 'Y', 400.0), (date(2020, 1, 6), 'Y@2014', 'Y', 200.0),
                (date(2020, 2, 3), 'Y@2014', 'Y', 100.0)])
    acts = pd.DataFrame([('Y', date(2020, 1, 4), 2.0), ('Y', date(2020, 2, 3), 2.0)],
                        columns=['symbol', 'ex_date', 'factor'])
    out = adj.adjust(p, adj.series_factors(p, acts)[0])
    assert list(out['close']) == [100.0, 100.0, 100.0]
    assert list(out['adj_factor']) == [4.0, 2.0, 1.0]


def test_action_follows_symbol_in_use_not_today_key():
    """INFIBEAM's 2021 bonus is stored under INFIBEAM (symbol on ex-date) and lands on the CCAVENUE series."""
    p = _panel([(date(2021, 3, 17), 'CCAVENUE@2014', 'INFIBEAM', 200.0),
                (date(2021, 3, 18), 'CCAVENUE@2014', 'INFIBEAM', 100.0),
                (date(2026, 2, 3), 'CCAVENUE@2014', 'CCAVENUE', 50.0)])
    acts = pd.DataFrame([('INFIBEAM', date(2021, 3, 18), 2.0)], columns=['symbol', 'ex_date', 'factor'])
    f, _ = adj.series_factors(p, acts)
    assert list(f['series_id']) == ['CCAVENUE@2014']
    assert adj.adjust(p, f)['close'].iloc[0] == 100.0


def test_unmatched_action_is_reported():
    """An action for a symbol with no rows near its ex-date is returned as unmatched, not silently dropped."""
    p = _panel([(date(2020, 1, 1), 'Z@2014', 'Z', 10.0)])
    acts = pd.DataFrame([('NOPE', date(2020, 1, 1), 2.0), ('Z', date(2020, 6, 1), 2.0)],
                        columns=['symbol', 'ex_date', 'factor'])
    f, unmatched = adj.series_factors(p, acts)
    assert f.empty and len(unmatched) == 2


def test_ratios_unchanged_by_later_split():
    """A 6-month return computed before a split equals the one computed on adjusted prices (no lookahead in ratios)."""
    p = _panel([(date(2020, 1, 1), 'R@2014', 'R', 100.0), (date(2020, 7, 1), 'R@2014', 'R', 130.0),
                (date(2021, 1, 4), 'R@2014', 'R', 30.0)])
    out = adj.adjust(p, adj.series_factors(p, pd.DataFrame([('R', date(2021, 1, 4), 5.0)],
                                                           columns=['symbol', 'ex_date', 'factor']))[0])
    assert out['close'].iloc[1] / out['close'].iloc[0] == pytest.approx(1.30)
