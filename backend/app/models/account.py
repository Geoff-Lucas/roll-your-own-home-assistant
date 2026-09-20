from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Account(SQLModel, table=True):
    """A linked calendar account (CalDAV: iCloud, Google, or generic)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str  # "icloud" | "google" | "caldav"
    display_name: str
    person_name: str  # which household member this belongs to
    color: str = "#4285F4"
    caldav_url: Optional[str] = None
    username: Optional[str] = None

    # Fernet-encrypted app-specific password / token, for basic-auth CalDAV
    # (iCloud, generic CalDAV). Never serialize this back out over the API —
    # see routers/accounts.py AccountRead.
    encrypted_credential: Optional[bytes] = None

    # Fernet-encrypted OAuth refresh token, for Google specifically — its
    # CalDAV requires OAuth exclusively, see app/sync/google_oauth.py. An
    # account has either this or encrypted_credential, never both;
    # caldav_client.py branches on which one is set.
    oauth_refresh_token: Optional[bytes] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
