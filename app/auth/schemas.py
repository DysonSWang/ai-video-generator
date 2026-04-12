"""Auth Pydantic Schemas - 请求/响应模型"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ========== User Schemas ==========

class UserCreate(BaseModel):
    username: str
    password: str
    nickname: str = ""


class UserResponse(BaseModel):
    id: str
    username: str
    nickname: str
    balance: float
    status: str
    is_admin: int
    created_at: datetime

    class Config:
        from_attributes = True


class UserDetailResponse(UserResponse):
    task_count: int = 0
    video_duration_seconds: int = 0
    api_key_count: int = 0


# ========== Auth Schemas ==========

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


class MeResponse(BaseModel):
    id: str
    username: str
    nickname: str
    balance: float
    status: str
    is_admin: int


# ========== API Key Schemas ==========

class ApiKeyCreate(BaseModel):
    name: str = ""


class ApiKeyResponse(BaseModel):
    id: str
    key_prefix: str
    name: str
    status: str
    last_used_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyCreateResponse(BaseModel):
    id: str
    api_key: str  # 只有创建时返回一次完整 key
    key_prefix: str
    name: str


# ========== Usage Schemas ==========

class UsageSummary(BaseModel):
    month_key: str
    task_count: int
    video_duration_seconds: int


class UsageHistoryItem(BaseModel):
    month_key: str
    task_count: int
    video_duration_seconds: int


# ========== Billing Schemas ==========

class BalanceResponse(BaseModel):
    balance: float


class BalanceTransactionResponse(BaseModel):
    id: str
    amount: float
    transaction_type: str
    balance_before: float
    balance_after: float
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class BalanceAdjustRequest(BaseModel):
    amount: float
    description: str = ""


# ========== Voice Profile Schemas ==========

class VoiceProfileResponse(BaseModel):
    id: str
    voice_uri: str
    voice_name: str
    reference_audio: str
    reference_text: str
    usage_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class VoiceSynthesizeRequest(BaseModel):
    text: str
    output_path: Optional[str] = None
    speed: float = 1.0
