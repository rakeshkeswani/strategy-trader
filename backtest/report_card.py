# -*- coding: utf-8 -*-
# backtest/report_card.py
"""
ST-010 piece 4 -- a plain-language report card per backtest run (layout approved by Rakesh 2026-10-15).

Sections: 1 verdict (Test 1, Test 2, checks); 2 in plain words; 3 year by year (financial years); 4 consistency;
5 how sure (block bootstrap of the lead); 6 risk side by side with the Nifty 500; 7 how it trades; 8 costs and tax;
9 data notes. With several runs, also a side-by-side comparison page.

Reads a run folder (data/backtests/<run_id>/) and the latest validator summary (LOG_DIR/validate_backtest_<run_id>_*.json).
Writes <run folder>/card.md; with 2+ runs also BACKTESTS_DIR/compare_<start>_<end>.md.
Usage (repo root): python -m backtest.report_card RUN_ID [RUN_ID ...]
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.run import BACKTESTS_DIR
from core.config import LOG_DIR

logger = logging.getLogger('report_card')
CAPITAL = 100000.0
TEST1_LIMIT = -0.20
BOOT_N = 10000
BOOT_BLOCK = 6          # months; keeps good and bad stretches together
BOOT_SEED = 20261015
HELD_OUT = '2024-26 held-out run: not run yet (waits for ST-012: split/bonus history after 2025-08-25).'


# ---- formatting --------------------------------------------------------------------------------------------------
def rs(x: float) -> str:
    """Indian grouping: Rs 1,19,928 / -Rs 16,924."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 'n/a'
    n = int(round(abs(x)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ','.join(groups) + ',' + tail
    return ('-' if x < 0 and n else '') + 'Rs ' + s


def lakh(x: float) -> str:
    """Rs 1.20 L."""
    return f'Rs {x / 1e5:.2f} L'


def pct(x: float, signed: bool = True) -> str:
    """-16.9% / 12.8%."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 'n/a'
    return f'{x:+.1%}' if signed else f'{x:.1%}'


def table(header: list, rows: list) -> str:
    """Markdown table."""
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


# ---- inputs ------------------------------------------------------------------------------------------------------
def load(folder: Path) -> dict:
    """Run folder + latest validator summary."""
    cfg = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    daily = pd.read_csv(folder / 'daily.csv', parse_dates=['date'])
    lots = pd.read_csv(folder / 'lots.csv', parse_dates=['entry_date', 'exit_date'])
    orders = pd.read_csv(folder / 'orders.csv', parse_dates=['date'])
    tax = pd.read_csv(folder / 'tax.csv', parse_dates=['date'])
    metrics = json.loads((folder / 'metrics.json').read_text(encoding='utf-8'))
    found = sorted(LOG_DIR.glob(f'validate_backtest_{folder.name}_*.json'))
    val = json.loads(found[-1].read_text(encoding='utf-8')) if found else None
    return {'folder': folder, 'run_id': folder.name, 'cfg': cfg, 'daily': daily, 'lots': lots, 'orders': orders,
            'tax': tax, 'metrics': metrics, 'val': val, 'faithful': cfg['limits'] is None,
            'name': cfg['strategy']['name']}


def label(r: dict) -> str:
    """'rakesh_top4, within limits'."""
    return f"{r['name']}, {'faithful (no stratrad limits)' if r['faithful'] else 'within limits'}"


# ---- numbers -----------------------------------------------------------------------------------------------------
def fy_of(d: pd.Timestamp) -> int:
    """Financial year starting April: FY 2019 = Apr 2019 - Mar 2020."""
    return d.year if d.month >= 4 else d.year - 1


def fy_table(daily: pd.DataFrame, orders: pd.DataFrame, tax: pd.DataFrame, lots: pd.DataFrame) -> pd.DataFrame:
    """Per financial year: strategy and Nifty returns (value at year end / value before it), gain in rupees before
    tax (change in value + tax paid that year), charges, tax, lots bought and sold. First/last years may be partial."""
    d = daily.assign(fy=daily['date'].map(fy_of))
    exit_fy = lots['exit_date'].map(lambda x: fy_of(x) if pd.notna(x) else -1)
    rows = []
    prev_eq, prev_b = CAPITAL, CAPITAL
    for fy, g in d.groupby('fy'):
        eq, b = float(g['equity'].iloc[-1]), float(g['bench_value'].iloc[-1])
        in_fy = lambda s: s.map(fy_of) == fy
        t = float(tax.loc[in_fy(tax['date']), 'tax'].sum())
        partial = g['date'].iloc[0] > pd.Timestamp(fy, 4, 7) or g['date'].iloc[-1] < pd.Timestamp(fy + 1, 3, 24)
        rows.append({'fy': fy, 'label': f"FY{fy % 100:02d}-{(fy + 1) % 100:02d}" + (' (part)' if partial else ''),
                     'from': g['date'].iloc[0].date(), 'to': g['date'].iloc[-1].date(), 'partial': partial,
                     'ret': eq / prev_eq - 1, 'bench': b / prev_b - 1, 'gain_rs': eq - prev_eq + t,
                     'charges': float(orders.loc[in_fy(orders['date']), 'ch_total'].sum()), 'tax': t,
                     'bought': int(in_fy(lots['entry_date']).sum()),
                     'sold': int((exit_fy == fy).sum())})
        prev_eq, prev_b = eq, b
    t = pd.DataFrame(rows)
    t['lead'] = t['ret'] - t['bench']
    return t


def rolling_ahead(daily: pd.DataFrame) -> tuple[float, int]:
    """Share of rolling 12-month windows (one ending each trading day, a full year after the start) where the
    strategy's return beat the Nifty's; and how many windows."""
    s = daily.set_index('date')[['equity', 'bench_value']]
    past = s.reindex(s.index - pd.Timedelta(days=365), method='ffill')
    ok = (s.index - pd.Timedelta(days=365)) >= s.index[0]
    a = s['equity'].to_numpy()[ok] / past['equity'].to_numpy()[ok]
    b = s['bench_value'].to_numpy()[ok] / past['bench_value'].to_numpy()[ok]
    return (float((a > b).mean()) if ok.any() else float('nan')), int(ok.sum())


def cagr(v0: float, v1: float, years: float) -> float:
    """Compound annual growth."""
    return (v1 / v0) ** (1 / years) - 1


def monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Month-end values (last trading day), starting from the first day."""
    s = daily.set_index('date')[['equity', 'bench_value']]
    m = s.groupby(s.index.to_period('M')).last()
    return pd.concat([s.iloc[[0]].set_axis([m.index[0] - 1]), m])


def bootstrap_lead(daily: pd.DataFrame, n: int = BOOT_N, block: int = BOOT_BLOCK, seed: int = BOOT_SEED) -> dict:
    """Circular block bootstrap of paired monthly returns -> 5th/50th/95th percentile of the annual lead
    (strategy CAGR minus Nifty CAGR), and the share of resamples where the strategy is ahead."""
    m = monthly(daily)
    rs_, rb = m['equity'].pct_change().dropna().to_numpy(), m['bench_value'].pct_change().dropna().to_numpy()
    k = len(rs_)
    rng = np.random.default_rng(seed)
    nb = -(-k // block)
    starts = rng.integers(0, k, size=(n, nb))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % k).reshape(n, -1)[:, :k]
    gs = np.prod(1 + rs_[idx], axis=1) ** (12 / k) - 1
    gb = np.prod(1 + rb[idx], axis=1) ** (12 / k) - 1
    lead = gs - gb
    return {'p5': float(np.percentile(lead, 5)), 'p50': float(np.percentile(lead, 50)),
            'p95': float(np.percentile(lead, 95)), 'share_ahead': float((lead > 0).mean()), 'months': k}


def underwater(values: pd.Series, dates: pd.Series) -> tuple[float, str, str]:
    """Longest stretch below a previous peak, in months; from peak date to recovery (or 'not recovered')."""
    v, d = values.to_numpy(), pd.to_datetime(dates).to_numpy()
    peak_i, best = 0, (0.0, None, None)
    for i in range(1, len(v)):
        if v[i] >= v[peak_i]:
            span = (d[i] - d[peak_i]) / np.timedelta64(1, 'D') / 30.44
            if span > best[0] and i - peak_i > 1:
                best = (span, str(pd.Timestamp(d[peak_i]).date()), str(pd.Timestamp(d[i]).date()))
            peak_i = i
    span = (d[-1] - d[peak_i]) / np.timedelta64(1, 'D') / 30.44
    if v[-1] < v[peak_i] and span > best[0]:
        best = (span, str(pd.Timestamp(d[peak_i]).date()), 'not recovered')
    return best


def numbers(r: dict) -> dict:
    """Everything the card and the comparison page show."""
    d, m, lots = r['daily'], r['metrics'], r['lots']
    years = (d['date'].iloc[-1] - d['date'].iloc[0]).days / 365.25
    fy = fy_table(d, r['orders'], r['tax'], lots)
    ahead_share, windows = rolling_ahead(d)
    closed = lots[lots['exit_date'].notna()]
    uw_s, uw_b = underwater(d['equity'], d['date']), underwater(d['bench_value'], d['date'])
    charges, tax = float(r['orders']['ch_total'].sum()), float(r['tax']['tax'].sum())
    gross = m['since_start_pnl_rupees'] + charges
    return {
        'years': years, 'final': m['final_equity'], 'bench_final': m['bench_final'], 'cagr': m['cagr'],
        'bench_cagr': m['bench_cagr'], 'lead': m['cagr'] - m['bench_cagr'], 'fy': fy,
        'fy_ahead': int((fy['lead'] > 0).sum()), 'fy_n': len(fy), 'ahead_share': ahead_share, 'windows': windows,
        'boot': bootstrap_lead(d), 'uw': uw_s, 'bench_uw': uw_b,
        'avg_invested': float(d['invested_cost'].mean()), 'avg_idle': float((d['cash'] / d['equity']).mean()),
        'days_held': float((closed['exit_date'] - closed['entry_date']).dt.days.mean()) if len(closed) else float('nan'),
        'exits': closed['exit_reason'].value_counts().to_dict(), 'charges': charges, 'tax': tax, 'gross': gross,
        'tax_owed_days': int((d['cash'] < -0.01).sum()),
    }


# ---- card --------------------------------------------------------------------------------------------------------
def plain_words(r: dict, n: dict) -> str:
    """3-4 sentences written from the numbers."""
    m = r['metrics']
    s = [f"Rs 1 L became {lakh(n['final'])}; the same money in the Nifty 500 became {lakh(n['bench_final'])} "
         f"({pct(n['cagr'], False)} vs {pct(n['bench_cagr'], False)} a year, after costs and tax).",
         f"It was ahead of the index in {n['fy_ahead']} of {n['fy_n']} financial years "
         f"(first and last are part-years) and in {n['ahead_share']:.0%} of all 12-month periods."]
    b = n['boot']
    if b['p5'] < 0 < b['p95']:
        s.append(f"The lead could be luck: its likely range is {pct(b['p5'])} to {pct(b['p95'])} a year.")
    else:
        word = 'ahead' if b['p5'] > 0 else 'behind'
        s.append(f"It is {word} with reasonable confidence: likely range of the lead {pct(b['p5'])} to "
                 f"{pct(b['p95'])} a year.")
    s.append(f"Its worst 12 months lost {rs(abs(m['worst_12m_pnl_rupees']))} on the Rs 1 L stake "
             f"({pct(m['worst_12m_of_stake'])}, to {m['worst_12m_pnl_date']}); on average "
             f"{rs(n['avg_invested'])} was invested.")
    return ' '.join(s)


def card(r: dict, n: dict) -> str:
    """The whole card as Markdown."""
    m, v = r['metrics'], r['val']
    t1 = 'PASS' if m['loss_first_pass'] else 'FAIL'
    lead_word = 'ahead by' if n['lead'] > 0 else 'behind by'
    checks = 'not validated' if not v else (f"validator {v['result']} ({v['date']}"
                                            f"{', with re-runs' if v['rerun'] else ', no re-runs'})"
                                            + (f"; warnings: {'; '.join(v['warnings'])}" if v['warnings'] else ''))
    out = [f"# Report card: {label(r)}", '',
           f"Period {m['start']} to {m['end']} ({n['years']:.1f} years), Rs 1,00,000 start. Generated {date.today()}.",
           '', '## 1. Verdict', '',
           table(['', 'Result'], [
               ['Test 1: worst 12-month loss, of the Rs 1 L stake (must be better than -20%)',
                f"{rs(m['worst_12m_pnl_rupees'])} = {pct(m['worst_12m_of_stake'])} (to {m['worst_12m_pnl_date']}): **{t1}**"],
               ['Test 2: return after costs and tax vs Nifty 500',
                f"{pct(n['cagr'], False)}/yr vs {pct(n['bench_cagr'], False)}/yr: **{lead_word} {abs(n['lead']):.1%}/yr**"],
               ['Checks', checks]]),
           '', '## 2. In plain words', '', plain_words(r, n), '',
           '## 3. Year by year (financial years, April-March)', '',
           'Return = account value at year end / value at year start, after charges and tax; the Nifty measured the '
           'same way. Gain = change in value + tax paid that year (rupees before tax, after charges).', '',
           table(['FY', 'Strategy', 'Nifty 500', 'Ahead by', 'Gain (Rs)', 'Charges', 'Tax', 'Lots bought / sold'],
                 [[x.label, pct(x.ret), pct(x.bench), pct(x.lead), rs(x.gain_rs), rs(x.charges), rs(x.tax),
                   f'{x.bought} / {x.sold}'] for x in n['fy'].itertuples()]),
           '', '## 4. Consistency', '']
    best, worst = n['fy'].loc[n['fy']['ret'].idxmax()], n['fy'].loc[n['fy']['ret'].idxmin()]
    out += [f"- Ahead of the Nifty in **{n['ahead_share']:.0%}** of {n['windows']:,} rolling 12-month periods "
            '(one ending on each trading day).',
            f"- Best year {best['label']}: {pct(best['ret'])} (Nifty {pct(best['bench'])}); worst year {worst['label']}: "
            f"{pct(worst['ret'])} (Nifty {pct(worst['bench'])}).", '',
            '## 5. How sure can we be about the lead?', '']
    b = n['boot']
    out += [f"The {b['months']} monthly results (strategy and Nifty together) were reshuffled {BOOT_N:,} times in "
            f"{BOOT_BLOCK}-month blocks, so good and bad stretches stay together. Likely range of the true lead "
            f"(90% of reshuffles): **{pct(b['p5'])} to {pct(b['p95'])} a year** (middle {pct(b['p50'])}); ahead in "
            f"{b['share_ahead']:.0%} of them." + (' The range includes zero, so the result could be luck.'
                                                   if b['p5'] < 0 < b['p95'] else ''), '',
            '## 6. Risk side by side', '',
            table(['', 'Strategy', 'Nifty 500'], [
                ['Worst 12 months (vs value 12 months earlier)',
                 f"{pct(m['worst_12m_return'])} (to {m['worst_12m_return_end']})",
                 f"{pct(m['bench_worst_12m_return'])} (to {m['bench_worst_12m_return_end']})"],
                ['Deepest fall from a peak', pct(m['max_drawdown']), pct(m['bench_max_drawdown'])],
                ['Longest time below a previous peak', f"{n['uw'][0]:.0f} months ({n['uw'][1]} to {n['uw'][2]})",
                 f"{n['bench_uw'][0]:.0f} months ({n['bench_uw'][1]} to {n['bench_uw'][2]})"],
                ['Worst 12 months at cost (Test 1)', rs(m['worst_12m_pnl_rupees']), '-']]),
            '', '## 7. How it trades', '']
    ex = n['exits']
    names = {'stop': 'stop', 'stop_gap': 'stop (gap down)', 'loss_15': '-15% rule', 'profit_50': '+50% rule',
             'time_12m': '12 months'}
    out += [f"- Lots: {m['lots']:,} ({m['lots_open_at_end']} still open at the end); "
            f"{m['lot_hit_rate']:.0%} made money; held {n['days_held']:.0f} days on average.",
            '- Exits: ' + ', '.join(f"{names.get(k, k)} {v:,}" for k, v in sorted(ex.items(), key=lambda kv: -kv[1])) + '.',
            f"- Money at work: on average {rs(n['avg_invested'])} invested at cost; {n['avg_idle']:.0%} of the account "
            'sat in cash.',
            f"- Worst lot {pct(m['worst_lot_pct'])}, best lot {pct(m['best_lot_pct'])}; "
            f"lots ended below -15%: {m['lots_below_minus_15pct']}.", '',
            '## 8. Costs and tax', '']
    if n['gross'] > 0:
        share = f" = {n['charges'] / n['gross']:.0%} and {n['tax'] / n['gross']:.0%} of the gross gain of {rs(n['gross'])}"
    else:
        share = ' (no gross gain to compare with)'
    out += [f"Charges {rs(n['charges'])}, tax {rs(n['tax'])}{share}. Per year in section 3.", '',
            '## 9. Data notes', '']
    notes = r['cfg']['data']
    out.append(f"- Split/bonus actions not matched to prices: {notes.get('actions_unmatched')} "
               f"{notes.get('unmatched', [])}.")
    if v:
        if v['unexplained_big_moves']:
            out.append(f"- Unexplained one-day moves over 30% in held stocks: {'; '.join(v['unexplained_big_moves'])} "
                       '(demergers, ST-019 -- results for this run are provisional until fixed).')
        if v['failed']:
            out.append(f"- Validator failed: {'; '.join(v['failed'])}.")
    else:
        out.append('- Not validated yet: run `python -m scripts.validate_backtest ' + r['run_id'] + ' --rerun`.')
    if n['tax_owed_days']:
        out.append(f"- Tax larger than the cash on {n['tax_owed_days']} days: carried as tax owed, repaid from later "
                   'sales, no buys meanwhile (Rakesh, 2026-10-15).')
    out.append(f'- {HELD_OUT}')
    return '\n'.join(out) + '\n'


def compare(runs: list) -> str:
    """Sections 1, 6 and 8 for every run plus the Nifty, side by side."""
    hdr = [''] + [label(r) for r, _ in runs] + ['Nifty 500']
    r0, n0 = runs[0]
    rows = [
        ['Rs 1 L became'] + [lakh(n['final']) for _, n in runs] + [lakh(n0['bench_final'])],
        ['Per year (after costs, tax)'] + [pct(n['cagr'], False) for _, n in runs] + [pct(n0['bench_cagr'], False)],
        ['Test 2: vs Nifty per year'] + [pct(n['lead']) for _, n in runs] + ['-'],
        ['Likely range of the lead'] + [f"{pct(n['boot']['p5'])} to {pct(n['boot']['p95'])}" for _, n in runs] + ['-'],
        ['Test 1: worst 12 months, of Rs 1 L'] + [f"{pct(r['metrics']['worst_12m_of_stake'])} "
                                                  f"{'PASS' if r['metrics']['loss_first_pass'] else 'FAIL'}"
                                                  for r, _ in runs] + ['-'],
        ['Worst 12 months (vs value)'] + [pct(r['metrics']['worst_12m_return']) for r, _ in runs]
        + [pct(r0['metrics']['bench_worst_12m_return'])],
        ['Deepest fall from a peak'] + [pct(r['metrics']['max_drawdown']) for r, _ in runs]
        + [pct(r0['metrics']['bench_max_drawdown'])],
        ['Longest below a peak (months)'] + [f"{n['uw'][0]:.0f}" for _, n in runs] + [f"{n0['bench_uw'][0]:.0f}"],
        ['Ahead in 12-month periods'] + [f"{n['ahead_share']:.0%}" for _, n in runs] + ['-'],
        ['Average invested at cost'] + [rs(n['avg_invested']) for _, n in runs] + ['-'],
        ['Charges / tax'] + [f"{rs(n['charges'])} / {rs(n['tax'])}" for _, n in runs] + ['-'],
        ['Checks'] + [(r['val']['result'] + (' (warnings)' if r['val']['warnings'] else '')) if r['val']
                      else 'not validated' for r, _ in runs] + ['-'],
    ]
    m = r0['metrics']
    return '\n'.join([f"# Comparison {m['start']} to {m['end']}", '', f'Generated {date.today()}. Rs 1,00,000 start.',
                      '', table(hdr, rows), '', f'- {HELD_OUT}', '']) + '\n'


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('runs', nargs='+', help='run_id(s) under BACKTESTS_DIR, or folder paths')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    done = []
    for x in args.runs:
        folder = Path(x) if Path(x).is_dir() else BACKTESTS_DIR / x
        r = load(folder)
        n = numbers(r)
        (folder / 'card.md').write_text(card(r, n), encoding='utf-8')
        logger.info(f'card -> {folder / "card.md"}')
        done.append((r, n))
    if len(done) > 1:
        m = done[0][0]['metrics']
        out = BACKTESTS_DIR / f"compare_{m['start']}_{m['end']}.md"
        out.write_text(compare(done), encoding='utf-8')
        logger.info(f'comparison -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
