# -*- coding: utf-8 -*-
"""ST-019: demerger factors (core.demergers) and their price-only adjustment (core.adjusted). No data files."""

import json
from datetime import date

import pandas as pd
import pytest

from core.adjusted import adjust, series_factors
from core.demergers import candidates, feed_records, load_demergers, merge_reviewed


def panel_rows(symbol, rows):
    """RAW panel rows: (date, open, close)."""
    return pd.DataFrame([{'trade_date': d, 'symbol': symbol, 'series_id': f'{symbol}@2014-01-01', 'open': o, 'high': max(o, c),
                          'low': min(o, c), 'close': c, 'prev_close': c, 'volume': 1000} for d, o, c in rows])


def test_feed_records_keeps_demerger_types_eq_only(tmp_path):
    recs = [{'symbol': 'MIRZAINT', 'series': 'EQ', 'exDate': '29-Mar-2023', 'subject': 'Demerger'},
            {'symbol': 'ABC', 'series': 'EQ', 'exDate': '01-Jun-2020', 'subject': 'Scheme Of Arrangement'},
            {'symbol': 'XYZ', 'series': 'EQ', 'exDate': '01-Jun-2020', 'subject': 'Bonus 1:1'},
            {'symbol': 'DEF', 'series': 'BE', 'exDate': '01-Jun-2020', 'subject': 'Demerger'},
            {'symbol': 'GHI', 'series': 'EQ', 'exDate': '-', 'subject': 'Demerger'}]
    (tmp_path / '2023.json').write_text(json.dumps(recs), encoding='utf-8')
    d = feed_records(tmp_path)
    assert d['symbol'].tolist() == ['ABC', 'MIRZAINT']


def test_factor_from_ex_day_close_falls_only():
    """Mirza: 252.85 -> close 34.65 = applied, factor 7.297; a rise or a small fall is not applied."""
    p = pd.concat([panel_rows('MIRZAINT', [(date(2023, 3, 28), 260.0, 252.85), (date(2023, 3, 29), 33.05, 34.65),
                                           (date(2023, 3, 31), 34.7, 34.85), (date(2023, 4, 3), 34.0, 33.10)]),
                   panel_rows('UP', [(date(2020, 6, 1), 100.0, 100.0), (date(2020, 6, 2), 120.0, 120.0)]),
                   panel_rows('SMALL', [(date(2020, 6, 1), 100.0, 100.0), (date(2020, 6, 2), 97.0, 97.0)])])
    recs = pd.DataFrame([('MIRZAINT', date(2023, 3, 29), 'Demerger'), ('UP', date(2020, 6, 2), 'Scheme Of Arrangement'),
                         ('SMALL', date(2020, 6, 2), 'Demerger'), ('NONE', date(2020, 6, 2), 'Demerger')],
                        columns=['symbol', 'ex_date', 'subject'])
    c = candidates(recs, p).set_index('symbol')
    assert c.loc['MIRZAINT', 'applied'] == 'Y' and c.loc['MIRZAINT', 'factor'] == pytest.approx(252.85 / 34.65, rel=1e-5)
    assert c.loc['MIRZAINT', 'next1_close'] == 34.85 and c.loc['MIRZAINT', 'next2_close'] == 33.10
    assert c.loc['UP', 'applied'] == 'N' and c.loc['UP', 'note'].startswith('price rose')
    assert c.loc['SMALL', 'applied'] == 'N' and 'within' in c.loc['SMALL', 'note']
    assert c.loc['NONE', 'applied'] == 'N' and 'no EQ trade' in c.loc['NONE', 'note']


def test_rebuild_keeps_reviewed_rows_only():
    fresh = pd.DataFrame([{'symbol': 'A', 'ex_date': date(2020, 1, 6), 'applied': 'Y', 'note': ''},
                          {'symbol': 'B', 'ex_date': date(2020, 1, 6), 'applied': 'Y', 'note': ''}])
    existing = pd.DataFrame([{'symbol': 'A', 'ex_date': '2020-01-06', 'applied': 'N', 'note': 'REVIEWED: not a spin-off'},
                             {'symbol': 'B', 'ex_date': '2020-01-06', 'applied': 'N', 'note': 'fall within 5%'}])
    m = merge_reviewed(fresh, existing).set_index('symbol')
    assert m.loc['A', 'applied'] == 'N' and m.loc['A', 'note'].startswith('REVIEWED')
    assert m.loc['B', 'applied'] == 'Y'


def test_load_demergers_applied_rows_only(tmp_path):
    f = tmp_path / 'demergers.csv'
    pd.DataFrame([{'symbol': 'A', 'ex_date': '2020-01-06', 'factor': 2.0, 'applied': 'Y'},
                  {'symbol': 'B', 'ex_date': '2020-01-06', 'factor': 1.03, 'applied': 'N'}]).to_csv(f, index=False)
    d = load_demergers(f)
    assert d['symbol'].tolist() == ['A'] and d['kind'].tolist() == ['demerger'] and d['ex_date'].iloc[0] == date(2020, 1, 6)
    assert load_demergers(tmp_path / 'absent.csv').empty


def test_demerger_adjusts_prices_not_volume_and_removes_the_gap():
    """A held lot keeps its value across the ex-date; a split in the same series still scales volume."""
    p = panel_rows('MIRZAINT', [(date(2023, 3, 27), 255.0, 250.0), (date(2023, 3, 28), 251.0, 252.85),
                                (date(2023, 3, 29), 33.05, 34.65)])
    acts = pd.DataFrame([{'symbol': 'MIRZAINT', 'ex_date': date(2023, 3, 29), 'factor': 252.85 / 34.65, 'kind': 'demerger'},
                         {'symbol': 'MIRZAINT', 'ex_date': date(2023, 3, 28), 'factor': 2.0, 'kind': 'split'}])
    f, unmatched = series_factors(p, acts)
    assert unmatched.empty
    a = adjust(p, f).set_index('trade_date')
    assert a.loc[date(2023, 3, 29), 'close'] / a.loc[date(2023, 3, 28), 'close'] - 1 == pytest.approx(0, abs=1e-9)
    assert a.loc[date(2023, 3, 28), 'volume'] == 1000            # the demerger does not scale volume
    assert a.loc[date(2023, 3, 27), 'volume'] == 2000            # the split before it still does
