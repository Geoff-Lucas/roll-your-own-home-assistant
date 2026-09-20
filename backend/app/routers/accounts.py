from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from ..db import SessionDep
from ..models import Account
from ..security.crypto import encrypt

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
