# -*- coding: utf-8 -*-
"""ST-003 unit tests for core.symbol_changes -- rows copied from NSE symbolchange.csv (2026-10-11)."""

from datetime import date

from core import corporate_actions as ca
from core import symbol_changes as sc

SNAPSHOT = '\n'.join([
    'AvenuesAI Limited,INFIBEAM,CCAVENUE,03-FEB-2026',
    'Veedol Corporation Limited,TIDEWATER,VEEDOL,09-OCT-2024',
    'KBC Global Limited,KARDA,KBCGLOBAL,16-DEC-2021',
    'Dharan Infra-EPC Limited,KBCGLOBAL,DHARAN,01-MAR-2024',      # second step of the chain (date illustrative)
    'Dhunseri Ventures Limited,DPL,DVL,02-JAN-2019',
    ' NIPPON INDIA MF - Dual Advantage, Plan E - GO,RDAXEDG,NDAXEDG,30-OCT-2019',  # comma inside the name
    'garbage line',
    ',780LTFL30,799LTFL30,19-FEB-2025',
])


def _changes(tmp_path):
    """Write the snapshot to a temp file and load it."""
    p = tmp_path / 'symbolchange.csv'
    p.write_bytes(SNAPSHOT.encode('latin-1'))
    return sc.load_changes(p, extra_path=None)


def test_curated_extras_are_merged(tmp_path):
    """Renames missing from NSE's list come from config/symbol_changes_extra.csv."""
    p = tmp_path / 'symbolchange.csv'
    p.write_bytes(SNAPSHOT.encode('latin-1'))
    ch = sc.load_changes(p)   # default extra file = the real config/symbol_changes_extra.csv
    assert sc.symbol_on(ch, 'PCBL', date(2018, 4, 19)) == 'PHILIPCARB'
    assert sc.symbol_on(ch, 'ESSENTIA', date(2022, 2, 3)) == 'INTEGRA'
    assert sc.symbol_on(ch, 'ESSENTIA', date(2022, 3, 7)) == 'ESSENTIA'


def test_parse_rows_handles_commas_and_garbage():
    """Company names with commas parse; unparseable lines are skipped."""
    rows = sc.parse_rows(SNAPSHOT)
    assert ('RDAXEDG', 'NDAXEDG', date(2019, 10, 30)) in rows
    assert len(rows) == 7


def test_symbol_on_before_and_after_rename(tmp_path):
    """Before the applicable date the old symbol traded; on/after it the new one."""
    ch = _changes(tmp_path)
    assert sc.symbol_on(ch, 'CCAVENUE', date(2021, 3, 18)) == 'INFIBEAM'
    assert sc.symbol_on(ch, 'CCAVENUE', date(2026, 2, 3)) == 'CCAVENUE'
    assert sc.symbol_on(ch, 'VEEDOL', date(2021, 7, 26)) == 'TIDEWATER'
    assert sc.symbol_on(ch, 'DVL', date(2021, 8, 5)) == 'DVL'
    assert sc.symbol_on(ch, 'DVL', date(2018, 6, 1)) == 'DPL'
    assert sc.symbol_on(ch, 'RELIANCE', date(2015, 1, 1)) == 'RELIANCE'


def test_symbol_on_follows_chains(tmp_path):
    """DHARAN <- KBCGLOBAL <- KARDA: each step only applies to dates before it."""
    ch = _changes(tmp_path)
    assert sc.symbol_on(ch, 'DHARAN', date(2021, 8, 12)) == 'KARDA'
    assert sc.symbol_on(ch, 'DHARAN', date(2022, 6, 1)) == 'KBCGLOBAL'
    assert sc.symbol_on(ch, 'DHARAN', date(2025, 1, 1)) == 'DHARAN'


def test_classify_records_stores_symbol_in_use_on_ex_date(tmp_path):
    """The feed's CCAVENUE bonus of 2021 is stored under INFIBEAM, with feed_symbol kept."""
    ch = _changes(tmp_path)
    recs = [{'symbol': 'CCAVENUE', 'series': 'EQ', 'exDate': '18-Mar-2021', 'subject': ' Bonus 1:1',
             'isin': 'INE483S01020'}]
    rows, _, counts = ca.classify_records(recs, date(2026, 10, 11), ch)
    assert (rows[0]['symbol'], rows[0]['feed_symbol'], counts['renamed']) == ('INFIBEAM', 'CCAVENUE', 1)
