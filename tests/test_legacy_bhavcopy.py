# -*- coding: utf-8 -*-
"""ST-002 unit tests -- no network, no real archive. Synthetic files built in tmp_path."""

import io
import zipfile
from datetime import date

import pytest

from core import legacy_bhavcopy_reader as legacy
from core import prices
from core import udiff_bhavcopy_reader as udiff
from core.legacy_bhavcopy_reader import BhavcopyDateMissingError, BhavcopyFormatError
from ingestion import fetch_legacy_bhavcopy as fetch

LEGACY_HEADER = ('SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,'
                 'TIMESTAMP,TOTALTRADES,ISIN,')
D = date(2014, 1, 2)


def legacy_csv(ts: str = '02-JAN-2014', extra_rows: int = 0) -> str:
    """Build a small legacy CSV: one EQ, one BE, one non-equity row, plus filler N-series rows."""
    rows = [
        f'RELIANCE,EQ,880.00,885.50,872.10,875.35,875.00,881.20,1234567,1080000000.50,{ts},45000,INE002A01018,',
        f'ABCBE,BE,10.00,10.50,9.90,10.20,10.20,10.00,500,5100.00,{ts},12,INE000X01011,',
        f'GOLDBOND,GB,2900.00,2910.00,2895.00,2905.00,2905.00,2900.00,10,29050.00,{ts},3,IN0020000000,',
    ]
    rows += [f'FILL{i},N1,1,1,1,1,1,1,1,1,{ts},1,INE{i:09d},' for i in range(extra_rows)]
    return LEGACY_HEADER + '\n' + '\n'.join(rows) + '\n'


def zip_bytes(csv_text: str, name: str = 'cm02JAN2014bhav.csv') -> bytes:
    """Wrap CSV text in an in-memory zip, as NSE serves it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def test_filename_url_and_timestamp():
    assert legacy.legacy_filename(D) == 'cm02JAN2014bhav.csv.zip'
    assert fetch.url_for(D) == ('https://nsearchives.nseindia.com/content/historical/EQUITIES/'
                                '2014/JAN/cm02JAN2014bhav.csv.zip')
    assert legacy.legacy_timestamp(date(2023, 12, 29)) == '29-DEC-2023'
    assert legacy.parse_timestamp('29-DEC-2023') == date(2023, 12, 29)
    assert legacy.parse_timestamp('13-Jul-20') == date(2020, 7, 13)  # real variant, 2020-07-13 file


def test_parse_keeps_only_equity_series_with_all_fields():
    out = legacy.parse_legacy_csv(legacy_csv(), expected_date=D)
    assert set(out) == {'RELIANCE', 'ABCBE'}
    r = out['RELIANCE']
    assert (r['open'], r['high'], r['low'], r['close'], r['prev_close']) == (880.0, 885.5, 872.1, 875.35, 881.2)
    assert r['volume'] == 1234567 and r['traded_value'] == 1080000000.5
    assert r['isin'] == 'INE002A01018' and r['series'] == 'EQ' and r['source'] == 'NSE_LEGACY'


def test_wrong_date_and_missing_columns_fail_loudly():
    with pytest.raises(BhavcopyFormatError, match='TIMESTAMP'):
        legacy.parse_legacy_csv(legacy_csv(ts='03-JAN-2014'), expected_date=D)
    with pytest.raises(BhavcopyFormatError, match='unparseable'):
        legacy.parse_legacy_csv(legacy_csv(ts='2014/01/02'), expected_date=D)
    # short-year variant for the right date is accepted
    assert 'RELIANCE' in legacy.parse_legacy_csv(legacy_csv(ts='02-Jan-14'), expected_date=D)
    with pytest.raises(BhavcopyFormatError, match='missing columns'):
        legacy.parse_legacy_csv('SYMBOL,SERIES,CLOSE\nX,EQ,1\n', expected_date=D)


def test_validate_payload_rejects_html_and_truncated_and_accepts_real():
    with pytest.raises(BhavcopyFormatError, match='not a zip'):
        fetch.validate_payload(b'<!DOCTYPE html><html>error</html>', D)
    with pytest.raises(BhavcopyFormatError, match='rows'):
        fetch.validate_payload(zip_bytes(legacy_csv()), D)
    rows, eq = fetch.validate_payload(zip_bytes(legacy_csv(extra_rows=600)), D)
    assert rows == 603 and eq == 2


def test_read_from_archive_and_missing_date(tmp_path):
    path = legacy.legacy_path(D, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(zip_bytes(legacy_csv()))
    assert 'RELIANCE' in legacy.read_ohlcv_for_date(D, tmp_path)
    with pytest.raises(BhavcopyDateMissingError):
        legacy.read_ohlcv_for_date(date(2014, 1, 3), tmp_path)


def test_weekdays_skips_weekends():
    days = fetch.weekdays(date(2014, 1, 3), date(2014, 1, 7))  # Fri..Tue
    assert days == [date(2014, 1, 3), date(2014, 1, 6), date(2014, 1, 7)]


def test_udiff_parse_matches_shared_shape():
    header = ('TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,'
              'FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,'
              'LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,'
              'TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4')
    row = ('2024-01-02,2024-01-02,CM,NSE,STK,2885,INE002A01018,RELIANCE,EQ,,,,,RELIANCE IND,'
           '2580.00,2600.00,2570.00,2590.00,2591.00,2585.00,,2590.00,,,1000,2590000.00,50,F1,1,,,,,')
    out = udiff.parse_udiff_csv(header + '\n' + row + '\n')
    assert set(out['RELIANCE']) == set(legacy.parse_legacy_csv(legacy_csv(), D)['RELIANCE'])
    assert out['RELIANCE']['traded_value'] == 2590000.0 and out['RELIANCE']['source'] == 'NSE_UDIFF'


def test_prices_routes_by_date(monkeypatch):
    monkeypatch.setattr(prices.legacy, 'read_ohlcv_for_date', lambda d: 'legacy')
    monkeypatch.setattr(prices.udiff, 'read_ohlcv_for_date', lambda d: 'udiff')
    assert prices.read_ohlcv_for_date(date(2023, 12, 29)) == 'legacy'
    assert prices.read_ohlcv_for_date(date(2024, 1, 1)) == 'udiff'


def test_refuses_network_share():
    from pathlib import PureWindowsPath
    assert fetch._is_network_share(PureWindowsPath(r'\\100.103.189.15\myinvestiq\data'))
    assert not fetch._is_network_share(PureWindowsPath('/home/rakeshbk/myinvestiq/data/bhavcopy_legacy'))


def test_udiff_reads_myinvestiq_first_then_gap_dir(tmp_path):
    header = ('TradDt,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,PrvsClsgPric,TtlTradgVol,TtlTrfVal,ISIN')
    def write(folder, d, close):
        folder.mkdir(parents=True, exist_ok=True)
        csv_text = header + f'\n{d.isoformat()},RELIANCE,EQ,1,1,1,{close},1,1,1,INE002A01018\n'
        name = udiff.NSE_FILENAME_TMPL.format(date_str=d.strftime('%Y%m%d'))
        (folder / name).write_bytes(zip_bytes(csv_text, name[:-4]))
    main, gap = tmp_path / 'myinvestiq', tmp_path / 'gap'
    d_both, d_gap, d_none = date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)
    write(main, d_both, 100.0)
    write(gap, d_both, 999.0)
    write(gap, d_gap, 200.0)
    assert udiff.read_ohlcv_for_date(d_both, main, gap)['RELIANCE']['close'] == 100.0  # MyInvestIQ wins
    assert udiff.read_ohlcv_for_date(d_gap, main, gap)['RELIANCE']['close'] == 200.0
    with pytest.raises(BhavcopyDateMissingError):
        udiff.read_ohlcv_for_date(d_none, main, gap)
