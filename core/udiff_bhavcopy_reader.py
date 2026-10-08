# -*- coding: utf-8 -*-
# core/udiff_bhavcopy_reader.py
"""
ST-002 -- read NSE UDiFF bhavcopy (2024-01-01 onward) from MyInvestIQ's archive, READ-ONLY.

COPIED (not imported) from MyInvestIQ core/bhavcopy_reader.py (_parse_udiff_csv_full,
_read_nse_zip; MyInvestIQ commit ac5493c, 2026-10-08) so the two repos stay independent.
Differences from the original:
  - NSE only. BSE is not needed for a Nifty 500 universe.
  - Adds traded_value (TtlTrfVal), isin and series -- ST-004 ranks stocks by traded value.
  - Archive location comes ONLY from BHAVCOPY_ARCHIVE_DIR; there is no default, and this
    module never writes anywhere.
  - A date missing from MyInvestIQ's archive is then looked up in UDIFF_GAP_DIR (this
    project's own files for 2024-01-03 to 2025-08-27). MyInvestIQ's archive always wins.
"""

import csv
import io
import zipfile
from datetime import date
from pathlib import Path

from core.config import BHAVCOPY_ARCHIVE_DIR, UDIFF_GAP_DIR
from core.legacy_bhavcopy_reader import BhavcopyDateMissingError, BhavcopyFormatError

NSE_EQUITY_SERIES = {'EQ', 'BE'}
NSE_FILENAME_TMPL = 'BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip'
UDIFF_ARCHIVE_START = date(2024, 1, 1)


def _archive_dir(archive_dir: Path | None) -> Path:
    """Resolve the archive dir; refuse to guess when BHAVCOPY_ARCHIVE_DIR is unset."""
    d = archive_dir or BHAVCOPY_ARCHIVE_DIR
    if d is None:
        raise RuntimeError('BHAVCOPY_ARCHIVE_DIR is not set (MyInvestIQ UDiFF archive, read-only)')
    return d


def parse_udiff_csv(csv_text: str) -> dict:
    """Parse UDiFF CSV text into the shared per-symbol dict (EQ/BE rows only)."""
    out: dict = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get('SctySrs') not in NSE_EQUITY_SERIES:
            continue
        symbol = row.get('TckrSymb')
        if not symbol:
            continue
        try:
            close = float(row['ClsPric'])
            prev_close = float(row['PrvsClsgPric'])
        except (KeyError, ValueError, TypeError):
            continue

        def _f(col: str) -> float | None:
            try:
                return float(row[col])
            except (KeyError, ValueError, TypeError):
                return None

        def _i(col: str) -> int | None:
            v = _f(col)
            return int(v) if v is not None else None

        out[symbol] = {
            'open': _f('OpnPric'), 'high': _f('HghPric'), 'low': _f('LwPric'),
            'close': close, 'prev_close': prev_close,
            'volume': _i('TtlTradgVol'), 'traded_value': _f('TtlTrfVal'),
            'isin': row.get('ISIN') or None, 'series': row.get('SctySrs'),
            'source': 'NSE_UDIFF',
        }
    return out


def _find_file(target_date: date, archive_dir: Path | None, gap_dir: Path | None) -> Path:
    """Return the NSE file for `target_date`: MyInvestIQ's archive first, then the gap dir.

    Raises:
        BhavcopyDateMissingError: in neither location.
    """
    name = NSE_FILENAME_TMPL.format(date_str=target_date.strftime('%Y%m%d'))
    primary = _archive_dir(archive_dir) / name
    if primary.exists():
        return primary
    gap = gap_dir if gap_dir is not None else UDIFF_GAP_DIR
    if gap is not None and (gap / name).exists():
        return gap / name
    raise BhavcopyDateMissingError(target_date)


def read_ohlcv_for_date(target_date: date, archive_dir: Path | None = None,
                        gap_dir: Path | None = None) -> dict:
    """Read one date's NSE UDiFF bhavcopy (MyInvestIQ's archive, else this project's gap dir).

    Raises:
        BhavcopyDateMissingError: no NSE file for this date in either location.
        BhavcopyFormatError: unreadable zip.
    """
    path = _find_file(target_date, archive_dir, gap_dir)
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
            if not names:
                raise BhavcopyFormatError(f'{path}: zip has no .csv member')
            csv_text = zf.read(names[0]).decode('utf-8')
    except zipfile.BadZipFile as e:
        raise BhavcopyFormatError(f'{path}: {e}') from e
    return parse_udiff_csv(csv_text)
