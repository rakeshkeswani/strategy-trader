# -*- coding: utf-8 -*-
# core/legacy_bhavcopy_reader.py
"""
ST-002 -- read NSE's legacy-format CM bhavcopy (cm{DD}{MON}{YYYY}bhav.csv.zip, the format NSE
published until 2024-07-05) from the archive ingestion/fetch_legacy_bhavcopy.py writes.

Return shape matches core/udiff_bhavcopy_reader.py so core/prices.py can switch between the two
by date without callers noticing:
    {symbol: {'open', 'high', 'low', 'close', 'prev_close', 'volume', 'traded_value',
              'isin', 'series', 'source'}}

Rules carried over from MyInvestIQ's core/bhavcopy_reader.py (TD-211):
  - RAW exchange values. Split/bonus adjustment happens at read time elsewhere (ST-003).
  - Equity series only: EQ (regular) and BE (trade-to-trade).
  - Key by SYMBOL, never ISIN.
  - A missing FILE raises BhavcopyDateMissingError; a missing SYMBOL is simply absent.
"""

import csv
import io
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path

from core.config import LEGACY_BHAVCOPY_DIR

logger = logging.getLogger(__name__)

NSE_EQUITY_SERIES = {'EQ', 'BE'}
MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
REQUIRED_COLUMNS = {'SYMBOL', 'SERIES', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'PREVCLOSE',
                    'TOTTRDQTY', 'TOTTRDVAL', 'TIMESTAMP', 'ISIN'}
LAST_LEGACY_DATE = date(2024, 7, 5)


class BhavcopyDateMissingError(Exception):
    """No archived bhavcopy file exists for the requested date."""

    def __init__(self, target_date: date):
        self.target_date = target_date
        super().__init__(f"No legacy bhavcopy archived for {target_date.isoformat()}")


class BhavcopyFormatError(Exception):
    """A file exists but is not a usable legacy bhavcopy (bad zip, missing columns, wrong date)."""


def legacy_filename(d: date) -> str:
    """Return NSE's legacy filename for date `d`, e.g. cm02JAN2014bhav.csv.zip."""
    return f"cm{d.day:02d}{MONTHS[d.month - 1]}{d.year}bhav.csv.zip"


def legacy_path(d: date, archive_dir: Path | None = None) -> Path:
    """Return the archive path for date `d`: <archive>/<YYYY>/<legacy filename>."""
    return (archive_dir or LEGACY_BHAVCOPY_DIR) / str(d.year) / legacy_filename(d)


def legacy_timestamp(d: date) -> str:
    """Return the TIMESTAMP value NSE prints in a legacy file for date `d`, e.g. 02-JAN-2014."""
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def extract_csv_text(raw_zip: bytes) -> str:
    """Return the text of the single CSV member inside a legacy bhavcopy zip.

    Raises:
        BhavcopyFormatError: not a zip, or no .csv member.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
            if not names:
                raise BhavcopyFormatError('zip has no .csv member')
            return zf.read(names[0]).decode('utf-8', errors='replace')
    except zipfile.BadZipFile as e:
        raise BhavcopyFormatError(f'not a valid zip: {e}') from e


def parse_legacy_csv(csv_text: str, expected_date: date | None = None) -> dict:
    """Parse legacy bhavcopy CSV text into the shared per-symbol dict (EQ/BE rows only).

    Args:
        csv_text: decoded CSV text.
        expected_date: if given, every row's TIMESTAMP must equal this date.

    Returns:
        {symbol: record}. Rows with a non-numeric CLOSE or PREVCLOSE are skipped; other numeric
        fields degrade to None individually (same policy as MyInvestIQ's reader).

    Raises:
        BhavcopyFormatError: required columns missing, or a TIMESTAMP that is not expected_date.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    header = {(h or '').strip() for h in (reader.fieldnames or [])}
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise BhavcopyFormatError(f'missing columns: {sorted(missing)}')

    expected_ts = legacy_timestamp(expected_date).upper() if expected_date else None
    out: dict = {}
    for raw in reader:
        row = {(k or '').strip(): (v or '').strip() for k, v in raw.items() if k is not None}
        if expected_ts and row.get('TIMESTAMP', '').upper() != expected_ts:
            raise BhavcopyFormatError(
                f"TIMESTAMP {row.get('TIMESTAMP')!r} != expected {expected_ts!r}")
        if row.get('SERIES') not in NSE_EQUITY_SERIES:
            continue
        symbol = row.get('SYMBOL')
        if not symbol:
            continue
        try:
            close = float(row['CLOSE'])
            prev_close = float(row['PREVCLOSE'])
        except (KeyError, ValueError):
            continue

        def _f(col: str) -> float | None:
            try:
                return float(row[col])
            except (KeyError, ValueError):
                return None

        def _i(col: str) -> int | None:
            v = _f(col)
            return int(v) if v is not None else None

        out[symbol] = {
            'open': _f('OPEN'), 'high': _f('HIGH'), 'low': _f('LOW'),
            'close': close, 'prev_close': prev_close,
            'volume': _i('TOTTRDQTY'), 'traded_value': _f('TOTTRDVAL'),
            'isin': row.get('ISIN') or None, 'series': row.get('SERIES'),
            'source': 'NSE_LEGACY',
        }
    return out


def count_rows(csv_text: str) -> int:
    """Return the number of data rows (all series) in a CSV text."""
    return max(sum(1 for line in csv_text.splitlines() if line.strip()) - 1, 0)


def read_ohlcv_for_date(target_date: date, archive_dir: Path | None = None) -> dict:
    """Read one date's legacy bhavcopy from the archive.

    Raises:
        BhavcopyDateMissingError: no file archived for this date.
        BhavcopyFormatError: the file is corrupt or not the expected date (fail loudly).
    """
    path = legacy_path(target_date, archive_dir)
    if not path.exists():
        raise BhavcopyDateMissingError(target_date)
    return parse_legacy_csv(extract_csv_text(path.read_bytes()), expected_date=target_date)


def parse_timestamp(value: str) -> date:
    """Parse a legacy TIMESTAMP like 02-JAN-2014 into a date."""
    return datetime.strptime(value.strip().title(), '%d-%b-%Y').date()
