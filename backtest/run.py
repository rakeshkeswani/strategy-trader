# -*- coding: utf-8 -*-
# backtest/run.py
"""
ST-010 -- run one strategy on real data and save the outputs to BACKTESTS_DIR/<run_id>/.

Loads the panel (core/panel.py), applies split/bonus adjustment (core/adjusted.py), adds indicators
(core/indicators.py + a 252-day return), takes the universe in force (core/universe.py) and the Nifty 500 benchmark
(data/benchmark/nifty500.csv), runs backtest/engine.py and writes:
  config.json (strategy, limits, period, data notes), lots.csv, orders.csv, daily.csv (with the benchmark), tax.csv,
  metrics.json (headline numbers incl. Test 1 = worst rolling 12-month rupee loss / the strategy's stake; card: piece 4).
  lots.csv carries pnl and pnl_pct per lot (closed at the sale, open at the last close).
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
from core.demergers import load_demergers
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


def actions_in_window(actions: pd.DataFrame, lo: date, hi: date) -> tuple[pd.DataFrame, int]:
    """Actions with lo <= ex_date <= hi (the loaded price window) and the number outside it (skipped, not 'unmatched')."""
    ed = pd.to_datetime(actions['ex_date']).dt.date
    inside = (ed >= lo) & (ed <= hi)
    return actions[inside].reset_index(drop=True), int((~inside).sum())


def load_market(start: date, end: date, panel_hook=None) -> tuple[pd.DataFrame, dict]:
    """Adjusted panel rows for [start - lookback, end] with ret_126, ret_252, sma_200, rsi_14; plus data notes.

    Only actions dated inside the loaded window are matched (earlier/later ones cannot affect these prices' ratios);
    'unmatched' therefore lists real gaps only, not actions after the run's end.
    `panel_hook(raw_panel) -> raw_panel` lets the validator change raw prices before adjustment (lookahead test).
    """
    lo = start - timedelta(days=LOOKBACK_DAYS)
    panel = read_panel(lo, end, columns=PANEL_COLS)
    if panel_hook is not None:
        panel = panel_hook(panel)
    splits = actions_frame(load_history()).assign(kind='split')
    actions, outside = actions_in_window(pd.concat([splits, load_demergers()], ignore_index=True), lo, end)
    factors, unmatched = series_factors(panel, actions)
    adj = add_indicators(adjust(panel, factors), ret_n=126, sma_n=200, rsi_n=14)
    adj['ret_252'] = adj['close'] / adj.groupby('series_id', sort=False)['close'].shift(252) - 1
    notes = {'panel_rows': len(panel), 'actions_window': f'{lo}..{end}', 'actions_outside_window': outside,
             'actions_matched': len(factors), 'demergers_applied': int((actions['kind'] == 'demerger').sum()),
             'actions_unmatched': len(unmatched),
             'unmatched': [f"{r.symbol} {r.ex_date}" for r in unmatched.itertuples()]}
    return adj, notes


def lot_pnl(lots: pd.DataFrame, last_close: dict) -> pd.DataFrame:
    """Level (a): each lot's gain/loss after charges / its buy value. Closed lots at the sale; open lots at the last
    close (`last_close`: series_id -> adjusted close on the run's last day; sell charges not yet paid)."""
    l = lots.copy()
    closed = l['exit_date'].notna()
    mark = l['qty'] * l['series_id'].map(last_close)
    value = np.where(closed, l['sell_value'] - l['sell_charges'], mark)
    l['pnl'] = value - l['buy_value'] - l['buy_charges']
    l['pnl_pct'] = l['pnl'] / l['buy_value']
    return l


def pnl_at_cost(daily: pd.DataFrame, lots: pd.DataFrame, window_days: int | None = 365) -> pd.DataFrame:
    """Level (b) per day, in rupees: gain/loss of open lots + of lots sold in the window, after charges.

    Open lot on day d: entry_date <= d and not yet sold at d's mark (exit_date > d or open). Open lots are valued at
    the engine's daily mark (`holdings`); sold lots at sale value. `window_days=None` = since start. Tax payments are
    not part of it (they are not market losses). Returns date, pnl, bought (total buy value of the lots counted).
    `bought` is NOT a denominator for Test 1: money reused lot after lot is counted again each time (2026-10-15: the
    baseline's worst year showed Rs -16,924 on Rs 4.9 L 'bought' = -3.5% while it never had more than Rs 53k in);
    Test 1 divides by the strategy's stake instead (headline()).
    """
    days = pd.to_datetime(daily['date']).values.astype('datetime64[D]')[:, None]
    entry = pd.to_datetime(lots['entry_date']).values.astype('datetime64[D]')[None, :]
    ex = pd.to_datetime(lots['exit_date']).values.astype('datetime64[D]')[None, :]
    sold = ~np.isnat(ex)
    is_open = (entry <= days) & (~sold | (ex > days))
    in_win = sold & (ex <= days)
    if window_days is not None:
        in_win &= ex > days - np.timedelta64(window_days, 'D')
    bv = lots['buy_value'].to_numpy()
    bc = lots['buy_charges'].to_numpy()
    sold_pnl = np.nan_to_num((lots['sell_value'] - lots['sell_charges']).to_numpy() - bv - bc)
    open_cost = is_open @ bv
    if not np.allclose(open_cost, daily['invested_cost'].to_numpy(), atol=0.01):
        raise ValueError('open lots from lots.csv do not match the engine\'s invested_cost')
    pnl = daily['holdings'].to_numpy() - open_cost - is_open @ bc + in_win @ sold_pnl
    return pd.DataFrame({'date': daily['date'].to_numpy(), 'pnl': pnl, 'bought': open_cost + in_win @ bv})


def worst_12m_return(values: pd.Series, dates: pd.Series, capital: float) -> tuple[float, str]:
    """Worst change vs the value 365 days earlier (first year: vs the starting capital); and the day it ends."""
    s = pd.Series(values.to_numpy(), index=pd.to_datetime(dates))
    past = s.reindex(s.index - pd.Timedelta(days=365), method='ffill').to_numpy()
    r = s.to_numpy() / np.where(np.isnan(past), capital, past) - 1
    i = int(np.argmin(r))
    return round(float(r[i]), 4), str(s.index[i].date())


def headline(daily: pd.DataFrame, capital: float, lots: pd.DataFrame | None = None,
             last_close: dict | None = None) -> dict:
    """Headline numbers: final equity, CAGR, max drawdown, the Test 1 loss measure, lots, vs the benchmark.

    Test 1 (Rakesh, 2026-10-15): the worst rolling 12-month rupee gain/loss at cost (level b, pnl_at_cost) divided
    by the strategy's stake (`capital`: Rs 1 L now; its own cap once a second strategy is live) must be better than
    -20%. `worst_12m_return` (vs the value 12 months earlier) is shown for both the strategy and the Nifty 500, for a
    like-for-like risk comparison. `worst_12m_change_of_capital` (equity incl. tax payments, vs Rs 1 L) for reference.
    """
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
    out['worst_12m_return'], out['worst_12m_return_end'] = worst_12m_return(eq, d['date'], capital)
    out['bench_worst_12m_return'], out['bench_worst_12m_return_end'] = worst_12m_return(bench, d['date'], capital)
    if lots is None or lots.empty:
        out['loss_first_pass'] = None
        return out
    roll_b = pnl_at_cost(daily, lots, 365)
    since = pnl_at_cost(daily, lots, None)
    i = int(np.argmin(roll_b['pnl'].to_numpy()))
    out['stake'] = capital
    out['worst_12m_pnl_rupees'] = round(float(roll_b['pnl'].iloc[i]), 2)
    out['worst_12m_pnl_date'] = str(pd.Timestamp(roll_b['date'].iloc[i]).date())
    out['worst_12m_of_stake'] = round(float(roll_b['pnl'].iloc[i]) / capital, 4)
    out['since_start_pnl_rupees'] = round(float(since['pnl'].iloc[-1]), 2)
    out['since_start_of_stake'] = round(float(since['pnl'].iloc[-1]) / capital, 4)
    lp = lot_pnl(lots, last_close or {})
    out['lots'] = int(len(lp))
    out['lots_open_at_end'] = int(lp['exit_date'].isna().sum())
    out['lot_hit_rate'] = round(float((lp['pnl'] > 0).mean()), 4)
    out['worst_lot_pct'] = round(float(lp['pnl_pct'].min()), 4)
    out['best_lot_pct'] = round(float(lp['pnl_pct'].max()), 4)
    out['lots_below_minus_15pct'] = int((lp['pnl_pct'] <= -0.15).sum())
    out['loss_first_pass'] = out['worst_12m_of_stake'] > -0.20
    return out


def run_id_of(strategy_name: str, faithful: bool, start: date, end: date) -> str:
    """Output folder name: <strategy>_<limits|faithful>_<start>_<end>."""
    return f"{strategy_name}_{'faithful' if faithful else 'limits'}_{start}_{end}"


def run_backtest(strategy_name: str, start: date, end: date, faithful: bool, panel_hook=None) -> dict:
    """Load data, run one strategy, add the benchmark and headline numbers. No files written.

    Returns strategy, limits, notes, market, res (engine Result; res.lots with per-lot pnl), daily (with benchmark),
    metrics. Raises ValueError when the benchmark misses a trading day.
    """
    t0 = time.time()
    strategy = tomllib.loads((STRATEGY_DIR / f'{strategy_name}.toml').read_text(encoding='utf-8'))
    limits = None if faithful else LIMITS
    market, notes = load_market(start, end, panel_hook)
    logger.info(f'market: {notes["panel_rows"]:,} rows; actions matched {notes["actions_matched"]}, unmatched '
                f'{notes["actions_unmatched"]} {notes["unmatched"]} ({time.time() - t0:.0f}s)')
    membership = load_membership()
    res = Backtest(strategy, market, lambda d: set(members_on(membership, d)['series_id']), start, end, limits).run()
    bench = pd.read_csv(BENCHMARK_DIR / 'nifty500.csv', parse_dates=['trade_date'])
    bench['trade_date'] = bench['trade_date'].dt.date
    daily = res.daily.merge(bench.rename(columns={'trade_date': 'date', 'close': 'bench_close'})[['date', 'bench_close']],
                            on='date', how='left')
    if daily['bench_close'].isna().any():
        raise ValueError(f"benchmark missing on {int(daily['bench_close'].isna().sum())} days")
    daily['bench_value'] = 100000 * daily['bench_close'] / daily['bench_close'].iloc[0]
    last = market[market['trade_date'] <= end].sort_values('trade_date').groupby('series_id')['close'].last()
    metrics = headline(daily, 100000, res.lots, last.to_dict())
    res.lots = lot_pnl(res.lots, last.to_dict())
    return {'strategy': strategy, 'limits': limits, 'notes': notes, 'market': market, 'res': res, 'daily': daily,
            'metrics': metrics}


def write_outputs(out: Path, r: dict, start: date, end: date) -> None:
    """Write config.json, lots.csv, orders.csv, daily.csv, tax.csv, metrics.json to `out`."""
    out.mkdir(parents=True, exist_ok=True)
    (out / 'config.json').write_text(json.dumps({'strategy': r['strategy'], 'limits': r['limits'], 'start': str(start),
                                                 'end': str(end), 'data': r['notes']}, indent=1, default=str),
                                     encoding='utf-8')
    r['res'].lots.to_csv(out / 'lots.csv', index=False)
    r['res'].orders.to_csv(out / 'orders.csv', index=False)
    r['daily'].to_csv(out / 'daily.csv', index=False)
    r['res'].tax.to_csv(out / 'tax.csv', index=False)
    (out / 'metrics.json').write_text(json.dumps(r['metrics'], indent=1), encoding='utf-8')


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
    out = BACKTESTS_DIR / run_id_of(args.strategy, args.faithful, args.start, args.end)
    if str(out).replace('\\', '/').startswith('//'):
        logger.critical(f'Refusing to write to a network share: {out}')
        return 2
    try:
        r = run_backtest(args.strategy, args.start, args.end, args.faithful)
    except ValueError as e:
        logger.critical(str(e))
        return 1
    write_outputs(out, r, args.start, args.end)
    res = r['res']
    logger.info(f'METRICS: {r["metrics"]}')
    logger.info(f'lots {len(res.lots)}, orders {len(res.orders)}, open at end {res.notes["open_lots_at_end"]} -> {out} '
                f'({time.time() - t0:.0f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
