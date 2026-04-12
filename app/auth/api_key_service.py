"""API Key CRUD服务"""

import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from app.auth.models import ApiKey
from app.auth.service import generate_api_key, hash_api_key, mask_api_key


def create_api_key(
    db: Session,
    user_id: str,
    name: str = "",
) -> tuple[ApiKey, str]:
    """创建新的API Key

    返回 (db_record, raw_key) - raw_key 只在此方法中返回一次
    """
    raw_key = generate_api_key()
    record = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user_id,
        key_prefix=raw_key[:12],
        key_hash=hash_api_key(raw_key),
        name=name,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, raw_key


def get_api_keys(db: Session, user_id: str) -> List[ApiKey]:
    """列出用户所有 API Key（不返回完整key）"""
    return (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )


def verify_api_key(db: Session, raw_key: str) -> Optional[str]:
    """验证API Key，返回user_id或None"""
    key_prefix = raw_key[:12]
    key_record = (
        db.query(ApiKey)
        .filter(ApiKey.key_prefix == key_prefix, ApiKey.status == "active")
        .first()
    )
    if not key_record:
        return None

    from app.auth.service import verify_api_key as _verify
    if not _verify(raw_key, key_record.key_hash):
        return None

    # 更新最后使用时间
    key_record.last_used_at = datetime.utcnow()
    db.commit()
    return key_record.user_id


def delete_api_key(db: Session, key_id: str, user_id: str) -> bool:
    """删除 API Key，成功返回 True"""
    record = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.user_id == user_id)
        .first()
    )
    if not record:
        return False
    db.delete(record)
    db.commit()
    return True


def disable_api_key(db: Session, key_id: str, user_id: str) -> bool:
    """禁用 API Key"""
    record = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.user_id == user_id)
        .first()
    )
    if not record:
        return False
    record.status = "disabled"
    db.commit()
    return True
