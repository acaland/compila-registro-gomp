from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urljoin, urlparse

import requests

from .client import GompClient, SessionExpired


CAS_LOGIN = 'https://iam.unict.it/cas/login'
PORTAL_SERVICE = 'https://docenti.smartedu.unict.it/WorkFlow2011/Logon/Logon.aspx'
PORTAL_SSO = 'https://docenti.smartedu.unict.it/NetCoreSignOn'
REGISTER_PATH = '/Professors/ActivityReport'

DEFAULT_COOKIE_FILE = Path(__file__).resolve().parent / 'auth' / 'cookies.json'
KEYCHAIN_SERVICE = os.environ.get('GOMP_KEYCHAIN_SERVICE', 'gomp-unict')
KEYCHAIN_SERVER = 'iam.unict.it'

USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/141.0 Safari/537.36'
)


class AuthError(RuntimeError):
    pass


@dataclass
class Credentials:
    username: str
    password: str = field(repr=False)


# ── credentials ─────────────────────────────────────────────────────────────

def _security(*args: str) -> str | None:
    try:
        result = subprocess.run(['security', *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _keychain(kind: str, selector: list[str], username: str | None) -> Credentials | None:
    account = ['-a', username] if username else []
    attributes = _security(kind, *selector, *account)
    if attributes is None:
        return None
    match = re.search(r'"acct"<blob>="([^"]*)"', attributes)
    user = username or (match.group(1) if match else None)
    password = _security(kind, *selector, *account, '-w')
    if not user or password is None:
        return None
    return Credentials(user, password.rstrip('\n'))


def load_credentials() -> Credentials | None:
    """CAS username/password, never stored in the repository.

    Looked up in order:
      1. GOMP_USERNAME + GOMP_PASSWORD environment variables (CI, a future MCP server);
      2. macOS keychain, generic password with service GOMP_KEYCHAIN_SERVICE (default
         "gomp-unict"), created once with
         `security add-generic-password -s gomp-unict -a <codice fiscale> -w`;
      3. macOS keychain, internet password saved for iam.unict.it.
    macOS asks the owner to allow each keychain read. GOMP_USERNAME alone picks
    the account when the keychain holds several.
    """
    username = os.environ.get('GOMP_USERNAME')
    password = os.environ.get('GOMP_PASSWORD')
    if username and password:
        return Credentials(username, password)
    if sys.platform != 'darwin':
        return None
    return (
        _keychain('find-generic-password', ['-s', KEYCHAIN_SERVICE], username)
        or _keychain('find-internet-password', ['-s', KEYCHAIN_SERVER], username)
    )


# ── cookie persistence ──────────────────────────────────────────────────────

def new_session() -> requests.Session:
    session = requests.Session()
    session.headers['User-Agent'] = USER_AGENT
    return session


def load_cookies(session: requests.Session, path: Path = DEFAULT_COOKIE_FILE) -> None:
    if not path.exists():
        return
    for c in json.loads(path.read_text()):
        session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'],
                            secure=c['secure'], expires=c['expires'])


def save_cookies(session: requests.Session, path: Path = DEFAULT_COOKIE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cookies = [
        {'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path,
         'secure': c.secure, 'expires': c.expires}
        for c in session.cookies
    ]
    path.touch(mode=0o600, exist_ok=True)
    path.write_text(json.dumps(cookies, indent=1))
    path.chmod(0o600)


# ── login chain: CAS -> docenti portal -> NetCoreSignOn -> GOMP ──────────────

_FORM_RE = re.compile(r'<form\b([^>]*)>(.*?)</form>', re.S | re.I)
_INPUT_RE = re.compile(r'<input\b([^>]*)>', re.I)
_ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def _attrs(tag: str) -> dict[str, str]:
    return {k.lower(): html.unescape(v) for k, v in _ATTR_RE.findall(tag)}


def _form_fields(form_body: str) -> dict[str, str]:
    fields = {}
    for tag in _INPUT_RE.findall(form_body):
        a = _attrs(tag)
        if 'name' in a and a.get('type', 'text').lower() not in {'submit', 'button'}:
            fields[a['name']] = a.get('value', '')
    return fields


def _follow_autopost(session: requests.Session, response: requests.Response) -> requests.Response:
    """Some hops hand over with a self-submitting form (SAML/ASP.NET style)."""
    for _ in range(3):
        text = response.text if 'html' in response.headers.get('content-type', '') else ''
        if not re.search(r'\.submit\(\)|onload\s*=\s*"[^"]*submit', text, re.I):
            return response
        match = _FORM_RE.search(text)
        if not match:
            return response
        form = _attrs(match.group(1))
        action = urljoin(response.url, form.get('action', response.url))
        response = session.post(action, data=_form_fields(match.group(2)), timeout=60)
    return response


def _on_cas_login(response: requests.Response) -> bool:
    url = urlparse(response.url)
    return url.netloc == 'iam.unict.it' and url.path.startswith('/cas/login')


def cas_login(session: requests.Session, credentials: Credentials) -> None:
    """Username/password login on the university CAS, landing on the docenti portal."""
    response = session.get(CAS_LOGIN, params={'service': PORTAL_SERVICE}, timeout=60)
    if _on_cas_login(response):
        form = next((m for m in _FORM_RE.finditer(response.text) if 'id="fm1"' in m.group(1)), None)
        if form is None:
            raise AuthError('CAS login form not found: the page layout changed.')
        fields = _form_fields(form.group(2))
        fields.update({'username': credentials.username, 'password': credentials.password,
                       '_eventId': 'submit'})
        response = session.post(response.url, data=fields, timeout=60)
    response = _follow_autopost(session, response)
    if _on_cas_login(response):
        raise AuthError('CAS refused the login (wrong credentials, or it asks for a second factor).')


def portal_sso(session: requests.Session) -> bool:
    """Ask the docenti portal to sign us into GOMP. True when we land on the register."""
    for _ in range(2):
        response = session.get(PORTAL_SSO, params={'url': REGISTER_PATH}, timeout=60)
        response = _follow_autopost(session, response)
        if _on_cas_login(response):
            return False
        if urlparse(response.url).netloc.endswith('gomp.it') and '/Login' not in response.url:
            return True
        # Landed back on the portal after a silent CAS round trip: try once more.
    return False


def open_client(auto_login: bool = True, cookie_file: Path = DEFAULT_COOKIE_FILE) -> GompClient:
    """A GompClient with a working session, renewing it as cheaply as possible.

    1. saved cookies, if GOMP still accepts them;
    2. single sign-on from the portal, which works without a password while the
       CAS or portal session is still alive;
    3. a full CAS login with stored credentials (only with auto_login).
    """
    session = new_session()
    load_cookies(session, cookie_file)
    client = GompClient(session)
    if client.is_authenticated():
        return client
    if portal_sso(session) and client.is_authenticated():
        save_cookies(session, cookie_file)
        return client
    if not auto_login:
        raise SessionExpired('GOMP session expired and automatic login is off: run `python -m gomp login`.')
    credentials = load_credentials()
    if credentials is None:
        raise AuthError('No CAS credentials found (environment or macOS keychain): see gomp/README.md.')
    cas_login(session, credentials)
    if not (portal_sso(session) and client.is_authenticated()):
        raise AuthError('CAS login succeeded but the GOMP single sign-on did not.')
    save_cookies(session, cookie_file)
    return client
