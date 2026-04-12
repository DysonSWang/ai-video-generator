"""Auth服务 - JWT生成/验证、密码哈希、token管理"""

import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from app.config import (
    JWT_SECRET,
    JWT_ALGORITHM,
    TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)


def get_password_hash(password: str) -> str:
    """bcrypt哈希密码"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    """创建JWT access token"""
    if expires_delta is None:
        expires_delta = timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    expire = datetime.utcnow() + expires_delta
    to_encode = {
        "sub": user_id,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """创建JWT refresh token"""
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[dict]:
    """验证JWT token，返回payload或None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def hash_token(token: str) -> str:
    """哈希token，用于存储"""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_key() -> str:
    """生成API Key: sk_live_ + 32字节随机字符串"""
    random_part = secrets.token_hex(16)  # 32 chars
    return f"sk_live_{random_part}"


def mask_api_key(api_key: str) -> str:
    """返回API Key前缀（用于显示）"""
    if len(api_key) <= 12:
        return api_key
    return api_key[:8] + "..." + api_key[-4:]


def hash_api_key(api_key: str) -> str:
    """哈希API Key用于存储"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """验证API Key"""
    return hash_api_key(api_key) == key_hash
