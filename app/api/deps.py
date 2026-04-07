from typing import Generator, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import UserModel
from app.db.session import SessionLocal


def get_db() -> Generator:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


def get_current_user(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> UserModel:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header",
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-User-Id header",
        ) from exc

    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
