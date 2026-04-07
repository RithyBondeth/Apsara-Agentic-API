from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None


class UserCreate(UserBase):
    email: EmailStr
    username: str
    password: str


class UserUpdate(UserBase):
    password: Optional[str] = None


class User(UserBase):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
