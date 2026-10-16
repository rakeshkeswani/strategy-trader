# -*- coding: utf-8 -*-
"""ST-006: session freshness, token exchange, the callback's rules, and that no token reaches a log or a repr.
Kite and the database are stubbed; nothing goes over the network."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from core import kite
from core.kite import IST, Client, KiteError, LoginNeeded, Session, exchange_token, is_fresh, last_expiry, load_session
from execution import kite_callback

TOKEN = 'ACCESS-TOKEN-SECRET-123'
REQ = 'REQ-TOKEN-456'


def ist(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


class Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


# ---- freshness -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('issued, now, fresh', [
    (ist(2026, 10, 16, 8, 30), ist(2026, 10, 16, 15, 0), True),    # today's login, afternoon
    (ist(2026, 10, 16, 8, 30), ist(2026, 10, 17, 5, 59), True),    # still valid just before 06:00 next day
    (ist(2026, 10, 16, 8, 30), ist(2026, 10, 17, 6, 0), False),    # expired at 06:00
    (ist(2026, 10, 17, 2, 0), ist(2026, 10, 17, 5, 0), True),      # a login after midnight is valid until 06:00
    (ist(2026, 10, 17, 2, 0), ist(2026, 10, 17, 7, 0), False),     # ...and not after
])
def test_session_expires_at_six_ist(issued, now, fresh):
    assert is_fresh(issued, now) is fresh


def test_last_expiry_handles_utc_input():
    now = datetime(2026, 10, 16, 0, 15, tzinfo=timezone.utc)      # 05:45 IST
    assert last_expiry(now) == ist(2026, 10, 15, 6, 0)


def test_save_and_load_round_trip_and_stale_refused(tmp_path):
    f = tmp_path / 'sub' / 'kite_session.json'
    kite.save_session(Session('UO0468', TOKEN, ist(2026, 10, 16, 8, 30)), f)
    assert load_session(f, now=ist(2026, 10, 16, 9, 0)).access_token == TOKEN
    with pytest.raises(LoginNeeded):
        load_session(f, now=ist(2026, 10, 17, 9, 0))
    with pytest.raises(LoginNeeded):
        load_session(tmp_path / 'missing.json')


# ---- token exchange ------------------------------------------------------------------------------------------------
def test_exchange_sends_checksum_and_returns_session():
    seen = {}

    def post(url, headers, timeout, data):
        seen.update(url=url, data=data)
        return Resp({'status': 'success', 'data': {'user_id': 'UO0468', 'access_token': TOKEN}})

    s = exchange_token(REQ, api_key='key', api_secret='sec', now=ist(2026, 10, 16, 8, 30), post=post)
    assert seen['url'].endswith('/session/token')
    assert seen['data']['checksum'] == hashlib.sha256(f'key{REQ}sec'.encode()).hexdigest()
    assert s.user_id == 'UO0468' and s.access_token == TOKEN


def test_exchange_error_carries_kite_message_only():
    post = lambda *a, **k: Resp({'status': 'error', 'error_type': 'TokenException', 'message': 'Token is invalid'}, 403)
    with pytest.raises(KiteError, match='TokenException: Token is invalid') as e:
        exchange_token(REQ, api_key='key', api_secret='sec', post=post)
    assert REQ not in str(e.value) and 'sec' not in str(e.value)


def test_client_sends_auth_header_and_hides_token():
    seen = {}

    def get(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return Resp({'status': 'success', 'data': []})

    c = Client(Session('UO0468', TOKEN, ist(2026, 10, 16, 8, 30)), api_key='key', get=get)
    assert c.holdings() == []
    assert seen['headers']['Authorization'] == f'token key:{TOKEN}' and seen['url'].endswith('/portfolio/holdings')
    assert TOKEN not in repr(c) and TOKEN not in repr(Session('UO0468', TOKEN, ist(2026, 10, 16, 8, 30)))


def test_no_order_endpoints_in_st006_code():
    """ST-006 is read-only: no order or GTT endpoint anywhere in the Kite code."""
    for f in ['core/kite.py', 'execution/kite_callback.py', 'scripts/kite_check.py']:
        text = (Path(__file__).resolve().parents[1] / f).read_text(encoding='utf-8')
        assert '/orders' not in text and '/gtt' not in text, f


# ---- callback ------------------------------------------------------------------------------------------------------
ACCESS = {'Cf-Access-Jwt-Assertion': 'jwt'}
OK_PATH = f'/kite/callback?action=login&type=login&status=success&request_token={REQ}'
PASS = lambda token: {}            # noqa: E731 -- a verifier that accepts (JWT checks are tested separately below)


def fake_exchange(req):
    assert req == REQ
    return Session('UO0468', TOKEN, ist(2026, 10, 16, 8, 30))


def test_callback_success_saves_audits_and_hides_token(caplog):
    saved, audited = [], []
    with caplog.at_level(logging.INFO):
        status, body = kite_callback.handle(OK_PATH, ACCESS, verify=PASS, exchange=fake_exchange, save=saved.append,
                                            write_audit=lambda a, d: audited.append((a, d)))
    assert status == 200 and b'Logged in' in body and b'Sat 17 Oct 06:00' in body
    assert saved[0].access_token == TOKEN
    assert audited[0][0] == 'kite_login' and audited[0][1]['user'] == 'UO****'
    blob = body.decode() + json.dumps(audited) + caplog.text
    assert TOKEN not in blob and REQ not in blob


def test_callback_refuses_without_access_header():
    called = []
    status, _ = kite_callback.handle(OK_PATH, {}, verify=PASS, exchange=lambda r: called.append(r), save=None,
                                     write_audit=None)
    assert status == 403 and not called


@pytest.mark.parametrize('path, want', [('/other', 404), ('/kite/callback?status=cancelled', 400),
                                        ('/kite/callback?status=success', 400)])
def test_callback_rejects_wrong_path_or_unsuccessful_login(path, want):
    assert kite_callback.handle(path, ACCESS, verify=PASS, exchange=None, save=None, write_audit=None)[0] == want


def test_callback_kite_error_is_502_and_saves_nothing(caplog):
    def bad(req):
        raise KiteError('HTTP 403 TokenException: Token is invalid or has expired.')
    saved = []
    status, body = kite_callback.handle(OK_PATH, ACCESS, verify=PASS, exchange=bad, save=saved.append, write_audit=None)
    assert status == 502 and not saved and REQ not in caplog.text + body.decode()


def test_callback_keeps_login_when_audit_fails():
    def boom(a, d):
        raise RuntimeError('db down')
    saved = []
    status, body = kite_callback.handle(OK_PATH, ACCESS, verify=PASS, exchange=fake_exchange, save=saved.append,
                                        write_audit=boom)
    assert status == 200 and saved and b'audit log write failed' in body


# ---- Cloudflare Access JWT ----------------------------------------------------------------------------------------
TEAM, AUD = 'team.cloudflareaccess.com', 'aud-tag-123'
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    """Stands in for PyJWKClient: always returns KEY's public half (or raises `error`)."""
    def __init__(self, error=None):
        self.error = error

    def get_signing_key_from_jwt(self, token):
        if self.error:
            raise self.error
        return type('K', (), {'key': KEY.public_key()})()


def token(key=KEY, aud=AUD, iss=f'https://{TEAM}', exp_minutes=10):
    now = datetime.now(timezone.utc)
    return jwt.encode({'aud': [aud], 'iss': iss, 'iat': now, 'exp': now + timedelta(minutes=exp_minutes),
                       'email': 'rakeshbk@gmail.com'}, key, algorithm='RS256', headers={'kid': 'k1'})


def run(tok, verifier):
    return kite_callback.handle(OK_PATH, {'Cf-Access-Jwt-Assertion': tok}, verify=verifier, exchange=fake_exchange,
                                save=lambda s: None, write_audit=lambda a, d: None)[0]


def test_valid_access_jwt_is_accepted():
    assert run(token(), kite_callback.AccessVerifier(TEAM, AUD, jwks=FakeJwks())) == 200


@pytest.mark.parametrize('tok', [token(aud='another-app'), token(iss='https://evil.cloudflareaccess.com'),
                                 token(exp_minutes=-5), token(key=OTHER_KEY), 'not-a-jwt'])
def test_invalid_access_jwt_is_403(tok):
    """Wrong audience, wrong issuer, expired, signed by a foreign key, or garbage: refused."""
    assert run(tok, kite_callback.AccessVerifier(TEAM, AUD, jwks=FakeJwks())) == 403


def test_unreachable_keys_and_missing_config_fail_closed():
    down = FakeJwks(error=jwt.PyJWKClientConnectionError('timeout'))
    assert run(token(), kite_callback.AccessVerifier(TEAM, AUD, jwks=down)) == 503
    assert run(token(), kite_callback.AccessVerifier('', '')) == 503


def test_server_log_line_drops_the_query():
    """The http.server access log must not contain the request_token."""
    records = []

    class H(kite_callback.Handler):
        def __init__(self):        # no socket
            self.command, self.path = 'GET', OK_PATH

    handler = logging.Handler()
    handler.emit = records.append
    kite_callback.logger.addHandler(handler)
    try:
        kite_callback.logger.setLevel(logging.INFO)
        H().log_message('"%s" %s %s', 'GET ...', '200', '-')
    finally:
        kite_callback.logger.removeHandler(handler)
    text = ' '.join(r.getMessage() for r in records)
    assert '/kite/callback' in text and REQ not in text
