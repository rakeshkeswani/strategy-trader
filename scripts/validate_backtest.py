# -*- coding: utf-8 -*-
# scripts/validate_backtest.py
"""
ST-010 piece 5 -- acceptance checks for one backtest output folder (data/backtests/<run_id>/). Read-only.

1. REPEATABLE (--rerun): the same config run again gives byte-identical lots/orders/daily/tax files.
2. NO LOOKAHEAD (--rerun): raw prices after a cut-off are scrambled (3 cut-offs); every order and daily row up to the
   cut-off must be identical.
3. LIMITS: cash negative only as tax owed (Rakesh 2026-10-15, option b: a negative stretch starts on a tax day, is
   never below minus that tax, and has no buys; repaid from later sales); buys per week <= the weekly budget; no
   buys after a signal day with tier no_buys/halt; limits runs: at cost <= capital cap and <= per-stock cap at
   every buy, invested_cost <= cap every day.
4. LOTS COMPLETE: entry, quantity, stop (stop strategies); exit with a known reason or open at the end; one BUY order
   per lot matching it, at most one SELL matching its exit; no open lot held past its time exit.
5. FILLS POSSIBLE: every fill inside that day's low-high (after slippage); buys and open exits at the open, the -15%
   rule at the close, stops at the stop (not above the open), gap-downs at an open at or below the stop.
6. CHARGES + TAX: every order's charges recomputed from Zerodha's rates written out HERE (not backtest/costs.py);
   tax per financial year recomputed from the lots with the set-off rules written out here.
7. MONEY: cash rebuilt from orders and tax equals daily cash every day; equity = cash + holdings; since-start rupees
   (metrics) = final equity + tax - capital.
8. BENCHMARK: the run's days are exactly the benchmark's days in the period, closes equal nifty500.csv.
9. BIG MOVES (warning): a held stock moving more than +/-30% close to close in a day must be a known crash in
   config/ca_exceptions.csv; otherwise listed (e.g. a demerger, ST-019).

Writes LOG_DIR/validate_backtest_<run_id>_<date>.csv. Exit code 0 only when RESULT: PASS (warnings allowed).
Usage (repo root): python -m scripts.validate_backtest <run_id or folder> [--rerun]
"""

import argparse
import csv
import io
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.run import BACKTESTS_DIR, load_market, run_backtest
from core.config import BENCHMARK_DIR, LOG_DIR, REPO_ROOT

logger = logging.getLogger('validate_backtest')

# Written out independently of backtest/costs.py (zerodha.com/charges and incometaxindia.gov.in, ST-010 2026-10-14).
SLIP = 0.001
R_STT, R_STAMP, R_TXN, R_SEBI, R_GST, DP_FEE = 0.001, 0.00015, 0.0000307, 0.000001, 0.18, 15.34
STCG, LTCG = 0.208, 0.13
OPEN_EXITS = {'time_12m', 'stop_gap', 'profit_50'}
LATER_EXITS = {'stop', 'loss_15'}           # after the open: such a lot was still open when the day's buys happened
BIG_MOVE = 0.30
CUTOFF_FRACTIONS = (0.25, 0.5, 0.75)
TOL_RS = 0.01
TOL_PX = 1e-9


def _d(s: pd.Series) -> pd.Series:
    """CSV date strings (or NaN) -> datetime.date (or None)."""
    return pd.Series([x.date() if pd.notna(x) else None for x in pd.to_datetime(s)], index=s.index, dtype=object)


def _read(path: Path) -> pd.DataFrame:
    """read_csv with exact float round-trip (the lookahead check compares re-written CSV text)."""
    return pd.read_csv(path, float_precision='round_trip')


def load_run(folder: Path) -> dict:
    """Read a run folder."""
    cfg = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    lots = _read(folder / 'lots.csv')
    lots['entry_date'], lots['exit_date'] = _d(lots['entry_date']), _d(lots['exit_date'])
    lots['exit_reason'] = lots['exit_reason'].fillna('')
    orders = _read(folder / 'orders.csv')
    orders['date'] = _d(orders['date'])
    daily = _read(folder / 'daily.csv')
    daily['date'] = _d(daily['date'])
    tax = _read(folder / 'tax.csv')
    tax['date'] = _d(tax['date'])
    metrics = json.loads((folder / 'metrics.json').read_text(encoding='utf-8'))
    return {'cfg': cfg, 'lots': lots, 'orders': orders, 'daily': daily, 'tax': tax, 'metrics': metrics,
            'start': date.fromisoformat(cfg['start']), 'end': date.fromisoformat(cfg['end']),
            'name': cfg['strategy']['name'], 'faithful': cfg['limits'] is None}


def year_later(d: date) -> date:
    """Same calendar date one year later (29 Feb -> 28 Feb)."""
    return d.replace(year=d.year + 1, day=28) if (d.month, d.day) == (2, 29) else d.replace(year=d.year + 1)


# ---- 3 limits ----------------------------------------------------------------------------------------------------
def check_limits(r: dict, issues: list) -> dict:
    """Cash, weekly budget, tier, and (limits runs) capital and per-stock caps at every buy."""
    lots, orders, daily = r['lots'], r['orders'], r['daily']
    s, limits = r['cfg']['strategy'], r['cfg']['limits']
    c = {'cash_negative_not_tax': 0, 'weeks_over_budget': 0, 'buys_while_blocked': 0, 'cap_breaches': 0,
         'per_stock_breaches': 0, 'days_invested_over_cap': 0}
    tax_on = r['tax'].groupby('date')['tax'].sum().to_dict()
    buys = orders[orders['side'] == 'BUY']
    buy_days = set(buys['date'])
    owed, stretch_tax = 0, 0.0          # owed: days with tax owed (allowed); stretch_tax: tax that started the stretch
    for row in daily.itertuples():
        if row.cash >= -TOL_RS:
            stretch_tax = 0.0
            continue
        if stretch_tax == 0.0:
            stretch_tax = tax_on.get(row.date, 0.0)
        if stretch_tax > 0 and row.cash >= -stretch_tax - TOL_RS and row.date not in buy_days:
            owed += 1
        else:
            c['cash_negative_not_tax'] += 1
            issues.append(('limits', 'cash_negative_not_tax_owed', row.date, round(row.cash, 2)))
    c_info = {'days_tax_owed': owed}
    wk = buys.assign(wk=[d.isocalendar()[:2] for d in buys['date']]).groupby('wk')['value'].sum()
    for k, v in wk[wk > s['sizing']['weekly_budget'] + TOL_RS].items():
        c['weeks_over_budget'] += 1
        issues.append(('limits', 'week_over_budget', f'{k[0]}-W{k[1]:02d}', round(v, 2)))
    days = list(daily['date'])
    prev = {days[i]: days[i - 1] for i in range(1, len(days))}
    tier = dict(zip(daily['date'], daily['tier']))
    for d in sorted(set(buys['date'])):
        if tier.get(prev.get(d)) in ('no_buys', 'halt'):
            c['buys_while_blocked'] += 1
            issues.append(('limits', 'buy_while_blocked', d, tier.get(prev.get(d))))
    if limits:
        for row in daily[daily['invested_cost'] > limits['capital_cap'] + TOL_RS].itertuples():
            c['days_invested_over_cap'] += 1
            issues.append(('limits', 'invested_over_cap', row.date, round(row.invested_cost, 2)))
        ex = lots['exit_date']
        for d in sorted(set(buys['date'])):
            held = lots[(lots['entry_date'] <= d) & (ex.isna() | (ex.apply(lambda x: x is not None and x > d))
                                                     | ((ex == d) & lots['exit_reason'].isin(LATER_EXITS)))]
            total = held['buy_value'].sum()
            if total > limits['capital_cap'] + TOL_RS:
                c['cap_breaches'] += 1
                issues.append(('limits', 'cap_at_buy', d, round(total, 2)))
            per = held.groupby('series_id')['buy_value'].sum()
            for sid, v in per[per > limits['per_stock'] + TOL_RS].items():
                c['per_stock_breaches'] += 1
                issues.append(('limits', 'per_stock_at_buy', f'{d} {sid}', round(v, 2)))
    return {**c, **c_info}


# ---- 4 lots complete ---------------------------------------------------------------------------------------------
def check_lots(r: dict, market_days: dict, issues: list) -> dict:
    """Every lot whole and matching its orders; no lot held past its time exit while its stock traded."""
    lots, orders, end = r['lots'], r['orders'], r['end']
    lot_stop = r['cfg']['strategy']['exit']['mode'] == 'lot_stop'
    reasons = OPEN_EXITS | LATER_EXITS
    c = {'lots': len(lots), 'bad_lots': 0, 'order_mismatch': 0, 'missed_time_exit': 0}
    by_lot = {k: g for k, g in orders.groupby('lot_id')}
    for l in lots.itertuples():
        bad = []
        if not (l.entry_px > 0 and l.qty > 0 and l.raw_qty >= 1 and l.buy_value > 0):
            bad.append('entry')
        if lot_stop and not l.stop > 0:
            bad.append('stop')
        if l.exit_date is not None:
            if not (l.exit_date >= l.entry_date and l.exit_px > 0 and l.exit_reason in reasons):
                bad.append('exit')
        elif l.exit_reason or not np.isnan(l.exit_px):
            bad.append('open_lot_has_exit_fields')
        if bad:
            c['bad_lots'] += 1
            issues.append(('lots', 'bad_lot', l.lot_id, ','.join(bad)))
        g = by_lot.get(l.lot_id, orders.iloc[0:0])
        b, s = g[g['side'] == 'BUY'], g[g['side'] == 'SELL']
        ok = (len(b) == 1 and b['date'].iloc[0] == l.entry_date and abs(b['value'].iloc[0] - l.buy_value) <= TOL_RS
              and abs(b['ch_total'].iloc[0] - l.buy_charges) <= TOL_RS)
        if l.exit_date is None:
            ok = ok and len(s) == 0
        else:
            ok = ok and len(s) == 1 and s['date'].iloc[0] == l.exit_date and s['reason'].iloc[0] == l.exit_reason \
                and abs(s['value'].iloc[0] - l.sell_value) <= TOL_RS and abs(s['ch_total'].iloc[0] - l.sell_charges) <= TOL_RS
        if not ok:
            c['order_mismatch'] += 1
            issues.append(('lots', 'orders_do_not_match_lot', l.lot_id, l.symbol))
        due = year_later(l.entry_date)
        last = l.exit_date or end
        traded_after = [d for d in market_days.get(l.series_id, ()) if due < d <= last]
        if traded_after and (l.exit_date is None or l.exit_date > traded_after[0]):
            c['missed_time_exit'] += 1
            issues.append(('lots', 'held_past_time_exit', l.lot_id, f'{l.symbol} due after {due}, first day {traded_after[0]}'))
    return c


# ---- 5 fills -----------------------------------------------------------------------------------------------------
def check_fills(r: dict, market: pd.DataFrame, issues: list) -> dict:
    """Each fill inside the day's range and at the price its rule says."""
    o = r['orders'].merge(market[['series_id', 'trade_date', 'open', 'high', 'low', 'close']],
                          left_on=['series_id', 'date'], right_on=['series_id', 'trade_date'], how='left')
    o = o.merge(r['lots'][['lot_id', 'stop']], on='lot_id', how='left')
    c = {'orders': len(o), 'no_bar': 0, 'outside_range': 0, 'wrong_price': 0}
    for x in o.itertuples():
        if np.isnan(x.open):
            c['no_bar'] += 1
            issues.append(('fills', 'no_bar', x.date, x.symbol))
            continue
        raw = x.price / (1 + SLIP) if x.side == 'BUY' else x.price / (1 - SLIP)
        tol = TOL_PX * max(x.high, 1)
        if raw < x.low - tol or raw > x.high + tol:
            c['outside_range'] += 1
            issues.append(('fills', 'outside_low_high', f'{x.date} {x.symbol} {x.side} {x.reason}',
                           f'{raw:.4f} not in [{x.low:.4f}, {x.high:.4f}]'))
        if x.side == 'BUY' or x.reason in OPEN_EXITS:
            want = x.open
        elif x.reason == 'loss_15':
            want = x.close
        else:                                             # 'stop': at the stop, which the open was above
            want = x.stop if raw <= x.open + tol else np.nan
        ok = not np.isnan(want) and abs(raw - want) <= tol
        if x.reason == 'stop_gap':
            ok = ok and x.open <= x.stop + tol
        if not ok:
            c['wrong_price'] += 1
            issues.append(('fills', 'wrong_price', f'{x.date} {x.symbol} {x.side} {x.reason}', f'{raw:.4f} vs {want}'))
    return c


# ---- 6 charges + tax ---------------------------------------------------------------------------------------------
def order_charges(side: str, value: float, first_sale_of_day: bool) -> float:
    """Zerodha delivery charges for one order (rates in this file)."""
    txn, sebi = value * R_TXN, value * R_SEBI
    total = value * R_STT + txn + sebi + R_GST * (txn + sebi)
    if side == 'BUY':
        return total + value * R_STAMP
    return total + (DP_FEE if first_sale_of_day else 0.0)


def fy_tax_table(lots: pd.DataFrame, fys: list[int]) -> pd.DataFrame:
    """Tax per financial year from closed lots. Gains after charges except STT; long-term = held more than 12 months.

    Set-off (Income-tax Act ss. 70-74): this year's short-term loss against long-term gains; long-term losses only
    against long-term gains; carried long-term losses used first on long-term gains, carried short-term losses then on
    short-term and long-term gains.
    """
    c = lots[lots['exit_date'].notna()].copy()
    c['gain'] = (c['sell_value'] - (c['sell_charges'] - c['sell_stt'])) - (c['buy_value'] + (c['buy_charges'] - c['buy_stt']))
    c['lt'] = [x > year_later(e) for e, x in zip(c['entry_date'], c['exit_date'])]
    c['fy'] = [x.year if x.month >= 4 else x.year - 1 for x in c['exit_date']]
    st_cf = lt_cf = 0.0
    rows = []
    for fy in fys:
        g = c[c['fy'] == fy]
        st, lt = float(g.loc[~g['lt'], 'gain'].sum()), float(g.loc[g['lt'], 'gain'].sum())
        row = {'fy': fy, 'st_gain': st, 'lt_gain': lt}
        if st < 0:
            use = min(-st, max(lt, 0.0))
            lt -= use
            st_cf += -st - use
            st = 0.0
        if lt < 0:
            lt_cf += -lt
            lt = 0.0
        use = min(lt_cf, lt); lt -= use; lt_cf -= use
        use = min(st_cf, st); st -= use; st_cf -= use
        use = min(st_cf, lt); lt -= use; st_cf -= use
        row.update(tax=st * STCG + lt * LTCG, st_loss_cf=st_cf, lt_loss_cf=lt_cf)
        rows.append(row)
    return pd.DataFrame(rows)


def check_charges_tax(r: dict, issues: list) -> dict:
    """Every order's charges and every year's tax recomputed."""
    o = r['orders']
    c = {'orders': len(o), 'charge_mismatch': 0, 'charge_diff_max': 0.0, 'tax_years': 0, 'tax_mismatch': 0,
         'tax_total_engine': round(float(r['tax']['tax'].sum()), 2)}
    seen = set()
    for x in o.itertuples():
        first = False
        if x.side == 'SELL':
            first = (x.date, x.series_id) not in seen
            seen.add((x.date, x.series_id))
        diff = abs(order_charges(x.side, x.value, first) - x.ch_total)
        c['charge_diff_max'] = max(c['charge_diff_max'], round(diff, 6))
        if diff > 0.005:
            c['charge_mismatch'] += 1
            issues.append(('charges', 'mismatch', f'{x.date} {x.symbol} {x.side} lot {x.lot_id}', round(diff, 4)))
    mine = fy_tax_table(r['lots'], list(r['tax']['fy']))
    c['tax_years'] = len(mine)
    c['tax_total_recomputed'] = round(float(mine['tax'].sum()), 2)
    for a, b in zip(r['tax'].itertuples(), mine.itertuples()):
        if abs(a.st_gain - b.st_gain) > TOL_RS or abs(a.lt_gain - b.lt_gain) > TOL_RS or abs(a.tax - b.tax) > TOL_RS:
            c['tax_mismatch'] += 1
            issues.append(('tax', f'FY{a.fy}', f'engine st {a.st_gain:.2f} lt {a.lt_gain:.2f} tax {a.tax:.2f}',
                           f'recomputed st {b.st_gain:.2f} lt {b.lt_gain:.2f} tax {b.tax:.2f}'))
    return c


# ---- 7 money -----------------------------------------------------------------------------------------------------
def check_money(r: dict, capital: float, issues: list) -> dict:
    """Cash rebuilt from orders and tax; equity; since-start rupees."""
    o, daily, tax = r['orders'], r['daily'], r['tax']
    flow = np.where(o['side'] == 'BUY', -(o['value'] + o['ch_total']), o['value'] - o['ch_total'])
    by_day = pd.Series(flow, index=o['date']).groupby(level=0).sum()
    by_day = by_day.add(-tax.set_index('date')['tax'].groupby(level=0).sum(), fill_value=0)
    cash = capital + by_day.reindex(daily['date'], fill_value=0).cumsum().to_numpy()
    diff = np.abs(cash - daily['cash'].to_numpy())
    c = {'days': len(daily), 'cash_diff_max': round(float(diff.max()), 4), 'cash_mismatch_days': int((diff > 0.05).sum()),
         'equity_mismatch_days': int((np.abs(daily['cash'] + daily['holdings'] - daily['equity']) > TOL_RS).sum())}
    for d, a, b in zip(daily['date'][diff > 0.05][:20], cash[diff > 0.05][:20], daily['cash'][diff > 0.05][:20]):
        issues.append(('money', 'cash', d, f'rebuilt {a:.2f} vs daily {b:.2f}'))
    since = float(daily['equity'].iloc[-1]) + float(tax['tax'].sum()) - capital
    c['since_start_diff'] = round(abs(since - r['metrics'].get('since_start_pnl_rupees', np.nan)), 4)
    return c


# ---- 8 benchmark -------------------------------------------------------------------------------------------------
def check_benchmark(r: dict, issues: list) -> dict:
    """The run's days = the benchmark's days in the period; closes equal."""
    b = pd.read_csv(BENCHMARK_DIR / 'nifty500.csv')
    b['trade_date'] = _d(b['trade_date'])
    b = b[(b['trade_date'] >= r['start']) & (b['trade_date'] <= r['end'])]
    run_days, bench_days = set(r['daily']['date']), set(b['trade_date'])
    m = r['daily'].merge(b, left_on='date', right_on='trade_date', how='inner')
    c = {'days': len(run_days), 'only_in_run': len(run_days - bench_days), 'only_in_benchmark': len(bench_days - run_days),
         'close_mismatch': int((np.abs(m['bench_close'] - m['close']) > 0.005).sum()),
         'filled_days': int((b['source'] == 'ffill').sum())}
    for d in sorted(run_days ^ bench_days)[:20]:
        issues.append(('benchmark', 'day_not_in_both', d, 'run' if d in run_days else 'benchmark'))
    return c


# ---- 9 big moves -------------------------------------------------------------------------------------------------
def check_big_moves(r: dict, market: pd.DataFrame, issues: list) -> dict:
    """Held stocks' one-day moves beyond BIG_MOVE: known crash or listed (warning)."""
    exc = pd.read_csv(REPO_ROOT / 'config' / 'ca_exceptions.csv')
    known = {(s, date.fromisoformat(d)) for k, s, d in zip(exc['kind'], exc['symbol'], exc['date']) if k == 'drop'}
    lots = r['lots']
    m = market[market['series_id'].isin(set(lots['series_id']))].sort_values(['series_id', 'trade_date'])
    m = m.assign(move=m['close'] / m.groupby('series_id')['close'].shift(1) - 1)
    big = m[m['move'].abs() > BIG_MOVE]
    c = {'held_big_moves': 0, 'known_crashes': 0, 'unexplained': 0, 'lots_affected': 0}
    for x in big.itertuples():
        held = lots[(lots['series_id'] == x.series_id) & (lots['entry_date'] < x.trade_date)
                    & lots['exit_date'].apply(lambda e: e is None or e >= x.trade_date)]
        if held.empty:
            continue
        c['held_big_moves'] += 1
        c['lots_affected'] += len(held)
        if (x.symbol, x.trade_date) in known:
            c['known_crashes'] += 1
            issues.append(('big_move', 'known_crash', f'{x.trade_date} {x.symbol}', f'{x.move:+.1%}, {len(held)} lots'))
        else:
            c['unexplained'] += 1
            issues.append(('big_move', 'UNEXPLAINED', f'{x.trade_date} {x.symbol}', f'{x.move:+.1%}, {len(held)} lots'))
    return c


# ---- 1 + 2 re-runs -----------------------------------------------------------------------------------------------
def _csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def check_repeatable(r: dict, folder: Path, issues: list) -> dict:
    """Run the same config again; files must be identical."""
    again = run_backtest(r['name'], r['start'], r['end'], r['faithful'])
    frames = {'lots.csv': again['res'].lots, 'orders.csv': again['res'].orders, 'daily.csv': again['daily'],
              'tax.csv': again['res'].tax}
    c = {'files_different': 0}
    for name, df in frames.items():
        with (folder / name).open(encoding='utf-8', newline='') as f:
            saved = f.read()
        if _csv(df) != saved:
            c['files_different'] += 1
            issues.append(('repeatable', 'different', name, ''))
    return c


def scrambler(cutoff: date, seed: int):
    """panel_hook: multiply every raw price after `cutoff` by a random factor in [0.5, 1.5] per row."""
    def hook(panel: pd.DataFrame) -> pd.DataFrame:
        p = panel.copy()
        mask = (p['trade_date'] > cutoff).to_numpy()
        f = np.random.default_rng(seed).uniform(0.5, 1.5, int(mask.sum()))
        for col in ('open', 'high', 'low', 'close', 'prev_close'):
            p.loc[mask, col] = p.loc[mask, col].to_numpy() * f
        return p
    return hook


def check_no_lookahead(r: dict, issues: list) -> dict:
    """Scramble the future at each cut-off; the past must not change."""
    days = list(r['daily']['date'])
    o_cols = ['date', 'lot_id', 'side', 'series_id', 'price', 'value', 'reason', 'ch_total']
    d_cols = ['date', 'cash', 'holdings', 'equity', 'invested_cost', 'open_lots', 'tier']
    c = {'cutoffs': [], 'different': 0}
    for i, frac in enumerate(CUTOFF_FRACTIONS):
        cut = days[int(len(days) * frac)]
        c['cutoffs'].append(str(cut))
        s = run_backtest(r['name'], r['start'], r['end'], r['faithful'], panel_hook=scrambler(cut, 20261015 + i))
        a = r['orders'][r['orders']['date'] <= cut][o_cols].reset_index(drop=True)
        b = s['res'].orders[s['res'].orders['date'] <= cut][o_cols].reset_index(drop=True)
        da = r['daily'][r['daily']['date'] <= cut][d_cols].reset_index(drop=True)
        db = s['daily'][s['daily']['date'] <= cut][d_cols].reset_index(drop=True)
        same = len(a) == len(b) and len(da) == len(db) and _csv(a) == _csv(b) and _csv(da) == _csv(db)
        future_changed = _csv(r['orders'][o_cols]) != _csv(s['res'].orders[o_cols])
        if not same:
            c['different'] += 1
            issues.append(('lookahead', 'past_changed', cut, f'orders {len(a)} vs {len(b)}'))
        if not future_changed:
            issues.append(('lookahead', 'scramble_had_no_effect', cut, 'test is not exercising anything'))
            c['different'] += 1
    return c


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run', help='run_id under BACKTESTS_DIR, or a folder path')
    ap.add_argument('--rerun', action='store_true', help='also checks 1-2 (re-runs the backtest 4 times)')
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    folder = Path(args.run) if Path(args.run).is_dir() else BACKTESTS_DIR / args.run
    r = load_run(folder)
    capital = 100000.0
    issues: list = []
    failed, warnings = [], []
    market, _ = load_market(r['start'], r['end'])
    market_days = {sid: sorted(g) for sid, g in market.groupby('series_id')['trade_date']}

    if args.rerun:
        rep = check_repeatable(r, folder, issues)
        logger.info(f'1 REPEATABLE: {rep}')
        if rep['files_different']:
            failed.append('repeatable')
        look = check_no_lookahead(r, issues)
        logger.info(f'2 NO LOOKAHEAD: {look}')
        if look['different']:
            failed.append('lookahead')
    else:
        failed.append('checks 1-2 not run (--rerun)')
    lim = check_limits(r, issues)
    logger.info(f'3 LIMITS: {lim}')
    if any(v for k, v in lim.items() if k != 'days_tax_owed'):
        failed.append('limits')
    lc = check_lots(r, market_days, issues)
    logger.info(f'4 LOTS: {lc}')
    if lc['bad_lots'] or lc['order_mismatch'] or lc['missed_time_exit']:
        failed.append('lots')
    fl = check_fills(r, market, issues)
    logger.info(f'5 FILLS: {fl}')
    if fl['no_bar'] or fl['outside_range'] or fl['wrong_price']:
        failed.append('fills')
    ct = check_charges_tax(r, issues)
    logger.info(f'6 CHARGES + TAX: {ct}')
    if ct['charge_mismatch'] or ct['tax_mismatch']:
        failed.append('charges/tax')
    mo = check_money(r, capital, issues)
    logger.info(f'7 MONEY: {mo}')
    if mo['cash_mismatch_days'] or mo['equity_mismatch_days'] or not mo['since_start_diff'] <= 1:
        failed.append('money')
    bm = check_benchmark(r, issues)
    logger.info(f'8 BENCHMARK: {bm}')
    if bm['only_in_run'] or bm['only_in_benchmark'] or bm['close_mismatch']:
        failed.append('benchmark')
    bg = check_big_moves(r, market, issues)
    logger.info(f'9 BIG MOVES: {bg}')
    if bg['unexplained']:
        warnings.append(f"{bg['unexplained']} unexplained big moves in held stocks (ST-019)")

    run_id = folder.name
    out = LOG_DIR / f'validate_backtest_{run_id}_{date.today():%Y%m%d}.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['check', 'key', 'value1', 'value2'])
        w.writerows(issues)
    logger.info(f'{len(issues)} rows -> {out}')
    if warnings:
        logger.warning('WARNINGS: ' + '; '.join(warnings))
    logger.info('RESULT: ' + ('FAIL -- ' + '; '.join(failed) if failed else 'PASS'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
