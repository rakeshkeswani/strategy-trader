# -*- coding: utf-8 -*-
"""ST-010 piece 4: report card numbers on small made-up runs. No data files."""

import numpy as np
import pandas as pd
import pytest

from backtest.report_card import bootstrap_lead, fy_table, rolling_ahead, rs, underwater


def test_indian_rupee_grouping():
    assert rs(119928.4) == 'Rs 1,19,928'
    assert rs(-16924) == '-Rs 16,924'
    assert rs(12345678) == 'Rs 1,23,45,678'
    assert rs(999) == 'Rs 999'


def days(start, end):
    """Weekdays as trading days."""
    return pd.bdate_range(start, end)


def test_financial_years_split_in_april_and_add_tax_back_to_the_gain():
    """Rs 1 L -> 1.10 L by 31 Mar 2020 (part year), tax Rs 2,000 paid that day; -> 1.21 L by Mar 2021."""
    d = days('2019-10-01', '2021-03-31')
    eq = np.where(d <= '2020-03-31', 110000.0, 121000.0)
    eq[0] = 100000.0
    daily = pd.DataFrame({'date': d, 'equity': eq, 'bench_value': 100000.0})
    tax = pd.DataFrame({'date': [pd.Timestamp('2020-03-31')], 'tax': [2000.0]})
    orders = pd.DataFrame({'date': [pd.Timestamp('2019-10-01')], 'ch_total': [5.0]})
    lots = pd.DataFrame({'entry_date': [pd.Timestamp('2019-10-01')], 'exit_date': [pd.Timestamp('2020-05-04')]})
    t = fy_table(daily, orders, tax, lots)
    assert t['label'].tolist() == ['FY19-20 (part)', 'FY20-21']
    assert t['ret'].tolist() == pytest.approx([0.10, 0.10])
    assert t['gain_rs'].tolist() == pytest.approx([12000, 11000])
    assert t['bought'].tolist() == [1, 0] and t['sold'].tolist() == [0, 1]


def test_rolling_ahead_counts_only_full_year_windows():
    d = days('2019-01-01', '2020-12-31')
    daily = pd.DataFrame({'date': d, 'equity': np.linspace(100, 200, len(d)), 'bench_value': 100.0})
    share, n = rolling_ahead(daily)
    assert share == 1.0 and 250 < n < 270


def test_bootstrap_of_identical_paths_has_zero_lead():
    d = days('2015-01-01', '2020-12-31')
    v = 100000 * np.cumprod(1 + np.random.default_rng(1).normal(0.0004, 0.01, len(d)))
    b = bootstrap_lead(pd.DataFrame({'date': d, 'equity': v, 'bench_value': v}), n=500)
    assert b['p5'] == pytest.approx(0, abs=1e-12) and b['p95'] == pytest.approx(0, abs=1e-12)


def test_bootstrap_clearly_ahead():
    """2% a month vs flat: the whole range is above zero."""
    d = days('2015-01-01', '2020-12-31')
    v = 100000 * 1.02 ** (np.arange(len(d)) / 21)
    b = bootstrap_lead(pd.DataFrame({'date': d, 'equity': v, 'bench_value': 100000.0}), n=500)
    assert b['p5'] > 0.2 and b['share_ahead'] == 1.0


def test_longest_below_a_peak():
    dates = pd.Series(pd.to_datetime(['2020-01-01', '2020-02-01', '2020-08-01', '2020-09-01', '2021-01-01']))
    months, peak, back = underwater(pd.Series([100.0, 120.0, 90.0, 121.0, 110.0]), dates)
    assert (peak, back) == ('2020-02-01', '2020-09-01') and months == pytest.approx(7.0, abs=0.1)
