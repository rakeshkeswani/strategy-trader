# -*- coding: utf-8 -*-
# scripts/relocate_udiff_gap.py
"""
HISTORICAL -- DO NOT RE-RUN. Ran once on 2026-10-08. Its DEST was later moved to
/home/rakeshbk/strategy-trader/data/bhavcopy_udiff (docs/CONFIG.md); kept as a record.

ST-002 one-off (2026-10-08): undo the UDiFF backfill that was run into MyInvestIQ's archive.

On 2026-10-08 MyInvestIQ's own fetcher was run with
  --backfill-from 2024-01-01 --backfill-to 2025-08-27
which put ~400 days of NSE+BSE UDiFF files into myinvestiq/data/bhavcopy/. That changes
MyInvestIQ's behaviour (its Sunday ensure_price_history() would start writing raw
2024-2025 rows into stock_price_history), so the files belong to strategy-trader instead.

This script:
  1. selects manifest rows with date in [2024-01-03, 2025-08-27], fetched_at on 2026-10-08,
     excluding the 5 pre-existing probe dates (those rows were not touched by the run);
  2. backs up MyInvestIQ's manifest.csv (manifest.csv.bak_<timestamp>);
  3. moves the selected files to <dest>/ and writes the selected rows to <dest>/manifest.csv;
  4. rewrites MyInvestIQ's manifest.csv without the selected rows (same column order).

Default is a DRY RUN that only prints counts. Pass --go to do it. Run on rkneo50q with
MyInvestIQ's jobs idle (not during the 06:00 or 18:00 runs).

Usage:
  python -m scripts.relocate_udiff_gap            # dry run
  python -m scripts.relocate_udiff_gap --go
"""

import argparse
import csv
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

SRC = Path('/home/rakeshbk/myinvestiq/data/bhavcopy')
DEST = Path('/home/rakeshbk/myinvestiq/data/strategy_trader/bhavcopy_udiff')
RANGE_LO, RANGE_HI = date(2024, 1, 3), date(2025, 8, 27)
RUN_DAY = '2026-10-08'
PROBE_DATES = {'2024-01-01', '2024-01-02', '2024-03-01', '2024-05-02', '2024-06-28'}


def select(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split manifest rows into (move, keep) per the rules in the module docstring."""
    move, keep = [], []
    for r in rows:
        d = date.fromisoformat(r['date'])
        if (RANGE_LO <= d <= RANGE_HI and r['date'] not in PROBE_DATES
                and (r.get('fetched_at') or '').startswith(RUN_DAY)):
            move.append(r)
        else:
            keep.append(r)
    return move, keep


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--go', action='store_true', help='actually move files and rewrite the manifest')
    args = ap.parse_args()

    manifest = SRC / 'manifest.csv'
    with manifest.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    move, keep = select(rows)

    files = [r['filename'] for r in move if r.get('filename')]
    present = [n for n in files if (SRC / n).exists()]
    by_outcome: dict = {}
    for r in move:
        key = f"{r.get('exchange', 'NSE')}:{r['outcome']}"
        by_outcome[key] = by_outcome.get(key, 0) + 1
    print(f'manifest rows: {len(rows)} total, {len(move)} to move, {len(keep)} to keep')
    print(f'moved rows by exchange:outcome: {dict(sorted(by_outcome.items()))}')
    print(f'files referenced: {len(files)}, present on disk: {len(present)}')
    print(f'date span of moved rows: {min(r["date"] for r in move) if move else "-"} .. '
          f'{max(r["date"] for r in move) if move else "-"}')
    if not args.go:
        print('DRY RUN -- nothing changed. Re-run with --go.')
        return 0

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = SRC / f'manifest.csv.bak_{stamp}'
    shutil.copy2(manifest, backup)
    print(f'backup: {backup}')

    DEST.mkdir(parents=True, exist_ok=True)
    for name in present:
        shutil.move(str(SRC / name), str(DEST / name))
    with (DEST / 'manifest.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(move, key=lambda r: (r['date'], r.get('exchange', ''))))

    tmp = manifest.with_suffix('.csv.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(keep)
    tmp.replace(manifest)
    print(f'moved {len(present)} files to {DEST}; MyInvestIQ manifest now {len(keep)} rows')
    return 0


if __name__ == '__main__':
    sys.exit(main())
