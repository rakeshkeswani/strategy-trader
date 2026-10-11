# -*- coding: utf-8 -*-
"""ST-003 unit tests -- no network. Fixtures are real NSE feed records saved 2026-10-11."""

import json
from datetime import date
from pathlib import Path

import pytest

from core import corporate_actions as ca

FIXTURES = Path(__file__).parent / 'fixtures'
AS_OF = date(2026, 10, 11)


def _load(name: str) -> list:
    """Load a fixture JSON list."""
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def _actions(subject: str) -> dict:
    """Parse a subject and return {action_type: factor}."""
    return {t: round(f, 6) for t, f in ca.parse_subject(subject).actions}


@pytest.mark.parametrize('subject, expected', [
    ('Bonus 1:1', {'BONUS': 2.0}),
    ('Bonus 1 : 1', {'BONUS': 2.0}),
    ('Bonus Issue 1 : 1', {'BONUS': 2.0}),
    ('Bonus- 1:1', {'BONUS': 2.0}),
    (' Bonus 1:4', {'BONUS': 1.25}),
    (' Bonus 25:202', {'BONUS': round(227 / 202, 6)}),
    ('Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share', {'SPLIT': 5.0}),
    ('Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share', {'SPLIT': 2.0}),
    ('Face Value Split From Rs.10/- To Rs.2/-', {'SPLIT': 5.0}),
    ('Face Value Split Rs.10/- To Re.1/- Per Share', {'SPLIT': 10.0}),
    ('Sub-Division From Rs 10/- Per Share To Rs 2/- Per Share', {'SPLIT': 5.0}),
    (' Face Value Split (Sub-Division) - From Rs 10 /- Per Share To Rs 2/- Per Share', {'SPLIT': 5.0}),
    ('Face Value Split From Rs 10/- Each To Rs 2/- Each', {'SPLIT': 5.0}),
    ('Annual General Meeting And Face Value Split From Rs.10/- To Re.1/-', {'SPLIT': 10.0}),
    ('Bonus 1:1 / Face Value Split From 10/- To Face Value 2/-', {'BONUS': 2.0, 'SPLIT': 5.0}),
    ('Bonus 1:1 / Face Value Split From Rs.10/- To Rs.5/-', {'BONUS': 2.0, 'SPLIT': 2.0}),
    ('Bonus 1:1 And Face Value Split Rs.10/- To Rs.5/- Per Share', {'BONUS': 2.0, 'SPLIT': 2.0}),
    (' Bonus 1:2/Face Value Split (Sub-Division) From Rs 2/- Per Share To Re 1/- Per Share',
     {'BONUS': 1.5, 'SPLIT': 2.0}),
    ('Dividend Rs 2.50/- Per Share / Bonus 1 : 4', {'BONUS': 1.25}),
    ('Annual General Meeting / Final Dividend - Rs 7/- Per Share / Bonus 1 : 1', {'BONUS': 2.0}),
    (' Bonus 1:1/Dividend- Rs 7 Per Share', {'BONUS': 2.0}),
    ('Consolidation Of Shares From Rs 1/- To Rs 10/-', {'CONSOLIDATION': 0.1}),
    ('Dividend - Rs 1.50 Per Share', {}),
])
def test_parse_subject_shapes(subject, expected):
    """Real 2014-2026 subject shapes give the right factors; combined subjects give every action."""
    p = ca.parse_subject(subject)
    assert _actions(subject) == expected
    assert not p.unclassified and not p.review and not p.excluded


@pytest.mark.parametrize('subject, bucket', [
    ('Scheme Of Arrangement - Bonus Ncrps 3:1', 'excluded'),
    ('Bonus Preference Shares 21:1', 'excluded'),
    ('Scheme Of Arrangement - Issue Of Bonus Debentures', 'excluded'),
    (' Capital Reduction Rs 10 To Rs 3.30 / Consolidation Rs 3.30 To Rs.10', 'review'),
    ('Bonus Shares To Be Announced', 'unclassified'),
    ('Face Value Split Of Shares', 'unclassified'),
])
def test_traps_are_never_adjusted(subject, bucket):
    """Not-equity bonuses, capital reductions and unparseable shapes produce no factor, each in its bucket."""
    p = ca.parse_subject(subject)
    assert p.actions == []
    assert len(getattr(p, bucket)) == 1


def test_myinvestiq_fixture_regression():
    """On MyInvestIQ's 2025-26 records we match its verified counts exactly: 47 bonus, 53 split, 2 NCRPS."""
    rows, issues, counts = ca.classify_records(_load('ca_myinvestiq_2025_2026_subset.json'), AS_OF)
    assert (counts['BONUS'], counts['SPLIT'], counts['excluded']) == (47, 53, 2)
    assert counts['unclassified'] == 0 and counts['review'] == 0


def test_history_fixture_has_no_unclassified():
    """Every bonus/split-shaped 2014 and 2018 subject is parsed, excluded or sent to review -- none slips through."""
    rows, issues, counts = ca.classify_records(_load('ca_history_shapes_2014_2018.json'), AS_OF)
    assert counts['unclassified'] == 0, [i for i in issues if i[0] == 'unclassified']
    assert counts['review'] == 1 and counts['excluded'] == 2
    assert counts['BONUS'] + counts['SPLIT'] >= 95


def test_actions_on_or_after_as_of_are_deferred():
    """Publication timing is unknown, so ex_date >= as_of is never stored."""
    recs = [{'symbol': 'AAA', 'series': 'EQ', 'exDate': '10-Oct-2026', 'subject': 'Bonus 1:1', 'isin': ''},
            {'symbol': 'BBB', 'series': 'EQ', 'exDate': '11-Oct-2026', 'subject': 'Bonus 1:1', 'isin': ''}]
    rows, _, counts = ca.classify_records(recs, AS_OF)
    assert [r['symbol'] for r in rows] == ['AAA'] and counts['deferred'] == 1


def test_same_day_actions_combine(tmp_path):
    """Bonus and split on one ex_date are stored as two rows and multiply on load."""
    recs = [{'symbol': 'XYZ', 'series': 'EQ', 'exDate': '05-Mar-2015',
             'subject': 'Bonus 1:1 / Face Value Split From Rs 10/- To Rs 2/-', 'isin': 'INE000X01011'}]
    rows, _, _ = ca.classify_records(recs, AS_OF)
    path = tmp_path / 'history.csv'
    ca.write_history(path, rows)
    table = ca.load_history(path)
    assert table == {'XYZ': [(date(2015, 3, 5), 10.0)]}


def test_adjustment_maths(tmp_path):
    """ANANDRATHI's raw pre-bonus close 3539.30 / 2 = 1769.65 (MyInvestIQ's verified figure); range semantics."""
    table = {'ANANDRATHI': [(date(2025, 3, 20), 2.0)], 'TWO': [(date(2015, 1, 5), 5.0), (date(2016, 1, 5), 2.0)]}
    assert ca.adjust_price(table, 'ANANDRATHI', 3539.30, date(2025, 3, 19), date(2025, 3, 20)) == pytest.approx(1769.65)
    assert ca.adjust_price(table, 'ANANDRATHI', 1769.65, date(2025, 3, 20), date(2025, 6, 1)) == 1769.65
    assert ca.cumulative_factor(table, 'TWO', date(2014, 1, 1), date(2026, 1, 1)) == 10.0
    assert ca.cumulative_factor(table, 'TWO', date(2015, 1, 5), date(2026, 1, 1)) == 2.0  # ex_date itself excluded
    assert ca.cumulative_factor(table, 'NONE', date(2014, 1, 1), date(2026, 1, 1)) == 1.0
    assert ca.adjust_volume(table, 'TWO', 100, date(2014, 1, 1), date(2015, 1, 5)) == 500
