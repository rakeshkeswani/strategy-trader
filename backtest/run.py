# -*- coding: utf-8 -*-
# backtest/run.py
"""
ST-010 -- run one strategy on real data and save the outputs to BACKTESTS_DIR/<run_id>/.

Loads the panel (core/panel.py), applies split/bonus adjustment (core/adjusted.py), adds indicators
(core/indicators.py + a 252-day return), takes the universe in force (core/universe.py) and the Nifty 500 benchmark
(data/benchmark/nifty500.csv), runs backtest/engine.py and writes:
  config.json (strategy, limits, period, data notes), lots.csv, orders.csv, daily.csv (with the benchmark), tax.csv,
  metrics.json (headline numbers; the full report card is ST-010 piece 4).
run_id = <strategy>_<limits|faithful>_<start>_<end>. Re-running the same arguments overwrites the same folder.

Usage (on rkneo50q, from the repo root):
  python -m backtest.run --strategy baseline_momentum --start 2014-10-01 --end 2023-12-31
  python -m backtest.run --strategy rakesh_top4 --faithful --start 2014-10-01 --end 2023-12-31
"""

import argparse
import json
import logging
import sys
import time
import tomllib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.engine import Backtest
from core.adjusted import actions_frame, adjust, series_factors
from core.config import BENCHMARK_DIR, LOG_DIR, REPO_ROOT, _dir_from_env
from core.corporate_actions import load_history
from core.indicators import add_indicators
from core.panel import read_panel
from core.universe import load_membership, members_on

logger = logging.getLogger('backtest.run')
BACKTESTS_DIR = _dir_from_env('BACKTESTS_DIR', REPO_ROOT / 'data' / 'backtests')
STRATEGY_DIR = REPO_ROOT / 'config' / 'strategies'
LIMITS = {'capital_cap': 100000, 'per_stock': 8000, 'loss_tiers': (0.10, 0.15, 0.20)}
LOOKBACK_DAYS = 420
PANEL_COLS = ['trade_date', 'series_id', 'symbol', 'open', 'high', 'low', 'close', 'prev_close', 'volume']


def load_market(start: date, end: date) -> tuple[pd.DataFrame, dict]:
    """Adjusted panel rows for [start - lookback, end] with ret_126, ret_252, sma_200, rsi_14; plus data notes."""
    panel = read_panel(start - timedelta(days=LOOKBACK_DAYS), end, columns=PANEL_COLS)
    factors, unmatched = series_factors(panel, actions_frame(load_history()))
    adj = add_indicators(adjust(panel, factors), ret_n=126, sma_n=200, rsi_n=14)
    adj['ret_252'] = adj['close'] / adj.groupby('series_id', sort=False)['close'].shift(252) - 1
    notes = {'panel_rows': len(panel), 'actions_matched': len(factors), 'actions_unmatched': len(unmatched),
             'unmatched': [f"{r.symbol} {r.ex_date}" for r in unmatched.itertuples()]}
    return adj, notes


def headline(daily: pd.DataFrame, capital: float) -> dict:
    """Headline numbers: final equity, CAGR, max drawdown, worst rolling 12-month change, vs the benchmark."""
    d = daily.copy()
    d['date'] = pd.to_datetime(d['date'])
    years = (d['date'].iloc[-1] - d['date'].iloc[0]).days / 365.25
    eq = d['equity']
    bench = d['bench_value']
    dd = (eq / eq.cummax() - 1).min()
    s = d.set_index('date')['equity']
    past = s.reindex(s.index - pd.Timedelta(days=365), method='ffill').values
    roll = (s.values - np.where(np.isnan(past), capital, past)) / capital
    out = {'start': str(d['date'].iloc[0].date()), 'end': str(d['date'].iloc[-1].date()), 'years': round(years, 2),
           'final_equity': round(float(eq.iloc[-1]), 2), 'cagr': round(float((eq.iloc[-1] / capital) ** (1 / years) - 1), 4),
           'max_drawdown': round(float(dd), 4), 'worst_12m_change_of_capital': round(float(roll.min()), 4),
           'bench_final': round(float(bench.iloc[-1]), 2),
           'bench_cagr': round(float((bench.iloc[-1] / capital) ** (1 / years) - 1), 4),
           'bench_max_drawdown': round(float((bench / bench.cummax() - 1).min()), 4),
           'tax_paid': round(float(d['tax_paid'].iloc[-1]), 2), 'charges_paid': round(float(d['charges_paid'].iloc[-1]), 2)}
    out['loss_first_pass'] = out['worst_12m_change_of_capital'] > -0.20
    return out


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--strategy', required=True)
    ap.add_argument('--start', type=date.fromisoformat, default=date(2014, 10, 1))
    ap.add_argument('--end', type=date.fromisoformat, default=date(2023, 12, 31))
    ap.add_argument('--faithful', action='store_true', help="no stratrad limits (only cash and the weekly budget)")
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    t0 = time.time()
    strategy = tomllib.loads((STRATEGY_DIR / f'{args.strategy}.toml').read_text(encoding='utf-8'))
    limits = None if args.faithful else LIMITS
    market, notes = load_market(args.start, args.end)
    logger.info(f'market: {notes["panel_rows"]:,} rows; actions matched {notes["actions_matched"]}, unmatched '
                f'{notes["actions_unmatched"]} {notes["unmatched"]} ({time.time() - t0:.0f}s)')
    membership = load_membership()
    res = Backtest(strategy, market, lambda d: set(members_on(membership, d)['series_id']),
                   args.start, args.end, limits).run()
    bench = pd.read_csv(BENCHMARK_DIR / 'nifty500.csv', parse_dates=['trade_date'])
    bench['trade_date'] = bench['trade_date'].dt.date
    daily = res.daily.merge(bench.rename(columns={'trade_date': 'date', 'close': 'bench_close'})[['date', 'bench_close']],
                            on='date', how='left')
    if daily['bench_close'].isna().any():
        logger.critical(f"benchmark missing on {int(daily['bench_close'].isna().sum())} days")
        return 1
    daily['bench_value'] = 100000 * daily['bench_close'] / daily['bench_close'].iloc[0]
    metrics = headline(daily, 100000)
    run_id = f"{args.strategy}_{'faithful' if args.faithful else 'limits'}_{args.start}_{args.end}"
    out = BACKTESTS_DIR / run_id
    if str(out).replace('\\', '/').startswith('//'):
        logger.critical(f'Refusing to write to a network share: {out}')
        return 2
    out.mkdir(parents=True, exist_ok=True)
    (out / 'config.json').write_text(json.dumps({'strategy': strategy, 'limits': limits, 'start': str(args.start),
                                                 'end': str(args.end), 'data': notes}, indent=1, default=str),
                                     encoding='utf-8')
    res.lots.to_csv(out / 'lots.csv', index=False)
    res.orders.to_csv(out / 'orders.csv', index=False)
    daily.to_csv(out / 'daily.csv', index=False)
    res.tax.to_csv(out / 'tax.csv', index=False)
    (out / 'metrics.json').write_text(json.dumps(metrics, indent=1), encoding='utf-8')
    logger.info(f'METRICS: {metrics}')
    logger.info(f'lots {len(res.lots)}, orders {len(res.orders)}, open at end {res.notes["open_lots_at_end"]} -> {out} '
                f'({time.time() - t0:.0f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
