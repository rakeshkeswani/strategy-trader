# -*- coding: utf-8 -*-
"""ST-004 unit tests for core.universe -- calendar, eligibility, ranking, point-in-time, members_on. No network."""

from datetime import date, timedelta

import pandas as pd

from core import universe as u


def _weekdays(start: date, end: date) -> list[date]:
    """Mon-Fri dates in [start, end] (a stand-in trading calendar)."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _weekdays(date(2019, 1, 1), date(2020, 12, 31))


def _panel(stocks: dict) -> pd.DataFrame:
    """stocks: {key: (traded_value, close, series, skip_every_n_days or 0)} -> panel rows on DAYS."""
    rows = []
    for key, (tv, close, series, skip) in stocks.items():
        for i, d in enumerate(DAYS):
            if skip and i % skip == 0:
                continue
            rows.append({'trade_date': d, 'series_id': f'{key}@2019-01-01', 'company_key': key, 'symbol': key,
                         'series': series, 'close': close, 'traded_value': tv})
    return pd.DataFrame(rows)


def test_calendar_cutoffs_and_effective_dates():
    """Cut-offs are the last trading days of Jan/Jul; effective the first of Apr/Oct; first review needs 6 months."""
    cal = u.review_calendar(DAYS)
    assert cal[0] == (date(2019, 7, 31), date(2019, 10, 1))      # Jan 2019 lacks six months of data
    assert cal[1] == (date(2020, 1, 31), date(2020, 4, 1))
    assert cal[-1] == (date(2020, 7, 31), date(2020, 10, 1))


def test_eligibility_filters_and_ranking(monkeypatch):
    """BE series, < 90% trading days and price < Rs 10 are excluded; the rest rank by median traded value."""
    monkeypatch.setattr(u, 'SIZE', 2)
    p = _panel({'BIG': (9e8, 500, 'EQ', 0), 'MID': (5e8, 300, 'EQ', 0), 'SMALL': (1e8, 200, 'EQ', 0),
                'TTOT': (9.9e8, 400, 'BE', 0), 'GAPPY': (9.8e8, 400, 'EQ', 5), 'PENNY': (9.7e8, 8, 'EQ', 0)})
    members, c = u.build_review(p, date(2020, 1, 31), date(2020, 4, 1))
    assert list(members['company_key']) == ['BIG', 'MID']
    assert (c['eq_on_cutoff'], c['freq_ok'], c['eligible'], c['members']) == (5, 4, 3, 2)


def test_rows_after_cutoff_are_ignored():
    """Point-in-time: adding a huge traded value AFTER the cut-off changes nothing."""
    p = _panel({'AAA': (5e8, 100, 'EQ', 0), 'BBB': (4e8, 100, 'EQ', 0)})
    before, _ = u.build_review(p, date(2020, 1, 31), date(2020, 4, 1))
    late = pd.DataFrame([{'trade_date': date(2020, 2, 3), 'series_id': 'BBB@2019-01-01', 'company_key': 'BBB',
                          'symbol': 'BBB', 'series': 'EQ', 'close': 100, 'traded_value': 1e15}])
    after, _ = u.build_review(pd.concat([p, late]), date(2020, 1, 31), date(2020, 4, 1))
    assert before.equals(after)


def test_members_on_follows_effective_dates(tmp_path):
    """Before the first effective day: none; between reviews: the earlier one; round trip through the CSV."""
    p = _panel({'AAA': (5e8, 100, 'EQ', 0)})
    reviews = [u.build_review(p, c, e)[0] for c, e in u.review_calendar(DAYS)]
    path = u.write_membership(pd.concat(reviews), tmp_path / 'membership.csv')
    m = u.load_membership(path)
    assert u.members_on(m, date(2019, 9, 30)).empty
    assert set(u.members_on(m, date(2020, 3, 31))['cutoff_date']) == {date(2019, 7, 31)}
    assert set(u.members_on(m, date(2020, 4, 1))['cutoff_date']) == {date(2020, 1, 31)}
    assert u.rebalance_dates(m) == [date(2019, 10, 1), date(2020, 4, 1), date(2020, 10, 1)]
