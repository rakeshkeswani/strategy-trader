# -*- coding: utf-8 -*-
# backtest/costs.py
"""
ST-010 -- Zerodha equity-delivery charges and Indian capital-gains tax, as verified 2026-10-14 (tech-debt/ST-010.md).

Charges (zerodha.com/charges): brokerage 0; STT 0.1% buy and sell; NSE transaction 0.00307%; SEBI Rs 10/crore;
stamp 0.015% on buys; GST 18% on (brokerage + SEBI + transaction); DP Rs 15.34 per stock per sell day.
Tax: STCG 20% + 4% cess; LTCG 12.5% + 4% cess for listed equity held more than 12 months; LTCG exemption not modelled.
Today's rates are applied to every year (conservative before July 2024).
"""

from datetime import date

STT = 0.001
STAMP_BUY = 0.00015
TXN = 0.0000307
SEBI = 10 / 1e7
GST = 0.18
DP_PER_SELL_DAY = 15.34
STCG_RATE = 0.20 * 1.04
LTCG_RATE = 0.125 * 1.04


def buy_charges(value: float) -> dict:
    """Charges on a delivery buy of `value` rupees."""
    stt, stamp, txn, sebi = value * STT, value * STAMP_BUY, value * TXN, value * SEBI
    gst = GST * (txn + sebi)
    return {'stt': stt, 'stamp': stamp, 'txn': txn, 'sebi': sebi, 'gst': gst, 'dp': 0.0,
            'total': stt + stamp + txn + sebi + gst}


def sell_charges(value: float, dp: bool) -> dict:
    """Charges on a delivery sell of `value` rupees; `dp` is True for the first sale of that stock that day."""
    stt, txn, sebi = value * STT, value * TXN, value * SEBI
    gst = GST * (txn + sebi)
    dp_fee = DP_PER_SELL_DAY if dp else 0.0
    return {'stt': stt, 'stamp': 0.0, 'txn': txn, 'sebi': sebi, 'gst': gst, 'dp': dp_fee,
            'total': stt + txn + sebi + gst + dp_fee}


def is_long_term(entry: date, exit_: date) -> bool:
    """True when held MORE than 12 months: exit after the same calendar date one year later."""
    return exit_ > one_year_after(entry)


def one_year_after(d: date) -> date:
    """Same calendar date next year (29 Feb -> 28 Feb)."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def fy_tax(st_gain: float, lt_gain: float, st_loss_cf: float, lt_loss_cf: float) -> tuple[float, float, float]:
    """Tax for one financial year from net realised gains (negative = loss) and carried-forward losses.

    Short-term losses set off against short- then long-term gains; long-term losses only against long-term gains.
    Returns (tax, st_loss_carried, lt_loss_carried).
    """
    st, lt = st_gain, lt_gain
    st_cf, lt_cf = st_loss_cf, lt_loss_cf
    if st < 0:                      # this year's short-term loss reduces long-term gains, rest carries
        use = min(-st, max(lt, 0))
        lt -= use
        st_cf += -st - use
        st = 0.0
    if lt < 0:
        lt_cf += -lt
        lt = 0.0
    use = min(st_cf, st)            # carried short-term losses: first against short-term, then long-term
    st -= use
    st_cf -= use
    use = min(st_cf, lt)
    lt -= use
    st_cf -= use
    use = min(lt_cf, lt)            # carried long-term losses only against long-term
    lt -= use
    lt_cf -= use
    return st * STCG_RATE + lt * LTCG_RATE, st_cf, lt_cf
