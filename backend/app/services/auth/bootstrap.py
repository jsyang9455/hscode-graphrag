"""Ensure demo office/user exists for first-time AWS/local installs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import Office, User
from backend.app.services.auth.security import hash_password

DEMO_EMAIL = "test@demo-customs.com"
DEMO_PASSWORD = "Test1234!"
DEMO_OFFICE_CODE = "DEMO-01"
DEMO_OFFICE_NAME = "데모관세사무소"
DEMO_FULL_NAME = "테스트관세사"


def ensure_demo_account(db: Session) -> dict[str, Any]:
    """Idempotent: create DEMO-01 office + test broker if missing."""
    office = db.query(Office).filter(Office.code == DEMO_OFFICE_CODE).first()
    created_office = False
    if not office:
        office = Office(code=DEMO_OFFICE_CODE, name=DEMO_OFFICE_NAME)
        db.add(office)
        db.flush()
        created_office = True

    user = (
        db.query(User)
        .filter(User.office_id == office.id, User.email == DEMO_EMAIL)
        .first()
    )
    created_user = False
    if not user:
        user = User(
            office_id=office.id,
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            full_name=DEMO_FULL_NAME,
            role="broker",
        )
        db.add(user)
        created_user = True

    if created_office or created_user:
        db.commit()
        db.refresh(user)
        db.refresh(office)
    else:
        db.rollback()

    return {
        "email": DEMO_EMAIL,
        "office_code": DEMO_OFFICE_CODE,
        "office_name": office.name,
        "created_office": created_office,
        "created_user": created_user,
        "user_id": user.id,
        "office_id": office.id,
    }
