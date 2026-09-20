from typing import Tuple

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from ..config import settings

# Google's CalDAV requires OAuth 2.0 exclusively (basic auth stopped working
# mid-2023, confirmed against Google's own developer docs). `calendar` scope
# for read/write CalDAV access; `userinfo.email` so we can build the CalDAV
# URL (it's keyed by email address) without asking the user to type it in.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

CALDAV_URL_TEMPLATE = "https://apidata.googleusercontent.com/caldav/v2/{email}/user"

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.google_oauth_redirect_uri],
        }
    }


def build_authorization_url(state: str) -> Tuple[str, str]:
    """Returns (authorization_url, code_verifier).

    PKCE is enabled automatically by google-auth-oauthlib — the Flow object
    generates a code_verifier and sends its hash (code_challenge) as part of
    the authorization URL. The verifier itself has to be presented again at
    token-exchange time to prove it's the same client, but /start and
    /callback are two separate HTTP requests (and, in this Flow library, two
    separate Flow instances) — so the caller must persist code_verifier
    (see routers/google_oauth.py's _pending dict) and pass it back into
    exchange_code(). Losing it produces Google's "Missing code verifier"
    invalid_grant error — confirmed the hard way against a real account.
    """
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_oauth_redirect_uri
    # access_type=offline + prompt=consent: without both, Google often
    # omits the refresh_token on repeat authorizations (only ever sends it
    # the very first time otherwise), which is exactly the piece we need
    # to keep long-term access without asking the household to re-consent.
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return url, flow.code_verifier


def exchange_code(code: str, code_verifier: str) -> Tuple[str, str]:
    """Exchanges an OAuth authorization code for (refresh_token, email)."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_oauth_redirect_uri
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    credentials = flow.credentials
    email = _fetch_email(credentials.token)
    return credentials.refresh_token, email


def _fetch_email(access_token: str) -> str:
    response = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["email"]


def get_valid_access_token(refresh_token: str) -> str:
    """Access tokens expire in ~1 hour; this always mints a fresh one from
    the (long-lived) refresh token rather than trying to cache/track expiry
    — one extra round trip per sync cycle, simple and correct."""
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=SCOPES,
    )
    credentials.refresh(GoogleAuthRequest())
    return credentials.token
