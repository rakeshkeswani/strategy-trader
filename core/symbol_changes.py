# -*- coding: utf-8 -*-
# core/symbol_changes.py
"""
ST-003 (shared with ST-013) -- NSE symbol renames: "which symbol did this company trade under on date X?"

Source: NSE https://nsearchives.nseindia.com/content/equities/symbolchange.csv (snapshot saved by
ingestion/fetch_symbol_changes.py). No header row; each row is
  <company name, may contain commas>,<old symbol>,<new symbol>,<DD-MON-YYYY applicable from>
From the applicable date the NEW symbol trades; before it, the OLD one (verified 2026-10-11 against bhavcopy:
INFIBEAM -> CCAVENUE 03-FEB-2026, TIDEWATER -> VEEDOL 09-OCT-2024, KARDA -> KBCGLOBAL 16-DEC-2021).

Why it exists: the corporate-actions feed reports a past action under the company's CURRENT symbol, while bhavcopy
carries the symbol in use on that day. Chains are followed (KARDA -> KBCGLOBAL -> DHARAN).
"""

import csv
from datetime import date, datetime
from pathlib import Path

from core.config import SYMBOL_CHANGES_DIR

SNAPSHOT_NAME = 'symbolchange.csv'


def parse_rows(text: str) -> list[tuple[str, str, date]]:
    """Parse symbolchange.csv text into [(old, new, applicable_from)], skipping rows that do not parse."""
    out = []
    for row in csv.reader(text.splitlines()):
        if len(row) < 4:
            continue
        old, new, when = row[-3].strip().upper(), row[-2].strip().upper(), row[-1].strip()
        try:
            d = datetime.strptime(when, '%d-%b-%Y').date()
        except ValueError:
            continue
        if old and new and old != new:
            out.append((old, new, d))
    return out


def load_changes(path: Path | None = None) -> dict:
    """Load the snapshot into {new_symbol: [(applicable_from, old_symbol), ...]} newest first.

    Raises:
        FileNotFoundError: snapshot missing (run ingestion.fetch_symbol_changes first).
    """
    path = path or (SYMBOL_CHANGES_DIR / SNAPSHOT_NAME)
    by_new: dict = {}
    for old, new, d in parse_rows(path.read_bytes().decode('latin-1')):
        by_new.setdefault(new, []).append((d, old))
    for lst in by_new.values():
        lst.sort(reverse=True)
    return by_new


def symbol_on(changes: dict, symbol: str, on: date) -> str:
    """Return the symbol that `symbol` (as named today) traded under on date `on`.

    Walks back through renames whose applicable date is AFTER `on`, newest first; each step must be earlier than
    the one before, so a chain cannot loop.
    """
    current, ceiling = symbol.upper(), date.max
    for _ in range(20):
        step = next(((d, old) for d, old in changes.get(current, ()) if on < d < ceiling), None)
        if step is None:
            return current
        ceiling, current = step
    return current
