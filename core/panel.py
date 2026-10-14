# -*- coding: utf-8 -*-
# core/panel.py
"""
ST-004 -- the price panel: every equity x every trading day in one Parquet table (docs/DATA_MODEL.md).

Layout: PANEL_DIR/equity_daily/year=YYYY/part-0.parquet (one file per calendar year). Prices are RAW; split/bonus
adjustment is applied at read time (core.corporate_actions), so a corrected factor never needs a rebuild.

Identity columns:
  company_key -- the company's symbol today (core.securities.key_on), constant across renames.
  series_id   -- company_key@<first trade_date of the series>. A NEW series starts when the company has no close for
                 more than SERIES_GAP_DAYS calendar days AND its ISIN changed across that gap (post-insolvency
                 relistings: INDOSOLAR, SPENTEX, NTL, EASTSILK -- docs/DATA_SOURCES.md). A gap alone (a suspension)
                 or an ISIN change alone (a split) keeps the series.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.config import PANEL_DIR

SERIES_GAP_DAYS = 30
TABLE = 'equity_daily'
PRICE_FIELDS = ['open', 'high', 'low', 'close', 'prev_close']
COLUMNS = ['trade_date', 'series_id', 'company_key', 'symbol', 'isin', 'series',
           *PRICE_FIELDS, 'volume', 'traded_value']
SCHEMA = pa.schema([
    ('trade_date', pa.date32()), ('series_id', pa.string()), ('company_key', pa.string()),
    ('symbol', pa.string()), ('isin', pa.string()), ('series', pa.string()),
    *[(f, pa.float64()) for f in PRICE_FIELDS],
    ('volume', pa.int64()), ('traded_value', pa.float64()),
])


def table_dir(root: Path | None = None) -> Path:
    """Return the directory holding the year partitions."""
    return (root or PANEL_DIR) / TABLE


def partition_path(year: int, root: Path | None = None) -> Path:
    """Return the Parquet file for one calendar year."""
    return table_dir(root) / f'year={year}' / 'part-0.parquet'


def day_frame(records: dict, trade_date: date, key_for) -> pd.DataFrame:
    """Turn one day's {symbol: record} (already filtered to equities) into panel rows without series_id.

    `key_for(symbol, trade_date)` returns the company key (core.securities.Securities.key_on).
    """
    rows = []
    for symbol, r in records.items():
        rows.append({'trade_date': trade_date, 'company_key': key_for(symbol, trade_date), 'symbol': symbol,
                     'isin': r.get('isin'), 'series': r.get('series'),
                     **{f: r.get(f) for f in PRICE_FIELDS},
                     'volume': r.get('volume'), 'traded_value': r.get('traded_value')})
    return pd.DataFrame(rows)


def assign_series(new_rows: pd.DataFrame, context: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return `new_rows` with series_id filled.

    `context` holds, per company_key, the last row already in the panel (trade_date, isin, series_id), so an
    incremental append continues each company's current series. Rows must not overlap the context dates.
    """
    df = new_rows.copy()
    df['_new'] = True
    if context is not None and len(context):
        ctx = context[['company_key', 'trade_date', 'isin', 'series_id']].copy()
        ctx['_new'] = False
        df = pd.concat([ctx, df], ignore_index=True)
    df = df.sort_values(['company_key', 'trade_date'], kind='stable').reset_index(drop=True)
    prev_date = df.groupby('company_key')['trade_date'].shift()
    prev_isin = df.groupby('company_key')['isin'].shift()
    gap_days = (pd.to_datetime(df['trade_date']) - pd.to_datetime(prev_date)).dt.days
    starts = prev_date.isna() | ((gap_days > SERIES_GAP_DAYS) & (df['isin'] != prev_isin))
    if 'series_id' not in df:
        df['series_id'] = None
    # a context row keeps its existing id; a new row starting a series gets key@date
    fresh = starts & df['_new']
    df.loc[fresh, 'series_id'] = df.loc[fresh, 'company_key'] + '@' + pd.to_datetime(
        df.loc[fresh, 'trade_date']).dt.strftime('%Y-%m-%d')
    df['series_id'] = df.groupby('company_key')['series_id'].ffill()
    return df[df['_new']].drop(columns='_new')[COLUMNS].reset_index(drop=True)


def write_year(df: pd.DataFrame, year: int, root: Path | None = None) -> Path:
    """Write one year's rows (sorted by trade_date, series_id) atomically; return the file path."""
    path = partition_path(year, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.sort_values(['trade_date', 'series_id'], kind='stable').reset_index(drop=True)
    table = pa.Table.from_pandas(out[COLUMNS], schema=SCHEMA, preserve_index=False)
    tmp = path.with_suffix('.tmp')
    pq.write_table(table, tmp, compression='snappy')
    tmp.replace(path)
    return path


def read_panel(start: date | None = None, end: date | None = None, columns: list[str] | None = None,
               root: Path | None = None) -> pd.DataFrame:
    """Read the panel (all years, or [start, end]) into a DataFrame; trade_date comes back as datetime.date."""
    tdir = table_dir(root)
    if not tdir.exists():
        return pd.DataFrame(columns=columns or COLUMNS)
    files = sorted(tdir.glob('year=*/part-0.parquet'))
    if start or end:
        files = [f for f in files if (start is None or int(f.parent.name[5:]) >= start.year)
                 and (end is None or int(f.parent.name[5:]) <= end.year)]
    if not files:
        return pd.DataFrame(columns=columns or COLUMNS)
    df = pd.concat([pq.read_table(f, columns=columns).to_pandas(types_mapper=None) for f in files],
                   ignore_index=True)
    if 'trade_date' in df and (start or end):
        if start:
            df = df[df['trade_date'] >= start]
        if end:
            df = df[df['trade_date'] <= end]
    return df.reset_index(drop=True)


def last_rows(root: Path | None = None) -> pd.DataFrame:
    """Return the last panel row per company_key (trade_date, isin, series_id) -- the context for appends."""
    df = read_panel(columns=['company_key', 'trade_date', 'isin', 'series_id'], root=root)
    if df.empty:
        return df
    return df.sort_values('trade_date').groupby('company_key', as_index=False).tail(1).reset_index(drop=True)
