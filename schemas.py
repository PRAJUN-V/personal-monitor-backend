from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator, ConfigDict


# ---------- Auth ----------
class UserCreate(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


# ---------- User management (admin) ----------
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool


class AdminUserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None

    @field_validator("username", "password", mode="before")
    @classmethod
    def empty_string_to_null(cls, v):
        return None if v == "" else v


# ---------- Health ----------
class HealthRecordCreate(BaseModel):
    date: Optional[str] = None
    height: float
    weight: float
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        return str(v) if v else None

    @field_validator("bp_systolic", "bp_diastolic", mode="before")
    @classmethod
    def empty_string_to_null(cls, v):
        return None if v == "" else v


class HealthRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    height: float
    weight: float
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    bmi: float
    category: str
    weight_diff_to_normal: float


# ---------- Finance ----------
class SourceCreate(BaseModel):
    name: str
    balance: float = 0.0


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    balance: float


class TransactionCreate(BaseModel):
    source_id: int
    amount: float
    type: str  # "income" or "expense"
    category: str
    date: Optional[str] = None  # ISO format, optionally with time
    description: Optional[str] = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        return str(v) if v else None


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    source_name: Optional[str] = None
    amount: float
    type: str
    category: str
    date: datetime
    description: Optional[str] = None
