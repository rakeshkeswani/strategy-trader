# -*- coding: utf-8 -*-
# backtest/engine.py
"""
ST-010 -- weekly, lot-based backtest engine (design: tech-debt/ST-010.md; data model: docs/DATA_MODEL.md).

Prices are split/bonus-ADJUSTED (core/adjusted.py), so a lot's quantity is held in adjusted units and every rupee value
(price x quantity) equals the real one; share counts are rounded on the RAW price (raw = adjusted x adj_factor).

One trading day, in order:
  open   - time exits (first trading day after a lot is held more than 12 months), lot stops gapped through at the
           open (sell at the open), queued weekly sells, then queued buys (sizing and limits checked here)
  intra  - lot stops touched by the day's low (sell at the stop)
  close  - stock-average loss rule (sell the oldest lot at the close), trailing stops raised, equity marked, loss tier
  signal - on the last trading day of a week: rank candidates from the universe in force; queue buys (and, for the
           stock-average mode, one profit sale per stock) for the next trading day's open
  FY end - capital-gains tax for the financial year deducted from cash (also accrued at the end of the run)
Slippage SLIPPAGE on every fill, against us. Every decision uses data up to that moment only.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

from backtest.costs import buy_charges, fy_tax, is_long_term, sell_charges

SLIPPAGE = 0.001
MAX_CANDIDATES = 60


@dataclass
class Lot:
    """One buy: its own entry, stop and exit."""
    lot_id: int
    series_id: str
    symbol: str
    entry_date: date
    entry_px: float          # adjusted, incl. slippage
    qty: float               # adjusted units
    raw_qty: int
    buy_value: float
    buy_charges: float
    buy_stt: float
    stop: float = math.nan
    high_close: float = math.nan
    exit_date: date | None = None
    exit_px: float = math.nan
    sell_value: float = math.nan
    sell_charges: float = math.nan
    sell_stt: float = math.nan
    exit_reason: str = ''


@dataclass
class Result:
    """Outputs of one run."""
    lots: pd.DataFrame
    orders: pd.DataFrame
    daily: pd.DataFrame
    tax: pd.DataFrame
    notes: dict = field(default_factory=dict)


def fy_of(d: date) -> int:
    """Financial year starting year (Apr-Mar): 2020-05-01 -> 2020, 2021-02-01 -> 2020."""
    return d.year if d.month >= 4 else d.year - 1


class Backtest:
    """Run one strategy over [start, end] on a prepared market frame."""

    def __init__(self, strategy: dict, market: pd.DataFrame, members_fn, start: date, end: date,
                 limits: dict | None, capital: float = 100000.0):
        """`market`: trade_date, series_id, symbol, open, high, low, close, adj_factor + the strategy's indicator columns.

        `members_fn(date) -> set of series_id` (universe in force). `limits` None = only cash and the weekly budget
        (faithful run); else keys capital_cap, per_stock, loss_tiers (alert, no_buys, halt as fractions of capital).
        """
        self.s, self.limits, self.capital = strategy, limits, capital
        self.members_fn = members_fn
        m = market[(market['trade_date'] >= start) & (market['trade_date'] <= end)]
        self.days = sorted(m['trade_date'].unique())
        cols = ['series_id', 'symbol', 'open', 'high', 'low', 'close', 'adj_factor']
        ind = [c for c in ('ret_126', 'ret_252', 'sma_200', 'rsi_14') if c in m.columns]
        self.bars = {d: g.set_index('series_id')[cols[1:] + ind] for d, g in m.groupby('trade_date')}
        self.cash = capital
        self.open: list[Lot] = []
        self.closed: list[Lot] = []
        self.orders: list[dict] = []
        self.daily: list[dict] = []
        self.tax_rows: list[dict] = []
        self.queue_buys: list[tuple] = []
        self.queue_sells: list[str] = []
        self.last_close: dict = {}
        self.next_id = 1
        self.fy_gain = {'st': 0.0, 'lt': 0.0}
        self.loss_cf = {'st': 0.0, 'lt': 0.0}
        self.tax_paid = 0.0
        self.charges_paid = 0.0
        self.sold_today: set = set()
        self.tier = 'ok'

    # ---- helpers -------------------------------------------------------------------------------------------------
    def _cost_open(self, series_id: str | None = None) -> float:
        """Buy value of open lots (all, or of one series)."""
        return sum(l.buy_value for l in self.open if series_id is None or l.series_id == series_id)

    def _order(self, d: date, lot: Lot, side: str, px: float, value: float, ch: dict, reason: str) -> None:
        """Append one order record."""
        self.orders.append({'date': d, 'lot_id': lot.lot_id, 'side': side, 'series_id': lot.series_id,
                            'symbol': lot.symbol, 'price': px, 'value': value, 'reason': reason,
                            **{f'ch_{k}': v for k, v in ch.items()}})

    def _sell(self, d: date, lot: Lot, px: float, reason: str) -> None:
        """Close `lot` at adjusted price `px` (slippage applied here)."""
        fill = px * (1 - SLIPPAGE)
        value = lot.qty * fill
        ch = sell_charges(value, dp=lot.series_id not in self.sold_today)
        self.sold_today.add(lot.series_id)
        self.cash += value - ch['total']
        self.charges_paid += ch['total']
        lot.exit_date, lot.exit_px, lot.sell_value = d, fill, value
        lot.sell_charges, lot.sell_stt, lot.exit_reason = ch['total'], ch['stt'], reason
        gain = (value - (ch['total'] - ch['stt'])) - (lot.buy_value + (lot.buy_charges - lot.buy_stt))
        self.fy_gain['lt' if is_long_term(lot.entry_date, d) else 'st'] += gain
        self.open.remove(lot)
        self.closed.append(lot)
        self._order(d, lot, 'SELL', fill, value, ch, reason)

    def _buy(self, d: date, series_id: str, amount: float, bar) -> None:
        """Open a lot of about `amount` rupees at the open (whole shares on the raw price)."""
        fill = bar['open'] * (1 + SLIPPAGE)
        raw_px = fill * bar['adj_factor']
        raw_qty = int(amount // raw_px) if raw_px > 0 else 0
        if raw_qty <= 0:
            return
        value = raw_qty * raw_px
        ch = buy_charges(value)
        if value + ch['total'] > self.cash:
            return
        self.cash -= value + ch['total']
        self.charges_paid += ch['total']
        lot = Lot(self.next_id, series_id, bar['symbol'], d, fill, raw_qty * bar['adj_factor'], raw_qty, value,
                  ch['total'], ch['stt'])
        self.next_id += 1
        ex = self.s['exit']
        if ex['mode'] == 'lot_stop':
            lot.stop = fill * (1 - ex['initial_stop'])
            lot.high_close = fill
        self.open.append(lot)
        self._order(d, lot, 'BUY', fill, value, ch, 'entry')

    # ---- the daily steps ----------------------------------------------------------------------------------------
    def _open_steps(self, d: date, bars: pd.DataFrame) -> None:
        """Time exits, gapped stops, queued sells, queued buys -- all at the open."""
        ex = self.s['exit']
        for lot in list(self.open):
            if lot.series_id not in bars.index:
                continue
            bar = bars.loc[lot.series_id]
            if is_long_term(lot.entry_date, d):
                self._sell(d, lot, bar['open'], 'time_12m')
            elif ex['mode'] == 'lot_stop' and bar['open'] <= lot.stop:
                self._sell(d, lot, bar['open'], 'stop_gap')
        for sid in self.queue_sells:
            lots = sorted((l for l in self.open if l.series_id == sid), key=lambda l: (l.entry_date, l.lot_id))
            if lots and sid in bars.index:
                self._sell(d, lots[0], bars.loc[sid]['open'], 'profit_50')
        self.queue_sells = []
        budget = self.s['sizing']['weekly_budget']
        spent = 0.0
        for sid, target in self.queue_buys:
            if sid not in bars.index or spent >= budget:
                continue
            bar = bars.loc[sid]
            amount = min(target, budget - spent)
            if self.limits:
                amount = min(amount, self.limits['capital_cap'] - self._cost_open(),
                             self.limits['per_stock'] - self._cost_open(sid))
            if ex['mode'] == 'lot_stop':
                amount = min(amount, self.s['sizing']['risk_per_trade'] / ex['initial_stop'])
            if amount < max(self.s['sizing'].get('min_lot', 0), 1):
                continue
            before = self.cash
            self._buy(d, sid, amount, bar)
            spent += before - self.cash
        self.queue_buys = []

    def _intraday_and_close(self, d: date, bars: pd.DataFrame) -> None:
        """Stops touched intraday; stock-average loss rule; trailing stops; last closes."""
        ex = self.s['exit']
        if ex['mode'] == 'lot_stop':
            for lot in list(self.open):
                if lot.series_id in bars.index and bars.loc[lot.series_id]['low'] <= lot.stop:
                    self._sell(d, lot, lot.stop, 'stop')
        if ex['mode'] == 'stock_average':
            for sid in sorted({l.series_id for l in self.open}):
                if sid not in bars.index:
                    continue
                lots = sorted((l for l in self.open if l.series_id == sid), key=lambda l: (l.entry_date, l.lot_id))
                avg = sum(l.buy_value for l in lots) / sum(l.qty for l in lots)
                if bars.loc[sid]['close'] <= avg * (1 + ex['loss_trigger']):
                    self._sell(d, lots[0], bars.loc[sid]['close'], 'loss_15')
        for sid, row in bars.iterrows():
            self.last_close[sid] = row['close']
        if ex['mode'] == 'lot_stop':
            for lot in self.open:
                if lot.series_id in bars.index:
                    lot.high_close = max(lot.high_close, bars.loc[lot.series_id]['close'])
                    lot.stop = max(lot.stop, lot.high_close * (1 - ex['trailing_stop']))

    def _mark(self, d: date) -> None:
        """Record the day's equity and update the loss tier."""
        holdings = sum(l.qty * self.last_close.get(l.series_id, l.entry_px) for l in self.open)
        equity = self.cash + holdings
        self.tier = 'ok'
        if self.limits:
            ref = self.capital
            past = [r for r in self.daily if (d - r['date']).days >= 365]
            if past:
                ref = past[-1]['equity']
            change = (equity - ref) / self.capital
            a, n, h = self.limits['loss_tiers']
            self.tier = 'halt' if change <= -h else 'no_buys' if change <= -n else 'alert' if change <= -a else 'ok'
        self.daily.append({'date': d, 'cash': self.cash, 'holdings': holdings, 'equity': equity,
                           'invested_cost': self._cost_open(), 'open_lots': len(self.open), 'tier': self.tier,
                           'tax_paid': self.tax_paid, 'charges_paid': self.charges_paid})

    def _signal(self, d: date, bars: pd.DataFrame) -> None:
        """Rank candidates at this week's last close and queue next open's orders."""
        sig, ex = self.s['signal'], self.s['exit']
        if ex['mode'] == 'stock_average':
            for sid in sorted({l.series_id for l in self.open}):
                if sid not in bars.index:
                    continue
                lots = [l for l in self.open if l.series_id == sid]
                avg = sum(l.buy_value for l in lots) / sum(l.qty for l in lots)
                if bars.loc[sid]['close'] / avg - 1 > ex['profit_trigger']:
                    self.queue_sells.append(sid)
        if self.tier in ('no_buys', 'halt'):
            return
        members = self.members_fn(d)
        c = bars[bars.index.isin(members)].copy()
        key = sig['rank_by']
        c = c[c[key].notna()]
        if 'above_sma' in sig:
            col = f"sma_{sig['above_sma']}"
            c = c[c[col].notna() & (c['close'] > c[col])]
        if 'rsi_min' in sig:
            c = c[c['rsi_14'].between(sig['rsi_min'], sig['rsi_max'])]
        c = c.reset_index().sort_values([key, 'series_id'], ascending=[False, True])
        if sig['top_n']:
            c = c.head(sig['top_n'])
        c = c.head(MAX_CANDIDATES)
        budget = self.s['sizing']['weekly_budget']
        if sig.get('weights') == 'by_gain':
            c = c[c[key] > 0]
            total = c[key].sum()
            self.queue_buys = [(r.series_id, budget * getattr(r, key) / total) for r in c.itertuples()] if total else []
        else:
            self.queue_buys = [(r.series_id, budget) for r in c.itertuples()]

    def _fy_close(self, d: date) -> None:
        """Deduct the financial year's capital-gains tax."""
        tax, self.loss_cf['st'], self.loss_cf['lt'] = fy_tax(self.fy_gain['st'], self.fy_gain['lt'],
                                                             self.loss_cf['st'], self.loss_cf['lt'])
        self.tax_rows.append({'fy': fy_of(d), 'date': d, 'st_gain': self.fy_gain['st'], 'lt_gain': self.fy_gain['lt'],
                              'tax': tax, 'st_loss_cf': self.loss_cf['st'], 'lt_loss_cf': self.loss_cf['lt']})
        self.cash -= tax
        self.tax_paid += tax
        self.fy_gain = {'st': 0.0, 'lt': 0.0}

    # ---- run -----------------------------------------------------------------------------------------------------
    def run(self) -> Result:
        """Simulate every trading day; return the run's outputs."""
        for i, d in enumerate(self.days):
            bars = self.bars[d]
            self.sold_today = set()
            self._open_steps(d, bars)
            self._intraday_and_close(d, bars)
            nxt = self.days[i + 1] if i + 1 < len(self.days) else None
            if nxt is None or fy_of(nxt) != fy_of(d):
                self._fy_close(d)
            self._mark(d)
            if nxt is not None and nxt.isocalendar()[:2] != d.isocalendar()[:2]:
                self._signal(d, bars)
        lots = pd.DataFrame([asdict(l) for l in self.closed + self.open])
        return Result(lots=lots, orders=pd.DataFrame(self.orders), daily=pd.DataFrame(self.daily),
                      tax=pd.DataFrame(self.tax_rows),
                      notes={'open_lots_at_end': len(self.open), 'days': len(self.days)})
