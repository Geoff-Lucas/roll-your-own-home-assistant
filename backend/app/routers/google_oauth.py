import secrets
from typing import Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import SessionDep
from ..models import Account
from ..security.crypto import encrypt
from ..sync.google_oauth import CALDAV_URL_TEMPLATE, build_authorization_url, exchange_code

router = APIRouter(prefix="/google-oauth", tags=["google-oauth"])

# Pending link requests: state token -> the new account's details, filled in
# once Google redirects back to /callback. In-memory and short-lived by
# design — a link flow completes in the same browser session within a
# couple of minutes, no need for database persistence of a token that's
# meaningless once used.
_pending: Dict[str, dict] = {}


@router.get("/start")
def start_link(person_name: str, display_name: str, color: str = "#4285F4") -> RedirectResponse:
    """Visit this URL directly in a browser to link a Google account —
    there's no dedicated frontend UI for this yet (see PLAN.md, account
    linking has always been API/URL-driven so far). Redirects to Google's
    own login+consent screen; we never see the household member's Google
    password, only get a token back via the /callback redirect.
    """
    state = secrets.token_urlsafe(16)
    authorization_url, code_verifier = build_authorization_url(state)
    # code_verifier must survive to /callback (a separate request, separate
    # Flow instance) for PKCE token exchange to succeed — see
    # sync/google_oauth.py's build_authorization_url docstring.
    _pending[state] = {
        "person_name": person_name,
        "display_name": display_name,
        "color": color,
        "code_verifier": code_verifier,
    }
    return RedirectResponse(authorization_url)


@router.get("/callback")
def oauth_callback(session: SessionDep, code: str = Query(...), state: str = Query(...)) -> HTMLResponse:
    pending = _pending.pop(state, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="Unknown or expired link request — start over from /start")

    refresh_token, email = exchange_code(code, pending["code_verifier"])

    account = Account(
        provider="google",
        display_name=pending["display_name"],
        person_name=pending["person_name"],
        color=pending["color"],
        caldav_url=CALDAV_URL_TEMPLATE.format(email=email),
        username=email,
        oauth_refresh_token=encrypt(refresh_token),
    )
    session.add(account)
    session.commit()

    return HTMLResponse(
        f"<html><body style='font-family: sans-serif; padding: 2rem;'>"
        f"<h2>Google Calendar linked ✅</h2>"
        f"<p>{email} is now linked as {pending['person_name']} — {pending['display_name']}.</p>"
        f"<p>You can close this tab.</p>"
        f"</body></html>"
    )
