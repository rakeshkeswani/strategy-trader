# -*- coding: utf-8 -*-
"""ST-010 headline measures in backtest/run.py (Test 1 at cost, 12-month return, actions window). No data files."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backtest.run import actions_in_window, headline, lot_pnl, pnl_at_cost, worst_12m_return

DAY = date(2020, 10, 1)


def lot(entry, exit_=None, buy=8000.0, sell=None, bc=0.0, sc=0.0, sid='X', qty=1.0):
    """One lots.csv row."""
    return {'series_id': sid, 'entry_date': entry, 'exit_date': exit_, 'qty': qty, 'buy_value': buy,
            'buy_charges': bc, 'sell_value': np.nan if sell is None else sell, 'sell_charges': np.nan if sell is None else sc}


def one_day(holdings, invested_cost, d=DAY):
    """daily.csv with a single row."""
    return pd.DataFrame([{'date': d, 'holdings': holdings, 'invested_cost': invested_cost}])


def test_level_b_open_lots_only():
    """Rakesh's table 2026-10-15: lots paid 8,000 / 8,000 / 4,000 worth 19,400 today -> -600 / 20,000 = -3.0%."""
    lots = pd.DataFrame([lot(date(2020, 3, 2)), lot(date(2020, 5, 4)), lot(date(2020, 7, 6), buy=4000.0)])
    r = pnl_at_cost(one_day(19400.0, 20000.0), lots).iloc[0]
    assert r['pnl'] == pytest.approx(-600) and r['bought'] == 20000


def test_level_b_counts_lots_sold_in_the_last_12_months():
    """Same open lots + 5 lots stopped out this year at -700 each -> Rs -4,100."""
    rows = [lot(date(2020, 3, 2)), lot(date(2020, 5, 4)), lot(date(2020, 7, 6), buy=4000.0)]
    rows += [lot(date(2019, 11, 4), date(2020, 1, 6 + i), sell=7300.0) for i in range(5)]
    r = pnl_at_cost(one_day(19400.0, 20000.0), pd.DataFrame(rows)).iloc[0]
    assert r['pnl'] == pytest.approx(-4100) and r['bought'] == 60000


def test_window_drops_lots_sold_more_than_12_months_ago_since_start_keeps_them():
    """A lot sold 400 days earlier is outside the rolling window but inside 'since start'."""
    lots = pd.DataFrame([lot(date(2020, 6, 1)), lot(date(2019, 1, 7), date(2019, 8, 28), sell=4000.0)])
    daily = one_day(8800.0, 8000.0)
    assert pnl_at_cost(daily, lots, 365).iloc[0]['pnl'] == pytest.approx(800)
    assert pnl_at_cost(daily, lots, None).iloc[0]['pnl'] == pytest.approx(800 - 4000)


def test_a_lot_sold_today_counts_as_sold_not_open():
    """Sold on the day itself: in the window at its sale value, not in the day's holdings."""
    lots = pd.DataFrame([lot(date(2020, 9, 1), DAY, sell=7000.0)])
    r = pnl_at_cost(one_day(0.0, 0.0), lots).iloc[0]
    assert r['pnl'] == pytest.approx(-1000) and r['bought'] == 8000


def test_charges_are_part_of_the_loss():
    """Buy and sell charges count: a lot bought and sold at the same price still loses its charges."""
    lots = pd.DataFrame([lot(date(2020, 9, 1), date(2020, 9, 15), sell=8000.0, bc=15.0, sc=25.0)])
    assert pnl_at_cost(one_day(0.0, 0.0), lots).iloc[0]['pnl'] == pytest.approx(-40)


def test_mismatch_with_engine_cost_is_an_error():
    """If lots.csv and the engine disagree on what is open, refuse rather than report a wrong number."""
    lots = pd.DataFrame([lot(date(2020, 3, 2))])
    with pytest.raises(ValueError):
        pnl_at_cost(one_day(8000.0, 16000.0), lots)


def test_nothing_invested_is_zero():
    """A day before the first lot: no gain, no loss."""
    lots = pd.DataFrame([lot(date(2020, 11, 2))])
    assert pnl_at_cost(one_day(0.0, 0.0), lots).iloc[0]['pnl'] == 0


def test_test1_divides_by_the_stake_not_by_money_reused():
    """Churn: 10 lots of 8,000 bought and stopped out one after another lose 700 each = Rs -7,000. Test 1 is
    -7,000 / Rs 1 L stake = -7%, not -7,000 / 80,000 'bought' = -8.75% (and with more churn ever smaller)."""
    days = [date(2020, 1, 6), DAY]
    wk = [date(2020, 1, 6) + timedelta(days=7 * i) for i in range(11)]
    lots = pd.DataFrame([lot(wk[i], wk[i + 1], sell=7300.0) for i in range(10)])  # one lot at a time, reused
    daily = pd.DataFrame({'date': days, 'holdings': [8000.0, 0.0], 'invested_cost': [8000.0, 0.0],
                          'equity': [100000.0, 93000.0], 'bench_value': [100000.0, 100000.0],
                          'tax_paid': [0.0, 0.0], 'charges_paid': [0.0, 0.0]})
    m = headline(daily, 100000.0, lots, {})
    assert m['worst_12m_pnl_rupees'] == pytest.approx(-7000) and m['worst_12m_of_stake'] == pytest.approx(-0.07)
    assert m['loss_first_pass'] is True


def test_level_a_per_lot():
    """Closed lot at its sale after charges; open lot at the last close."""
    lots = pd.DataFrame([lot(date(2020, 1, 6), date(2020, 2, 3), sell=6800.0, bc=10.0, sc=10.0),
                         lot(date(2020, 3, 2), sid='Y', qty=100.0)])
    l = lot_pnl(lots, {'Y': 90.0})
    assert l['pnl_pct'].tolist() == pytest.approx([-1220 / 8000, 1000 / 8000])


def test_worst_12m_return_on_a_grown_account():
    """Rs 7 L -> Rs 6 L a year later is -14%, not -100% of the Rs 1 L start."""
    dates = pd.Series(pd.to_datetime(['2018-10-01', '2019-10-01', '2020-10-01']))
    r, end = worst_12m_return(pd.Series([100000.0, 700000.0, 600000.0]), dates, 100000.0)
    assert r == pytest.approx(-1 / 7, abs=1e-4) and end == '2020-10-01'


def test_actions_outside_the_loaded_window_are_skipped_not_unmatched():
    """A 2024 split cannot match 2014-2023 prices; it is counted as outside the window, not as a gap."""
    acts = pd.DataFrame([('A', date(2013, 1, 7), 2.0), ('B', date(2016, 5, 2), 5.0), ('C', date(2024, 3, 4), 2.0)],
                        columns=['symbol', 'ex_date', 'factor'])
    inside, outside = actions_in_window(acts, date(2013, 8, 7), date(2023, 12, 31))
    assert inside['symbol'].tolist() == ['B'] and outside == 2
