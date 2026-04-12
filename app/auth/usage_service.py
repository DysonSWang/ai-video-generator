"""用量记录服务 - 记录任务数 + 视频总时长"""

import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from app.auth.models import UsageRecord


def record_usage(
    db: Session,
    user_id: str,
    usage_type: str,  # "task_count" / "video_duration_seconds"
    amount: int,
    task_id: str = None,
):
    """写入单条用量记录

    用量按月聚合，month_key 格式 "2026-04"
    """
    month_key = datetime.utcnow().strftime("%Y-%m")
    record = UsageRecord(
        id=str(uuid.uuid4()),
        user_id=user_id,
        usage_type=usage_type,
        amount=amount,
        month_key=month_key,
        task_id=task_id,
    )
    db.add(record)
    db.commit()
    return record


def get_usage_summary(db: Session, user_id: str, month_key: str = None) -> dict:
    """获取指定月份的用量汇总"""
    if month_key is None:
        month_key = datetime.utcnow().strftime("%Y-%m")

    records = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user_id, UsageRecord.month_key == month_key)
        .all()
    )

    task_count = 0
    video_duration_seconds = 0

    for r in records:
        if r.usage_type == "task_count":
            task_count += r.amount
        elif r.usage_type == "video_duration_seconds":
            video_duration_seconds += r.amount

    return {
        "month_key": month_key,
        "task_count": task_count,
        "video_duration_seconds": video_duration_seconds,
    }


def get_usage_history(db: Session, user_id: str, limit: int = 12) -> list:
    """获取最近N个月的用量历史"""
    records = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user_id)
        .order_by(UsageRecord.month_key.desc())
        .limit(limit)
        .all()
    )

    # 按月聚合
    monthly = {}
    for r in records:
        if r.month_key not in monthly:
            monthly[r.month_key] = {"task_count": 0, "video_duration_seconds": 0}
        if r.usage_type == "task_count":
            monthly[r.month_key]["task_count"] += r.amount
        elif r.usage_type == "video_duration_seconds":
            monthly[r.month_key]["video_duration_seconds"] += r.amount

    result = []
    for month, data in sorted(monthly.items(), reverse=True):
        result.append({
            "month_key": month,
            "task_count": data["task_count"],
            "video_duration_seconds": data["video_duration_seconds"],
        })
    return result
