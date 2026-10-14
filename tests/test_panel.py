# -*- coding: utf-8 -*-
"""ST-004 unit tests for core.panel -- series rule, append continuity, Parquet round trip. No network."""

from datetime import date

import pandas as pd

from core import panel


def _rows(spec: list[tuple]) -> pd.DataFrame:
    """Build panel rows (no series_id) from (date, key, symbol, isin, close)."""
    out = []
    for d, key, sym, isin, close in spec:
        out.append({'trade_date': d, 'company_key': key, 'symbol': sym, 'isin': isin, 'series': 'EQ',
                    'open': close, 'high': close, 'low': close, 'close': close, 'prev_close': close,
                    'volume': 100, 'traded_value': close * 100})
    return pd.DataFrame(out)


def test_gap_with_isin_change_starts_new_series():
    """Post-insolvency relisting: > 30 days without a close AND a new ISIN -> a new series."""
    df = panel.assign_series(_rows([
        (date(2019, 1, 1), 'WAAREEINDO', 'INDOSOLAR', 'INE866K01015', 1.0),
        (date(2019, 1, 2), 'WAAREEINDO', 'INDOSOLAR', 'INE866K01015', 1.1),
        (date(2025, 3, 3), 'WAAREEINDO', 'WAAREEINDO', 'INE866K01023', 180.0),
    ]))
    assert list(df['series_id']) == ['WAAREEINDO@2019-01-01'] * 2 + ['WAAREEINDO@2025-03-03']


def test_gap_alone_or_isin_change_alone_keeps_series():
    """A suspension (gap, same ISIN) or a split (new ISIN, no gap) is the same series."""
    df = panel.assign_series(_rows([
        (date(2020, 1, 1), 'AAA', 'AAA', 'INE1', 10.0),
        (date(2020, 6, 1), 'AAA', 'AAA', 'INE1', 9.0),     # 5-month suspension, same ISIN
        (date(2020, 6, 2), 'AAA', 'AAA', 'INE2', 1.8),     # split: ISIN changes next day
    ]))
    assert df['series_id'].nunique() == 1 and df['series_id'].iloc[0] == 'AAA@2020-01-01'


def test_rename_keeps_one_key_and_series():
    """TIDEWATER -> VEEDOL is one company key and one series (key comes from core.securities)."""
    df = panel.assign_series(_rows([
        (date(2024, 10, 8), 'VEEDOL', 'TIDEWATER', 'INE484C01030', 1900.0),
        (date(2024, 10, 9), 'VEEDOL', 'VEEDOL', 'INE484C01030', 1910.0),
    ]))
    assert set(df['series_id']) == {'VEEDOL@2024-10-08'} and list(df['symbol']) == ['TIDEWATER', 'VEEDOL']


def test_append_continues_existing_series():
    """An incremental append keeps each company's current series_id from the context row."""
    ctx = pd.DataFrame([{'company_key': 'AAA', 'trade_date': date(2026, 10, 9), 'isin': 'INE1',
                         'series_id': 'AAA@2014-01-02'}])
    df = panel.assign_series(_rows([(date(2026, 10, 12), 'AAA', 'AAA', 'INE1', 10.0),
                                    (date(2026, 10, 12), 'NEWCO', 'NEWCO', 'INE9', 50.0)]), ctx)
    assert dict(zip(df['company_key'], df['series_id'])) == {'AAA': 'AAA@2014-01-02', 'NEWCO': 'NEWCO@2026-10-12'}


def test_parquet_round_trip(tmp_path):
    """write_year then read_panel returns the same rows, dates as datetime.date, filtered by date."""
    df = panel.assign_series(_rows([(date(2021, 1, 4), 'AAA', 'AAA', 'INE1', 10.0),
                                    (date(2021, 1, 5), 'AAA', 'AAA', 'INE1', 11.0)]))
    panel.write_year(df, 2021, tmp_path)
    back = panel.read_panel(date(2021, 1, 5), date(2021, 1, 5), root=tmp_path)
    assert len(back) == 1 and back['close'].iloc[0] == 11.0 and back['trade_date'].iloc[0] == date(2021, 1, 5)
    assert list(panel.last_rows(tmp_path)['trade_date']) == [date(2021, 1, 5)]
