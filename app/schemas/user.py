from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict
from app.models.user import UserRole


# Common properties shared by all User schemas
class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = True
    username: Optional[str] = None
    role: UserRole = UserRole.USER


# Properties to receive via API on creation
class UserCreate(UserBase):
    email: EmailStr
    username: str
    password: str
    role: UserRole = UserRole.USER


# Properties to receive via API on update
class UserUpdate(UserBase):
    password: Optional[str] = None


# Properties to return to the user via API (Response)
class User(UserBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    # This allows Pydantic to read data from SQLAlchemy models (objects)
    model_config = ConfigDict(from_attributes=True)
