# -*- coding: utf-8 -*-
# core/corporate_actions.py
"""
ST-003 -- parse NSE corporate-action subjects into price-scale factors, and apply them.

Scope: BONUS, SPLIT and CONSOLIDATION (reverse split) -- the actions that change the price scale with a clean
ratio. Rights, mergers, demergers and dividends are out of scope.

Based on MyInvestIQ core/corporate_actions.py (TD-211 B3; read 2026-10-11) -- same factor maths, same traps --
but the parser is rewritten: MyInvestIQ's whole-subject regexes fit the 2025-26 feed, while 2014-2018 subjects
are messier (verified live 2026-10-11, tests/fixtures/ca_history_shapes_2014_2018.json):
  - several actions in one subject: "Bonus 1:1 / Face Value Split From Rs 10/- To Rs 5/-",
    "Dividend Rs 2.50/- Per Share / Bonus 1 : 4", "Bonus 1:1 And Face Value Split Rs.10/- To Rs.5/-"
  - spacing and wording: "Bonus 1 : 1", "Bonus Issue 1 : 1", "Sub-Division From Rs 10/- ...", "Rs.10/-", "Re.1/-",
    "From 10/- To Face Value 2/-"
  - "Rs 10/-" contains a "/", so a subject is split into parts only on a "/" NOT followed by "-".

Traps (each excluded with a named reason, never adjusted):
  - preference shares, NCRPS and debentures wearing a "Bonus" subject are not the equity;
  - "Capital Reduction ... / Consolidation ..." has no safe automatic factor -> REVIEW (manual decision);
  - never join on the feed's `isin` (MyInvestIQ CORPORATE_ACTIONS_FINDINGS Q6) -- join by symbol;
  - the feed files past actions under the company's CURRENT symbol (2021: INFIBEAM's bonus under CCAVENUE), so
    each row's `symbol` is the one in use on ex_date (core.symbol_changes); `feed_symbol` keeps what the feed said;
  - only actions with ex_date before the run date are kept (publication timing unknown, Q7).

Any part that mentions bonus / split / sub-division / consolidation and is not parsed, excluded or sent to review
is UNCLASSIFIED -- callers treat that as a failure, so a new subject shape cannot be skipped silently.

Factor maths (MyInvestIQ, verified on ANANDRATHI and TDPOWERSYS):
  BONUS "X:Y" (X new per Y held)   -> (Y + X) / Y      e.g. 1:1 -> 2.0, 1:4 -> 1.25
  SPLIT face value A -> B          -> A / B            e.g. Rs 10 -> Rs 2 -> 5.0
  CONSOLIDATION face value A -> B  -> A / B (< 1)
  A price dated BEFORE ex_date is DIVIDED by the factor to put it on the post-action scale; volume is multiplied.
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from core.config import CORPORATE_ACTIONS_DIR
from core.symbol_changes import symbol_on

ACTION_TYPES = ('BONUS', 'SPLIT', 'CONSOLIDATION')
HISTORY_FIELDS = ['symbol', 'feed_symbol', 'series', 'ex_date', 'action_type', 'adjustment_factor', 'subject_text',
                  'isin']

_NUM = r'(\d+(?:\.\d+)?)'
_PART_SEP = re.compile(r'/(?!-)')
_SHAPE_BONUS = re.compile(r'\bbonus\b', re.I)
_SHAPE_SPLIT = re.compile(r'split|sub[\s-]?div', re.I)
_SHAPE_CONSOL = re.compile(r'consolidat', re.I)
_NOT_EQUITY = re.compile(r'preference|ncrps|debenture', re.I)
_CAPITAL_REDUCTION = re.compile(r'capital\s+reduction', re.I)
_BONUS_RE = re.compile(r'\bbonus(?:\s+issue)?\s*-?\s*(\d+)\s*:\s*(\d+)', re.I)
_SPLIT_RE = re.compile(r'(?:split|sub[\s-]?division)[^\d]*?' + _NUM + r'.*?\bto\b[^\d]*?' + _NUM, re.I)
_CONSOL_RE = re.compile(r'consolidat\w*[^\d]*?' + _NUM + r'.*?\bto\b[^\d]*?' + _NUM, re.I)


@dataclass
class SubjectParse:
    """Result of parsing one subject: scale actions found, plus anything excluded / for review / not understood."""
    actions: list = field(default_factory=list)       # [(action_type, factor)]
    excluded: list = field(default_factory=list)      # [(reason, part)]
    review: list = field(default_factory=list)        # [(reason, part)]
    unclassified: list = field(default_factory=list)  # [part]


def _ratio(a: str, b: str) -> float | None:
    """Return a / b as float, or None when b is zero."""
    a_f, b_f = float(a), float(b)
    return a_f / b_f if b_f else None


def parse_subject(subject: str) -> SubjectParse:
    """Parse one corporate-action `subject` into scale-changing actions.

    A subject is split into parts on "/" not followed by "-" (so "Rs 10/-" stays whole); each part is classified.
    Returns a SubjectParse; dividends and other out-of-scope parts simply produce nothing.
    """
    out = SubjectParse()
    subject = (subject or '').strip()
    if _CAPITAL_REDUCTION.search(subject):
        out.review.append(('capital reduction -- no automatic factor', subject))
        return out
    for part in (p.strip() for p in _PART_SEP.split(subject)):
        if not part:
            continue
        has_bonus, has_split, has_consol = (bool(r.search(part)) for r in (_SHAPE_BONUS, _SHAPE_SPLIT, _SHAPE_CONSOL))
        if not (has_bonus or has_split or has_consol):
            continue
        if _NOT_EQUITY.search(part):
            out.excluded.append(('not equity (preference/NCRPS/debenture)', part))
            continue
        understood = True
        if has_bonus:
            m = _BONUS_RE.search(part)
            factor = _ratio(str(int(m.group(2)) + int(m.group(1))), m.group(2)) if m else None
            if factor:
                out.actions.append(('BONUS', factor))
            else:
                understood = False
        if has_split:
            m = _SPLIT_RE.search(part)
            factor = _ratio(m.group(1), m.group(2)) if m else None
            if factor and factor > 1:
                out.actions.append(('SPLIT', factor))
            else:
                understood = False
        if has_consol:
            m = _CONSOL_RE.search(part)
            factor = _ratio(m.group(1), m.group(2)) if m else None
            if factor and factor < 1:
                out.actions.append(('CONSOLIDATION', factor))
            else:
                understood = False
        if not understood:
            out.unclassified.append(part)
    return out


def classify_records(records: list, as_of: date, changes: dict | None = None) -> tuple[list, list, dict]:
    """Turn raw NSE corporate-action records into history rows.

    Each row's `symbol` is the symbol in use on ex_date when `changes` (core.symbol_changes.load_changes()) is
    given, else the feed's symbol. Rows with the same (symbol, ex_date, action_type) are combined by multiplying
    factors. Records with ex_date >= `as_of` are not kept (publication timing unknown).

    Returns:
        (rows as dicts with HISTORY_FIELDS, issues as [kind, symbol, ex_date, detail], counts dict)
    """
    counts = {'records': len(records), 'BONUS': 0, 'SPLIT': 0, 'CONSOLIDATION': 0, 'excluded': 0,
              'review': 0, 'unclassified': 0, 'deferred': 0, 'bad_record': 0, 'renamed': 0}
    combined: dict = {}
    issues: list = []
    for rec in records:
        symbol, subject, ex_raw = rec.get('symbol'), rec.get('subject') or '', rec.get('exDate')
        try:
            ex_date = datetime.strptime(ex_raw, '%d-%b-%Y').date()
        except (TypeError, ValueError):
            ex_date = None
        parsed = parse_subject(subject)
        if not (parsed.actions or parsed.excluded or parsed.review or parsed.unclassified):
            continue
        if not symbol or ex_date is None:
            counts['bad_record'] += 1
            issues.append(['bad_record', symbol or '', ex_raw or '', subject])
            continue
        feed_symbol = symbol
        symbol = symbol_on(changes, feed_symbol, ex_date) if changes else feed_symbol
        for reason, part in parsed.excluded:
            counts['excluded'] += 1
            issues.append(['excluded', symbol, ex_date.isoformat(), f'{reason}: {part}'])
        for reason, part in parsed.review:
            counts['review'] += 1
            issues.append(['review', symbol, ex_date.isoformat(), f'{reason}: {part}'])
        for part in parsed.unclassified:
            counts['unclassified'] += 1
            issues.append(['unclassified', symbol, ex_date.isoformat(), part])
        if ex_date >= as_of:
            counts['deferred'] += len(parsed.actions)
            continue
        for action_type, factor in parsed.actions:
            key = (symbol, ex_date, action_type)
            if key in combined:
                combined[key]['adjustment_factor'] *= factor
            else:
                combined[key] = {'symbol': symbol, 'feed_symbol': feed_symbol, 'series': rec.get('series') or '',
                                 'ex_date': ex_date, 'action_type': action_type, 'adjustment_factor': factor,
                                 'subject_text': subject.strip(), 'isin': rec.get('isin') or ''}
                counts[action_type] += 1
                counts['renamed'] += symbol != feed_symbol
    rows = sorted(combined.values(), key=lambda r: (r['ex_date'], r['symbol'], r['action_type']))
    return rows, issues, counts


def write_history(path: Path, rows: list) -> None:
    """Write history rows to CSV atomically (temp file + replace)."""
    tmp = path.with_suffix('.csv.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**r, 'ex_date': r['ex_date'].isoformat(),
                        'adjustment_factor': f"{r['adjustment_factor']:.6f}"})
    tmp.replace(path)


def load_history(path: Path | None = None) -> dict:
    """Load history.csv into {symbol: [(ex_date, combined_factor), ...]} sorted by ex_date.

    Factors of different action types on the same (symbol, ex_date) are multiplied.

    Raises:
        FileNotFoundError: history.csv missing (run ingestion.fetch_corporate_actions_history first).
    """
    path = path or (CORPORATE_ACTIONS_DIR / 'history.csv')
    by_key: dict = {}
    with path.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            key = (r['symbol'], date.fromisoformat(r['ex_date']))
            by_key[key] = by_key.get(key, 1.0) * float(r['adjustment_factor'])
    table: dict = {}
    for (symbol, ex_date), factor in sorted(by_key.items(), key=lambda kv: kv[0][1]):
        table.setdefault(symbol, []).append((ex_date, factor))
    return table


def cumulative_factor(table: dict, symbol: str, from_date: date, to_date: date) -> float:
    """Factor to DIVIDE a `from_date` price by to put it on `to_date`'s scale.

    Multiplies every action with from_date < ex_date <= to_date. 1.0 when there is none or from_date >= to_date.
    """
    if from_date >= to_date:
        return 1.0
    factor = 1.0
    for ex_date, f in table.get(symbol, ()):
        if from_date < ex_date <= to_date:
            factor *= f
    return factor


def adjust_price(table: dict, symbol: str, price: float, price_date: date, target_date: date) -> float:
    """Return `price` (dated `price_date`) on `target_date`'s scale."""
    return price / cumulative_factor(table, symbol, price_date, target_date)


def adjust_volume(table: dict, symbol: str, volume: float, price_date: date, target_date: date) -> float:
    """Return `volume` (dated `price_date`) on `target_date`'s share-count scale."""
    return volume * cumulative_factor(table, symbol, price_date, target_date)
