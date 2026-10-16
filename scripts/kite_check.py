# -*- coding: utf-8 -*-
# scripts/kite_check.py
"""
ST-006 -- read-only check of today's Kite session: masked user id, available equity funds, number of holdings.

Exit 0 with RESULT: OK; exit 1 with RESULT: LOGIN NEEDED (no session, or issued before the last 06:00 IST); exit 2 when
Kite returns an error. Never prints the token. Usage (repo root): python -m scripts.kite_check
"""

import sys

from core.kite import KiteError, LoginNeeded, client, login_url, mask


def main() -> int:
    """CLI entry point."""
    try:
        c = client()
    except LoginNeeded as e:
        print(f'RESULT: LOGIN NEEDED -- {e}\nLogin link: {login_url()}')
        return 1
    try:
        p, m, h = c.profile(), c.margins('equity'), c.holdings()
    except KiteError as e:
        print(f'RESULT: KITE ERROR -- {e}')
        return 2
    print(f"user {mask(p.get('user_id', ''))} ({p.get('user_type', '')}); exchanges {','.join(p.get('exchanges', []))}")
    print(f"equity available: Rs {m['available']['live_balance']:,.2f} (net Rs {m['net']:,.2f})")
    print(f'holdings: {len(h)} stocks')
    print('RESULT: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
