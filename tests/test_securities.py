# -*- coding: utf-8 -*-
"""ST-013 unit tests for core.securities -- rename rows copied from NSE symbolchange.csv / extras (2026-10-11)."""

from datetime import date

from core import securities as sec
from core import symbol_changes as sc

SNAPSHOT = '\n'.join([
    'Veedol Corporation Limited,TIDEWATER,VEEDOL,09-OCT-2024',
    'KBC Global Limited,KARDA,KBCGLOBAL,16-DEC-2021',
    'Dharan Infra-EPC Limited,KBCGLOBAL,DHARAN,01-MAR-2024',      # second step (date illustrative)
    'PCBL Limited,PHILIPCARB,PCBL,13-JAN-2022',
    # reuse: company A trades OLDX until 2016 (OLDX -> ANEW); company B later takes OLDX (BPREV -> OLDX, 2019)
    'Company A,OLDX,ANEW,01-JUN-2016',
    'Company B,BPREV,OLDX,01-JUN-2019',
])


def _secs(tmp_path) -> sec.Securities:
    """Build Securities from the snapshot above (no extras)."""
    p = tmp_path / 'symbolchange.csv'
    p.write_bytes(SNAPSHOT.encode('latin-1'))
    return sec.Securities(sc.load_changes(p, extra_path=None))


def test_key_is_todays_symbol(tmp_path):
    """Any symbol on any date maps to the symbol the company trades under now."""
    s = _secs(tmp_path)
    assert s.key_on('TIDEWATER', date(2021, 7, 26)) == 'VEEDOL'
    assert s.key_on('VEEDOL', date(2025, 1, 1)) == 'VEEDOL'
    assert s.key_on('KARDA', date(2021, 8, 12)) == 'DHARAN'
    assert s.key_on('KBCGLOBAL', date(2022, 6, 1)) == 'DHARAN'
    assert s.key_on('RELIANCE', date(2015, 1, 1)) == 'RELIANCE'


def test_lineage_oldest_first(tmp_path):
    """symbols_for gives each symbol with its [from, to) range."""
    s = _secs(tmp_path)
    assert s.symbols_for('DHARAN') == [('KARDA', None, date(2021, 12, 16)),
                                       ('KBCGLOBAL', date(2021, 12, 16), date(2024, 3, 1)),
                                       ('DHARAN', date(2024, 3, 1), None)]
    assert s.symbols_for('RELIANCE') == [('RELIANCE', None, None)]
    assert s.symbol_for_key_on('VEEDOL', date(2024, 10, 8)) == 'TIDEWATER'
    assert s.symbol_for_key_on('VEEDOL', date(2024, 10, 9)) == 'VEEDOL'


def test_reused_symbol_is_two_companies(tmp_path):
    """OLDX before 2016 is company A (key ANEW); OLDX from 2019 is company B (key OLDX)."""
    s = _secs(tmp_path)
    assert s.key_on('OLDX', date(2015, 1, 1)) == 'ANEW'
    assert s.key_on('OLDX', date(2020, 1, 1)) == 'OLDX'
    assert s.symbols_for('ANEW') == [('OLDX', None, date(2016, 6, 1)), ('ANEW', date(2016, 6, 1), None)]
    assert s.symbols_for('OLDX') == [('BPREV', None, date(2019, 6, 1)), ('OLDX', date(2019, 6, 1), None)]
    assert s.symbol_for_key_on('OLDX', date(2015, 1, 1)) == 'BPREV'   # company B's own history, not A's OLDX


def test_is_equity():
    """INE/IN9 equities count; ETFs (INF), rights entitlements and missing ISINs do not."""
    assert sec.is_equity('RELIANCE', 'INE002A01018') and sec.is_equity('TATAMTRDVR', 'IN9155A01020')
    assert not sec.is_equity('NIFTYBEES', 'INF204KB14I2')
    assert not sec.is_equity('ASIAN-RE1', 'INE00AB20013') and not sec.is_equity('XYZ', None)
