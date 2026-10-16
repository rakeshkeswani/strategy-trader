# -*- coding: utf-8 -*-
# core/kite.py
"""
ST-006 -- Kite Connect session and a thin read-only REST client (requests; no kiteconnect library).

Login (Rakesh, daily, manual): Kite login page -> redirect to the callback (execution/kite_callback.py) with a one-time
request_token -> exchange_token() -> save_session(). The access token expires at 06:00 IST the next day (regulatory),
so load_session() refuses a session issued before the most recent 06:00 IST ("login needed").

No order endpoint lives here (ST-006 is read-only). Tokens and the API secret are never printed, logged or put in an
exception message: errors carry Kite's error type and message only (Kite never echoes the token).
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from core.config import KITE_API_KEY, KITE_API_SECRET, KITE_SESSION_FILE

API_ROOT = 'https://api.kite.trade'
IST = ZoneInfo('Asia/Kolkata')
EXPIRY = time(6, 0)                     # access tokens expire at 06:00 IST the next day
TIMEOUT = 15


class LoginNeeded(Exception):
    """No valid session for today: Rakesh must log in (bookmarked Kite login link)."""


class KiteError(Exception):
    """Kite answered with an error (type and message only)."""


def login_url(api_key: str = KITE_API_KEY) -> str:
    """The Kite login page for this app (safe to share: the API key is public)."""
    return f'https://kite.zerodha.com/connect/login?v=3&api_key={api_key}'


def mask(user_id: str) -> str:
    """'UO0468' -> 'UO****'."""
    return (user_id[:2] + '*' * (len(user_id) - 2)) if user_id else ''


def last_expiry(now: datetime) -> datetime:
    """The most recent 06:00 IST at or before `now` (a timezone-aware datetime)."""
    local = now.astimezone(IST)
    boundary = datetime.combine(local.date(), EXPIRY, tzinfo=IST)
    return boundary if local >= boundary else boundary - timedelta(days=1)


def is_fresh(issued_at: datetime, now: datetime) -> bool:
    """A session is usable only if issued after the most recent 06:00 IST."""
    return issued_at >= last_expiry(now)


@dataclass(frozen=True)
class Session:
    user_id: str
    access_token: str
    issued_at: datetime                  # timezone-aware

    def __repr__(self) -> str:           # never show the token
        return f'Session(user_id={mask(self.user_id)!r}, issued_at={self.issued_at.isoformat()})'


def _check(resp: requests.Response) -> dict | list:
    """Kite's envelope -> data, or KiteError with Kite's error_type and message (no request details)."""
    try:
        body = resp.json()
    except ValueError:
        raise KiteError(f'HTTP {resp.status_code}: not JSON') from None
    if resp.status_code != 200 or body.get('status') != 'success':
        raise KiteError(f"HTTP {resp.status_code} {body.get('error_type', '')}: {body.get('message', '')}".strip())
    return body['data']


def exchange_token(request_token: str, api_key: str = KITE_API_KEY, api_secret: str = KITE_API_SECRET,
                   now: datetime | None = None, post=requests.post) -> Session:
    """POST /session/token with checksum SHA-256(api_key + request_token + api_secret) -> today's Session."""
    if not api_key or not api_secret:
        raise KiteError('KITE_API_KEY / KITE_API_SECRET not set (prod .env)')
    checksum = hashlib.sha256((api_key + request_token + api_secret).encode('utf-8')).hexdigest()
    resp = post(f'{API_ROOT}/session/token', headers={'X-Kite-Version': '3'}, timeout=TIMEOUT,
                data={'api_key': api_key, 'request_token': request_token, 'checksum': checksum})
    data = _check(resp)
    return Session(user_id=data['user_id'], access_token=data['access_token'],
                   issued_at=now or datetime.now(timezone.utc))


def save_session(s: Session, path: Path = KITE_SESSION_FILE) -> None:
    """Write the session (mode 600, folder 700), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'user_id': s.user_id, 'access_token': s.access_token, 'issued_at': s.issued_at.isoformat()}, f)
    os.replace(tmp, path)


def load_session(path: Path = KITE_SESSION_FILE, now: datetime | None = None) -> Session:
    """Today's session, or LoginNeeded (missing, unreadable, or issued before the last 06:00 IST)."""
    try:
        d = json.loads(path.read_text(encoding='utf-8'))
        s = Session(user_id=d['user_id'], access_token=d['access_token'],
                    issued_at=datetime.fromisoformat(d['issued_at']))
    except (OSError, ValueError, KeyError):
        raise LoginNeeded('no Kite session: log in via the bookmarked Kite login link') from None
    if not is_fresh(s.issued_at, now or datetime.now(timezone.utc)):
        raise LoginNeeded(f'Kite session from {s.issued_at.astimezone(IST):%Y-%m-%d %H:%M} IST has expired: log in')
    return s


class Client:
    """Read-only Kite client for one session. Order endpoints are deliberately absent (ST-007/008/009)."""

    def __init__(self, session: Session, api_key: str = KITE_API_KEY, get=requests.get):
        self._auth = {'X-Kite-Version': '3', 'Authorization': f'token {api_key}:{session.access_token}'}
        self._get = get
        self.user_id = session.user_id

    def __repr__(self) -> str:
        return f'Client(user_id={mask(self.user_id)!r})'

    def _call(self, path: str) -> dict | list:
        return _check(self._get(f'{API_ROOT}{path}', headers=self._auth, timeout=TIMEOUT))

    def profile(self) -> dict:
        return self._call('/user/profile')

    def margins(self, segment: str = 'equity') -> dict:
        return self._call(f'/user/margins/{segment}')

    def holdings(self) -> list:
        return self._call('/portfolio/holdings')


def client(path: Path = KITE_SESSION_FILE) -> Client:
    """A ready read-only client for today, or LoginNeeded."""
    return Client(load_session(path))
