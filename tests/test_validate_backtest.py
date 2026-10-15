# -*- coding: utf-8 -*-
"""ST-010 piece 5: the validator's own rules (independent charges and tax, the lookahead scrambler). No data files."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest import costs
from scripts.validate_backtest import fy_tax_table, order_charges, scrambler


@pytest.mark.parametrize('value', [1000.0, 2555.35, 7999.99, 100000.0])
def test_independent_charges_agree_with_engine(value):
    """Two separate write-ups of Zerodha's rates give the same rupees."""
    assert order_charges('BUY', value, False) == pytest.approx(costs.buy_charges(value)['total'], abs=1e-9)
    assert order_charges('SELL', value, True) == pytest.approx(costs.sell_charges(value, True)['total'], abs=1e-9)
    assert order_charges('SELL', value, False) == pytest.approx(costs.sell_charges(value, False)['total'], abs=1e-9)


def closed(entry, exit_, gain):
    """A closed lot whose taxable gain is `gain` (no charges)."""
    return {'entry_date': entry, 'exit_date': exit_, 'buy_value': 1000.0, 'buy_charges': 0.0, 'buy_stt': 0.0,
            'sell_value': 1000.0 + gain, 'sell_charges': 0.0, 'sell_stt': 0.0}


def test_tax_short_and_long_term_with_set_off():
    """FY2020: short-term loss 300 eats long-term gain 1,000 -> LTCG 700 taxed at 13%."""
    lots = pd.DataFrame([closed(date(2020, 5, 4), date(2020, 9, 1), -300.0),
                         closed(date(2019, 5, 6), date(2020, 6, 1), 1000.0)])
    t = fy_tax_table(lots, [2020]).iloc[0]
    assert t['st_gain'] == pytest.approx(-300) and t['lt_gain'] == pytest.approx(1000)
    assert t['tax'] == pytest.approx(700 * 0.13)


def test_tax_long_term_loss_cannot_reduce_short_term_gain():
    """A long-term loss is carried forward, not set against short-term gains."""
    lots = pd.DataFrame([closed(date(2019, 5, 6), date(2020, 6, 1), -500.0),
                         closed(date(2020, 5, 4), date(2020, 9, 1), 800.0)])
    t = fy_tax_table(lots, [2020]).iloc[0]
    assert t['tax'] == pytest.approx(800 * 0.208) and t['lt_loss_cf'] == pytest.approx(500)


def test_scrambler_changes_only_after_cutoff():
    """The lookahead hook leaves every row up to the cut-off untouched."""
    p = pd.DataFrame({'trade_date': [date(2020, 1, d) for d in (1, 2, 3, 6)], 'open': 10.0, 'high': 11.0,
                      'low': 9.0, 'close': 10.0, 'prev_close': 10.0})
    q = scrambler(date(2020, 1, 2), 1)(p)
    assert q.iloc[:2].equals(p.iloc[:2])
    assert not np.allclose(q.iloc[2:]['close'], 10.0)
