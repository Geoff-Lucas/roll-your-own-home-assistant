from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import func, select

from ..db import SessionDep
from ..models import Account, Event
from ..security.crypto import encrypt
from ..sync import status as sync_status

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    provider: str
    display_name: str
    person_name: str
    color: str = "#4285F4"
    caldav_url: Optional[str] = None
    username: Optional[str] = None
    credential: Optional[str] = None  # plaintext in the request only; encrypted before storage


class AccountRead(BaseModel):
    """Deliberately omits encrypted_credential — never returned over the API."""

    id: int
    provider: str
    display_name: str
    person_name: str
    color: str
    caldav_url: Optional[str] = None
    username: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=List[AccountRead])
def list_accounts(session: SessionDep) -> List[Account]:
    return session.exec(select(Account)).all()


@router.get("/sync-problems")
def list_sync_problems(session: SessionDep) -> List[dict]:
    """Calendar accounts that aren't syncing and should be shown as such
    (see app/sync/status.py for which failures count, and when)."""
    newest = session.exec(select(Event.account_id, func.max(Event.last_synced_at)).group_by(Event.account_id)).all()
    # Stored as naive UTC (see time_utils.to_naive_utc).
    last_synced = {account_id: when.replace(tzinfo=timezone.utc) for account_id, when in newest if when}
    return sync_status.problems(session.exec(select(Account)).all(), last_synced=last_synced)


@router.post("", response_model=AccountRead, status_code=201)
def create_account(payload: AccountCreate, session: SessionDep) -> Account:
    account = Account(
        provider=payload.provider,
        display_name=payload.display_name,
        person_name=payload.person_name,
        color=payload.color,
        caldav_url=payload.caldav_url,
        username=payload.username,
        encrypted_credential=encrypt(payload.credential) if payload.credential else None,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, session: SessionDep) -> None:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    session.delete(account)
    session.commit()
    sync_status.forget(account_id)
