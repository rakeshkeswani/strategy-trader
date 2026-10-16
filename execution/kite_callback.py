# -*- coding: utf-8 -*-
# execution/kite_callback.py
"""
ST-006 -- the Kite login callback: Rakesh's daily login lands here and becomes today's session.

Route: https://kite.myinvestiq.ai/kite/callback (Cloudflare tunnel + Cloudflare Access, only Rakesh's email) ->
http://127.0.0.1:KITE_CALLBACK_PORT/kite/callback on rkneo50q. Listens on 127.0.0.1 only, so the one way in is
cloudflared; every request must also carry Cloudflare Access's `Cf-Access-Jwt-Assertion` JWT, verified (RS256 signature
against the team's published keys, audience = the Access app's AUD tag, issuer = the team, expiry) -- a forged header
from anything local is refused too (homelab recommendation, 2026-10-16). Fails closed: no team/AUD configured, or the
keys cannot be fetched -> refused.

On `status=success&request_token=...`: exchange the token (core.kite.exchange_token), save the session (mode 600,
outside the repo), write `audit_log` (no token), answer with a plain page. Never logs the query string, the
request_token or the access token.

Run (prod, systemd service `stratrad-kite-callback`, see deploy/): python -m execution.kite_callback
"""

import html
import logging
import sys
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import jwt
from psycopg.types.json import Jsonb

from core.config import KITE_ACCESS_AUD, KITE_ACCESS_TEAM, KITE_CALLBACK_PORT, LOG_DIR
from core.kite import IST, KiteError, exchange_token, last_expiry, mask, save_session

logger = logging.getLogger('kite_callback')
PATH = '/kite/callback'
ACCESS_HEADER = 'Cf-Access-Jwt-Assertion'


def page(title: str, text: str) -> bytes:
    """A minimal phone-friendly page."""
    return (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{html.escape(title)}</title><body style="font-family:sans-serif;margin:2em">'
            f'<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>').encode('utf-8')


class AccessUnavailable(Exception):
    """The Access JWT could not be checked (not configured, or Cloudflare's keys unreachable)."""


class AccessVerifier:
    """Verifies Cloudflare Access JWTs for one Access application."""

    def __init__(self, team: str = KITE_ACCESS_TEAM, aud: str = KITE_ACCESS_AUD, jwks=None):
        self.team, self.aud = team, aud
        self.issuer = f'https://{team}'
        self._jwks = jwks or (jwt.PyJWKClient(f'https://{team}/cdn-cgi/access/certs', cache_keys=True, lifespan=3600,
                                              timeout=10) if team else None)

    def __call__(self, token: str) -> dict:
        """Claims of a valid token; jwt.InvalidTokenError when invalid; AccessUnavailable when it cannot be checked."""
        if not self.team or not self.aud or self._jwks is None:
            raise AccessUnavailable('KITE_ACCESS_TEAM / KITE_ACCESS_AUD not set')
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as e:
            raise AccessUnavailable(f'Cloudflare Access keys unreachable: {type(e).__name__}') from None
        except jwt.PyJWKClientError as e:          # unknown key id, malformed token
            raise jwt.InvalidTokenError(str(e)) from None
        return jwt.decode(token, key, algorithms=['RS256'], audience=self.aud, issuer=self.issuer,
                          options={'require': ['exp', 'iat', 'aud', 'iss']})


_verifier = None


def default_verifier(token: str) -> dict:
    """The configured verifier (built on first use, so the key cache lives for the life of the service)."""
    global _verifier
    if _verifier is None:
        _verifier = AccessVerifier()
    return _verifier(token)


def audit(action: str, details: dict) -> None:
    """One audit_log row (actor rakesh). Imported lazily so the handler can be tested without a database."""
    from core.db import connect
    with connect('app') as conn:
        conn.execute('INSERT INTO audit_log (actor, action, details) VALUES (%s, %s, %s)',
                     ('rakesh', action, Jsonb(details)))


def handle(target: str, headers: dict, verify=default_verifier, exchange=exchange_token, save=save_session,
           write_audit=audit) -> tuple[int, bytes]:
    """(HTTP status, body) for one GET. `target` is the request path with query; `headers` a case-insensitive map."""
    parts = urlsplit(target)
    if parts.path != PATH:
        return 404, page('Not found', '')
    token = headers.get(ACCESS_HEADER)
    if not token:
        logger.warning('refused: request without Cloudflare Access')
        return 403, page('Forbidden', 'This page is only reachable through Cloudflare Access.')
    try:
        verify(token)
    except AccessUnavailable as e:
        logger.error(f'refused: cannot verify Cloudflare Access ({e})')
        return 503, page('Try again', 'Could not verify the Cloudflare Access login just now. Try the login link again.')
    except jwt.InvalidTokenError as e:
        logger.warning(f'refused: invalid Cloudflare Access token ({type(e).__name__})')
        return 403, page('Forbidden', 'This page is only reachable through Cloudflare Access.')
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    if q.get('status') != 'success' or not q.get('request_token'):
        logger.warning(f"login not successful (status={q.get('status')!r})")
        return 400, page('Login not completed', 'Kite did not report a successful login. Try the login link again.')
    try:
        s = exchange(q['request_token'])
    except KiteError as e:
        logger.error(f'token exchange failed: {e}')
        return 502, page('Login failed', f'Kite refused the token exchange: {e}')
    save(s)
    valid_until = last_expiry(s.issued_at) + timedelta(days=1)
    details = {'user': mask(s.user_id), 'issued_at': s.issued_at.isoformat(), 'valid_until': valid_until.isoformat()}
    try:
        write_audit('kite_login', details)
        note = ''
    except Exception as e:  # noqa: BLE001 -- the session is saved; a missing audit row must not undo the login
        logger.error(f'audit_log write failed: {type(e).__name__}')
        note = ' (audit log write failed -- see the service log)'
    logger.info(f"login ok: {details['user']}, valid until {valid_until.astimezone(IST):%Y-%m-%d %H:%M} IST")
    return 200, page('Logged in', f"Kite session for {details['user']} is active until "
                                  f"{valid_until.astimezone(IST):%a %d %b %H:%M} IST.{note}")


class Handler(BaseHTTPRequestHandler):
    server_version = 'stratrad'
    sys_version = ''

    def do_GET(self):  # noqa: N802 (http.server API)
        status, body = handle(self.path, self.headers)
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # the default would log the full URL, request_token included
        logger.info(f'{self.command} {urlsplit(self.path).path} -> {args[1] if len(args) > 1 else ""}')


def main() -> int:
    """Serve on 127.0.0.1 only."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LOG_DIR / 'kite_callback.log', encoding='utf-8')])
    srv = ThreadingHTTPServer(('127.0.0.1', KITE_CALLBACK_PORT), Handler)
    logger.info(f'listening on 127.0.0.1:{KITE_CALLBACK_PORT}{PATH}')
    srv.serve_forever()
    return 0


if __name__ == '__main__':
    sys.exit(main())
