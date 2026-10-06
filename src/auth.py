"""Sign-in: Google SSO verified on the server, then a signed session cookie.

The browser half is Susmit's (Google Identity Services, no token in localStorage). The server half
is not: he trusts an X-User-Email header, which the cluster checklist rules out ("validated on the
backend"). Here the page hands us Google's signed ID token once, we check its signature, audience
and expiry against GOOGLE_CLIENT_ID, and answer with an HttpOnly cookie. From then on every call,
including a bare GeoTIFF link, carries the cookie, and nothing in the page can forge it.

No GOOGLE_CLIENT_ID (a laptop) -> the dev login: type a name, get a local account. It switches itself
off the moment a client id is configured, so it can't survive onto the tower.
"""
import logging
import re
import secrets
import time

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import config

log = logging.getLogger("corestack.auth")

COOKIE = "corestack_lulc_session"   # every app on www.cse.iitd.ernet.in shares one cookie jar (path=/), so the name is ours alone
DEV_DOMAIN = "local.dev"          # dev accounts look like name@local.dev, never a real address


def google_enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID)


def dev_login_allowed() -> bool:
    return not google_enabled()


def _secret() -> str:
    """SESSION_SECRET from .env; failing that a random one kept in data/, so a restart doesn't sign
    everybody out. Random either way, never a constant in the code."""
    if config.SESSION_SECRET:
        return config.SESSION_SECRET
    f = config.DATA_DIR / ".session_secret"
    if not f.exists():
        if google_enabled():
            log.warning("SESSION_SECRET is unset on a deploy with Google sign-in; using a generated one "
                        "in data/. Set it in .env so every replica signs cookies the same way.")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_urlsafe(48))
    return f.read_text().strip()


def _signer():
    return URLSafeTimedSerializer(_secret(), salt="corestack-session")


def make_cookie(email: str) -> str:
    return _signer().dumps({"email": email})


def read_cookie(value: str | None) -> str | None:
    """The signed-in email, or None for a missing, tampered or expired cookie."""
    if not value:
        return None
    try:
        return _signer().loads(value, max_age=config.SESSION_DAYS * 86400).get("email")
    except (BadSignature, SignatureExpired):
        return None


# Google's signing keys, fetched once an hour rather than on every sign-in. google-auth's own helper
# waits up to two minutes when the server can't reach Google, which nginx turns into a frozen page.
CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
_certs = {"keys": None, "at": 0.0}


class GoogleUnreachable(RuntimeError):
    """The server couldn't fetch Google's keys, so it can't check anyone's sign-in right now."""


_pool = None


def with_deadline(fn, seconds, *args, **kw):
    """Run fn with a hard wall-clock limit. requests' own timeout doesn't cover the DNS lookup, and on
    a box whose DNS hangs that lookup alone outlives nginx's 60 s, so the call runs on a side thread
    and we stop waiting for it (raises TimeoutError)."""
    global _pool
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as Late
    _pool = _pool or ThreadPoolExecutor(max_workers=4, thread_name_prefix="deadline")
    try:
        return _pool.submit(fn, *args, **kw).result(timeout=seconds)
    except Late:
        raise TimeoutError(f"no answer within {seconds} s") from None


def _google_certs() -> dict:
    if _certs["keys"] and time.time() - _certs["at"] < 3600:
        return _certs["keys"]
    import requests
    try:
        r = with_deadline(requests.get, 10, CERTS_URL, timeout=8)
        r.raise_for_status()
    except (requests.RequestException, TimeoutError) as e:
        log.error("couldn't fetch Google's sign-in keys from %s: %s", CERTS_URL, e)
        if _certs["keys"]:
            return _certs["keys"]          # a stale key set beats locking everyone out
        raise GoogleUnreachable("the server can't reach www.googleapis.com to check the sign-in. "
                                "/api/health?deep=1 shows whether it's DNS or the proxy") from e
    _certs.update(keys=r.json(), at=time.time())
    return _certs["keys"]


def verify_google(credential: str) -> dict:
    """Check a Google ID token and return {email, name, picture}. Raises ValueError if it's not one
    Google issued for OUR client id, or the email isn't verified."""
    if not google_enabled():
        raise ValueError("Google sign-in isn't configured on this server")
    from google.auth import jwt
    info = jwt.decode(credential, certs=_google_certs(), audience=config.GOOGLE_CLIENT_ID,
                      clock_skew_in_seconds=10)
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("that token wasn't issued by Google")
    if not info.get("email") or not info.get("email_verified"):
        raise ValueError("this Google account has no verified email")
    return {"email": info["email"].lower(), "name": info.get("name") or info["email"],
            "picture": info.get("picture")}


def dev_identity(name: str) -> dict:
    """A local account from a typed name: 'Salil G' -> salil_g@local.dev."""
    if not dev_login_allowed():
        raise ValueError("the local login is off because Google sign-in is configured")
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")[:40]
    if not slug:
        raise ValueError("type a name to sign in locally")
    return {"email": f"{slug}@{DEV_DOMAIN}", "name": name.strip(), "picture": None}
