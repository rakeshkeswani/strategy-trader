# -*- coding: utf-8 -*-
"""ST-010 engine tests on small synthetic markets with known answers. No network."""

import copy
from datetime import date, timedelta

import pandas as pd
import pytest

from backtest import costs
from backtest.engine import SLIPPAGE, Backtest

BASE = {'name': 't', 'signal': {'rank_by': 'ret_126', 'top_n': 0, 'weights': 'equal'},
        'sizing': {'weekly_budget': 10000, 'risk_per_trade': 1000, 'min_lot': 1000},
        'exit': {'mode': 'lot_stop', 'initial_stop': 0.08, 'trailing_stop': 0.08, 'time_exit_months': 12}}
LIMITS = {'capital_cap': 100000, 'per_stock': 8000, 'loss_tiers': (0.10, 0.15, 0.20)}


def weekdays(start: date, n: int) -> list[date]:
    """n consecutive Mon-Fri dates from start."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def market(paths: dict, days: list[date], ret=None) -> pd.DataFrame:
    """paths: {sid: [(open, high, low, close), ...]} aligned with days; ret: {sid: value} for the rank column."""
    rows = []
    for sid, bars in paths.items():
        for d, (o, h, l, c) in zip(days, bars):
            rows.append({'trade_date': d, 'series_id': sid, 'symbol': sid, 'open': o, 'high': h, 'low': l, 'close': c,
                         'adj_factor': 1.0, 'ret_126': (ret or {}).get(sid, 0.1), 'ret_252': (ret or {}).get(sid, 0.1)})
    return pd.DataFrame(rows)


def flat(n: int, px: float = 100.0) -> list[tuple]:
    """n bars at a constant price."""
    return [(px, px, px, px)] * n


def run(strategy, mkt, days, limits=LIMITS):
    """Run over the whole synthetic calendar with every series a member."""
    members = set(mkt['series_id'])
    return Backtest(strategy, mkt, lambda d: members, days[0], days[-1], limits).run()


def test_buy_then_initial_stop_at_stop_price():
    """Buy at Monday open; a low touching the 8% stop sells at the stop (minus slippage)."""
    days = weekdays(date(2020, 1, 3), 10)                     # Fri 3 Jan .. Thu 16 Jan
    bars = flat(10)
    bars[5] = (100, 100, 90, 95)                              # Fri 10 Jan low 90 < stop 92.0x
    res = run(BASE, market({'A': bars}, days), days)
    buy = res.orders[res.orders.side == 'BUY'].iloc[0]
    assert buy['date'] == date(2020, 1, 6) and buy['price'] == pytest.approx(100 * (1 + SLIPPAGE))
    assert buy['value'] <= 8000                               # per-stock cap
    sell = res.orders[res.orders.side == 'SELL'].iloc[0]
    assert sell['reason'] == 'stop' and sell['price'] == pytest.approx(100.1 * 0.92 * (1 - SLIPPAGE))


def test_gap_down_sells_at_open():
    """An open below the stop sells at the open, not at the stop."""
    days = weekdays(date(2020, 1, 3), 10)
    bars = flat(10)
    bars[5] = (80, 82, 78, 81)
    res = run(BASE, market({'A': bars}, days), days)
    sell = res.orders[res.orders.side == 'SELL'].iloc[0]
    assert sell['reason'] == 'stop_gap' and sell['price'] == pytest.approx(80 * (1 - SLIPPAGE))


def test_trailing_stop_follows_highest_close():
    """After a close at 120 the stop is 110.4; a low of 110 exits there."""
    days = weekdays(date(2020, 1, 3), 12)
    bars = flat(3) + [(118, 120, 118, 120)] * 3 + [(119, 119, 110, 112)] + flat(5, 112)
    res = run(BASE, market({'A': bars}, days), days)
    sell = res.orders[res.orders.side == 'SELL'].iloc[0]
    assert sell['reason'] == 'stop' and sell['price'] == pytest.approx(120 * 0.92 * (1 - SLIPPAGE))


def test_time_exit_after_more_than_12_months_is_long_term():
    """A lot never stopped out exits on the first trading day after 12 months; its gain is taxed long-term."""
    days = weekdays(date(2020, 1, 3), 290)
    bars = [(100 + i * 0.1,) * 4 for i in range(290)]          # steady rise, never touches a trailing stop
    res = run(BASE, market({'A': bars}, days), days)
    first = res.lots.sort_values('lot_id').iloc[0]
    assert first['entry_date'] == date(2020, 1, 6) and first['exit_reason'] == 'time_12m'
    assert first['exit_date'] == date(2021, 1, 7)               # first weekday after 6 Jan 2021
    assert costs.is_long_term(first['entry_date'], first['exit_date'])


def test_weekly_budget_and_per_stock_cap():
    """Each week buys at most Rs 10,000; one stock never exceeds Rs 8,000 at cost."""
    days = weekdays(date(2020, 1, 3), 30)
    res = run(BASE, market({'A': flat(30), 'B': flat(30), 'C': flat(30)}, days), days)
    buys = res.orders[res.orders.side == 'BUY']
    assert buys.groupby('date')['value'].sum().max() <= 10000
    assert buys.groupby('series_id')['value'].sum().max() <= 8000


def test_capital_cap_and_loss_tier_block_buys():
    """Open cost never exceeds Rs 1,00,000; a 15% loss over the rolling window stops new buys."""
    days = weekdays(date(2020, 1, 3), 120)
    mkt = market({f'S{i}': flat(120) for i in range(30)}, days)
    res = run(BASE, mkt, days)
    assert res.daily['invested_cost'].max() <= 100000 + 1e-6
    crash = market({f'S{i}': flat(40) + [(60, 60, 60, 60)] * 80 for i in range(30)}, days)
    res2 = run(copy.deepcopy(BASE) | {'exit': BASE['exit'] | {'initial_stop': 0.5, 'trailing_stop': 0.5}}, crash, days)
    blocked = res2.daily[res2.daily['tier'].isin(['no_buys', 'halt'])]
    assert not blocked.empty
    first_block = blocked['date'].min()
    later_buys = res2.orders[(res2.orders.side == 'BUY') & (res2.orders.date > first_block + timedelta(days=7))]
    assert later_buys.empty or (res2.daily.set_index('date').loc[later_buys['date'], 'tier'] == 'ok').all()


def test_rakesh_weights_and_average_rules():
    """Top-4 by gain with amounts in proportion; oldest lot sold at a -15% average; one lot a week above +50%."""
    rk = {'name': 'r', 'signal': {'rank_by': 'ret_252', 'top_n': 4, 'weights': 'by_gain'},
          'sizing': {'weekly_budget': 10000, 'min_lot': 0},
          'exit': {'mode': 'stock_average', 'loss_trigger': -0.15, 'profit_trigger': 0.5, 'time_exit_months': 12}}
    days = weekdays(date(2020, 1, 3), 15)
    gains = {'A': 0.9, 'B': 0.6, 'C': 0.3, 'D': 0.2, 'E': 0.1}
    paths = {s: flat(15) for s in gains}
    paths['A'] = flat(5) + [(84, 84, 84, 84)] * 10                     # A falls 16% from Fri 10 Jan
    res = run(rk, market(paths, days, gains), days, limits=None)
    first = res.orders[(res.orders.side == 'BUY') & (res.orders.date == date(2020, 1, 6))]
    assert set(first['series_id']) == {'A', 'B', 'C', 'D'}            # E is fifth
    share = first.set_index('series_id')['value'] / first['value'].sum()
    assert share['A'] == pytest.approx(0.9 / 2.0, abs=0.01)
    loss = res.orders[(res.orders.side == 'SELL') & (res.orders.reason == 'loss_15')]
    assert loss.iloc[0]['date'] == date(2020, 1, 10) and loss.iloc[0]['lot_id'] == first.set_index('series_id').loc['A', 'lot_id']


def test_no_lookahead_and_determinism():
    """Changing prices after a date leaves every earlier order unchanged; two runs are identical."""
    days = weekdays(date(2020, 1, 3), 60)
    base = market({'A': flat(60), 'B': [(100 + i,) * 4 for i in range(60)]}, days)
    r1, r2 = run(BASE, base, days), run(BASE, base, days)
    pd.testing.assert_frame_equal(r1.orders, r2.orders)
    cut = days[40]
    changed = base.copy()
    changed.loc[changed.trade_date > cut, ['open', 'high', 'low', 'close']] = 1.0
    r3 = run(BASE, changed, days)
    early = lambda r: r.orders[r.orders.date <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(early(r1), early(r3))


def test_fy_tax_setoff():
    """Short-term loss offsets long-term gain; carried losses are used next year."""
    tax, st_cf, lt_cf = costs.fy_tax(-1000, 3000, 0, 0)
    assert tax == pytest.approx(2000 * costs.LTCG_RATE) and st_cf == 0
    tax, st_cf, lt_cf = costs.fy_tax(-5000, 1000, 0, 0)
    assert tax == 0 and st_cf == 4000
    tax, st_cf, lt_cf = costs.fy_tax(6000, 0, 4000, 0)
    assert tax == pytest.approx(2000 * costs.STCG_RATE) and st_cf == 0
