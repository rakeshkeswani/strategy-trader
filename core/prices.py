# -*- coding: utf-8 -*-
# core/prices.py
"""
ST-002 -- single entry point for daily NSE equity prices, any date from 2014.

  date <  2024-01-01 -> legacy archive (this project's one-time download)
  date >= 2024-01-01 -> MyInvestIQ's UDiFF archive (read-only, kept current by its 18:00 job)

Jan-Jul 2024 exists in both formats; it is used only by scripts/validate_legacy_bhavcopy.py.
Values are RAW (unadjusted for splits/bonuses) until ST-003 adds adjustment.
"""

from datetime import date

from core import legacy_bhavcopy_reader as legacy
from core import udiff_bhavcopy_reader as udiff
from core.legacy_bhavcopy_reader import BhavcopyDateMissingError, BhavcopyFormatError  # noqa: F401

SWITCH_DATE = udiff.UDIFF_ARCHIVE_START


def read_ohlcv_for_date(target_date: date) -> dict:
    """Return {symbol: record} for one trading date from whichever archive covers it.

    Raises:
        BhavcopyDateMissingError: no file for that date (holiday, weekend or a gap).
    """
    if target_date < SWITCH_DATE:
        return legacy.read_ohlcv_for_date(target_date)
    return udiff.read_ohlcv_for_date(target_date)
