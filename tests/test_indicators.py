# -*- coding: utf-8 -*-
"""ST-010 unit tests for core.indicators and the benchmark file parser. No network."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from core import indicators as ind
from ingestion.fetch_benchmark import nse_index_closes


def _series(sid: str, closes: list) -> pd.DataFrame:
    """One series with consecutive dates."""
    d0 = date(2020, 1, 1)
    return pd.DataFrame({'series_id': sid, 'trade_date': [d0 + timedelta(days=i) for i in range(len(closes))],
                         'close': closes})


def test_return_sma_and_window_start():
    """ret_n and sma_n use the series' own rows; NaN until enough history."""
    df = ind.add_indicators(_series('A', [100, 110, 121, 133.1]), ret_n=2, sma_n=3, rsi_n=2)
    assert np.isnan(df['ret_2'].iloc[1]) and df['ret_2'].iloc[2] == pytest.approx(0.21)
    assert np.isnan(df['sma_3'].iloc[1]) and df['sma_3'].iloc[2] == pytest.approx(110.333333, rel=1e-6)


def test_series_do_not_mix():
    """Two series side by side: each window only sees its own closes."""
    df = pd.concat([_series('A', [100, 200, 300]), _series('B', [10, 10, 10])])
    out = ind.add_indicators(df, ret_n=1, sma_n=2, rsi_n=2)
    b = out[out['series_id'] == 'B']
    assert list(b['ret_1'].iloc[1:]) == [0.0, 0.0] and list(b['sma_2'].iloc[1:]) == [10.0, 10.0]


def test_rsi_extremes_and_known_value():
    """Only gains -> 100, only losses -> 0, flat -> 50; matches a hand-computed Wilder value."""
    assert ind.wilder_rsi(pd.Series([1, 2, 3, 4, 5.0]), 2).iloc[-1] == 100.0
    assert ind.wilder_rsi(pd.Series([5, 4, 3, 2, 1.0]), 2).iloc[-1] == pytest.approx(0.0)
    assert ind.wilder_rsi(pd.Series([3, 3, 3, 3.0]), 2).iloc[-1] == 50.0
    # changes +1, -1, +2 with n=2: avg_gain .5 -> .5*.5+2*.5=1.25 ... compute: after 2 changes ag=.5, al=.5;
    # third change +2: ag=.5*.5+2*.5=1.25, al=.5*.5=.25 -> RS=5 -> RSI=83.333
    assert ind.wilder_rsi(pd.Series([10, 11, 10, 12.0]), 2).iloc[-1] == pytest.approx(83.3333, rel=1e-4)


def test_no_lookahead_in_indicators():
    """Changing a later close never changes earlier indicator values."""
    base = _series('A', list(np.linspace(100, 150, 30)))
    changed = base.copy()
    changed.loc[29, 'close'] = 10.0
    a = ind.add_indicators(base, ret_n=5, sma_n=10, rsi_n=5).iloc[:29]
    b = ind.add_indicators(changed, ret_n=5, sma_n=10, rsi_n=5).iloc[:29]
    pd.testing.assert_frame_equal(a, b)


def test_nse_index_file_parser(tmp_path):
    """Reads the Nifty 500 row from ind_close_all files; ignores other indices."""
    (tmp_path / 'ind_close_all_01012025.csv').write_text(
        'Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value\n'
        'Nifty 50,01-01-2025,1,1,1,23742.9\nNifty 500,01-01-2025,1,1,1,22481.8\n', encoding='utf-8')
    assert nse_index_closes(tmp_path) == {date(2025, 1, 1): 22481.8}
