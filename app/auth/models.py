"""Auth数据模型 - SQLAlchemy ORM"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.auth.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    nickname = Column(String(128), default="")
    balance = Column(Float, default=0.0)
    status = Column(String(16), default="active")  # active / suspended
    is_admin = Column(Integer, default=0)  # 1=管理员
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tokens = relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user", cascade="all, delete-orphan")
    balance_transactions = relationship("BalanceTransaction", back_populates="user", cascade="all, delete-orphan")
    voice_profiles = relationship("VoiceProfile", back_populates="user", cascade="all, delete-orphan")


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(256), nullable=False)  # hash of the JWT
    token_type = Column(String(16), default="access")  # access / refresh
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="tokens")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_prefix = Column(String(32), nullable=False)  # "sk_live_xxxx" 前缀
    key_hash = Column(String(256), nullable=False)  # hash of the full key
    name = Column(String(128), default="")
    status = Column(String(16), default="active")  # active / disabled
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="api_keys")

    __table_args__ = (
        Index("idx_api_keys_user_id", "user_id"),
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    usage_type = Column(String(32), nullable=False)  # task_count / video_duration_seconds
    amount = Column(Integer, nullable=False)  # 任务数(1) 或 视频秒数
    month_key = Column(String(7), nullable=False)  # "2026-04"
    task_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="usage_records")

    __table_args__ = (
        Index("idx_usage_user_month", "user_id", "month_key"),
    )


class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)  # 正=充值，负=消费
    transaction_type = Column(String(32), nullable=False)  # recharge / adjust
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(Text, default="")
    task_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="balance_transactions")

    __table_args__ = (
        Index("idx_balance_user_id", "user_id"),
    )


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    voice_uri = Column(String(256), nullable=False)  # SiliconFlow 返回的音色ID
    voice_name = Column(String(128), nullable=False)
    reference_audio = Column(String(512), nullable=False)  # 用户目录下参考音频路径
    reference_text = Column(Text, default="")
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="voice_profiles")

    __table_args__ = (
        Index("idx_voice_user_id", "user_id"),
    )


class Package(Base):
    __tablename__ = "packages"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    price = Column(Float, nullable=False)
    video_cnt = Column(Integer, default=0)
    valid_days = Column(Integer, default=30)
    status = Column(String(16), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemConfig(Base):
    """系统配置（key-value）"""
    __tablename__ = "system_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)  # JSON 字符串存储
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(36), nullable=True)
