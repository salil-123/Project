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


def verify_google(credential: str) -> dict:
    """Check a Google ID token and return {email, name, picture}. Raises ValueError if it's not one
    Google issued for OUR client id, or the email isn't verified."""
    if not google_enabled():
        raise ValueError("Google sign-in isn't configured on this server")
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token
    info = id_token.verify_oauth2_token(credential, g_requests.Request(), config.GOOGLE_CLIENT_ID)
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
