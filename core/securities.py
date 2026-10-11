# -*- coding: utf-8 -*-
# core/securities.py
"""
ST-013 -- one continuous identity per company across NSE renames.

The company KEY is the symbol the company trades under today (Rakesh, 2026-10-11, option a): TIDEWATER's history
belongs to key VEEDOL. Built from core.symbol_changes (NSE snapshot + config/symbol_changes_extra.csv); nothing is
stored. A key changes if the company renames again -- research outputs are regenerated, so that is accepted.

Rules (each rename row = old, new, applicable_from; from that date the NEW symbol trades):
  - key_on(symbol, d) follows renames FORWARD from d: TIDEWATER on 2021-07-26 -> VEEDOL.
  - symbols_for(key) walks BACK from the key: [(TIDEWATER, None, 2024-10-09), (VEEDOL, 2024-10-09, None)].
  - A reused symbol is a different company after the rename that gave it away, because every step is bounded by
    its date (X traded by A until X->Y; X given to B later by Z->X belongs to B only from then).
Mergers / delistings are not renames: the last symbol simply stops (survivorship is ST-004).
"""

import re
from datetime import date, timedelta

from core.prices import BhavcopyDateMissingError, read_ohlcv_for_date
from core.symbol_changes import load_changes

RIGHTS_ENTITLEMENT = re.compile(r'-RE\d*$')
MAX_CHAIN = 20


def is_equity(symbol: str, isin: str | None) -> bool:
    """True for a listed equity: ISIN starting INE or IN9 (DVR), and not a -RE/-RE<n> rights entitlement."""
    return bool(isin) and isin[:3] in ('INE', 'IN9') and not RIGHTS_ENTITLEMENT.search(symbol)


class Securities:
    """Rename graph with forward (old -> new) and backward (new -> old) lookups."""

    def __init__(self, changes: dict):
        """`changes` is core.symbol_changes.load_changes(): {new: [(applicable_from, old), ...] newest first}."""
        self.back = changes
        fwd: dict = {}
        for new, steps in changes.items():
            for d, old in steps:
                fwd.setdefault(old, []).append((d, new))
        for lst in fwd.values():
            lst.sort()
        self.fwd = fwd

    @classmethod
    def load(cls) -> 'Securities':
        """Build from the NSE snapshot plus config/symbol_changes_extra.csv.

        Raises:
            FileNotFoundError: snapshot missing (run ingestion.fetch_symbol_changes first).
        """
        return cls(load_changes())

    def key_on(self, symbol: str, on: date) -> str:
        """Return the company key (today's symbol) for `symbol` as traded on date `on`."""
        current, floor = symbol.upper(), on
        for _ in range(MAX_CHAIN):
            step = next(((d, new) for d, new in self.fwd.get(current, ()) if d > floor), None)
            if step is None:
                return current
            floor, current = step
        return current

    def symbols_for(self, key: str) -> list[tuple[str, date | None, date | None]]:
        """Return the lineage of `key` as [(symbol, from_inclusive, to_exclusive)], oldest first (None = open)."""
        segs, current, end, ceiling = [], key.upper(), None, date.max
        for _ in range(MAX_CHAIN):
            step = next(((d, old) for d, old in self.back.get(current, ()) if d < ceiling), None)
            segs.append((current, step[0] if step else None, end))
            if step is None:
                break
            end = ceiling = step[0]
            current = step[1]
        return list(reversed(segs))

    def symbol_for_key_on(self, key: str, on: date) -> str | None:
        """Return the symbol `key` traded under on date `on`, or None if `on` is outside its lineage."""
        for symbol, start, end in self.symbols_for(key):
            if (start is None or on >= start) and (end is None or on < end):
                return symbol
        return None

    def read_stitched_ohlcv(self, key: str, start: date, end: date) -> list[tuple[date, str, dict]]:
        """Return [(date, symbol_traded_that_day, record)] for `key` across renames, raw (unadjusted) prices.

        Reads one bhavcopy per calendar day, so it suits checks and single names; panels are built in ST-004.
        """
        out = []
        d = start
        while d <= end:
            symbol = self.symbol_for_key_on(key, d)
            if symbol:
                try:
                    rec = read_ohlcv_for_date(d).get(symbol)
                except BhavcopyDateMissingError:
                    rec = None
                if rec:
                    out.append((d, symbol, rec))
            d += timedelta(days=1)
        return out
