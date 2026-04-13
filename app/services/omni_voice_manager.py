#!/usr/bin/env python3
"""OmniVoice 任务管理器 - 通过 Gradio SSE API 追踪异步任务"""

import time
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from app.config import OMNIVOICE_GRADIO_URL

_no_proxy_session = None

def _get_session():
    global _no_proxy_session
    if _no_proxy_session is None:
        import requests
        _no_proxy_session = requests.Session()
        _no_proxy_session.trust_env = False
    return _no_proxy_session


def init_db(db: Session):
    """初始化任务数据库（通过 SQLAlchemy）"""
    from app.auth.models import OmniTaskRecord
    db.execute(f"CREATE TABLE IF NOT EXISTS omni_task_records "
               "(event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, voice_name TEXT, text TEXT, "
               "status TEXT DEFAULT 'pending', result_file TEXT, result_duration REAL, "
               "submission_time REAL NOT NULL, completed_time REAL, error TEXT, "
               "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute("DELETE FROM omni_task_records WHERE created_at < datetime('now', '-7 days')")
    db.commit()


def record_submission(db: Session, event_id: str, task_id: str, voice_name: str = "", text: str = "") -> None:
    """记录一次任务提交"""
    from app.auth.models import OmniTaskRecord
    import uuid as _uuid
    record = OmniTaskRecord(
        event_id=event_id,
        task_id=task_id,
        voice_name=voice_name,
        text=text,
        status="pending",
        submission_time=time.time(),
    )
    db.merge(record)
    db.commit()


def update_result(db: Session, event_id: str, status: str, result_file: str = None,
                  duration: float = None, error: str = None) -> None:
    """更新任务结果"""
    from app.auth.models import OmniTaskRecord
    record = db.query(OmniTaskRecord).filter(OmniTaskRecord.event_id == event_id).first()
    if not record:
        return
    record.status = status
    if status == "completed":
        record.result_file = result_file
        record.result_duration = duration
        record.completed_time = time.time()
    else:
        record.error = error
    db.commit()


def mark_completed(db: Session, event_id: str, result_file: str, duration: float = None) -> None:
    """标记任务完成"""
    update_result(db, event_id, "completed", result_file, duration)


def mark_failed(db: Session, event_id: str, error: str) -> None:
    """标记任务失败"""
    update_result(db, event_id, "failed", error=error)


def get_pending_tasks(db: Session) -> List[Tuple]:
    """获取所有 pending 状态的任务"""
    from app.auth.models import OmniTaskRecord
    rows = db.query(OmniTaskRecord.event_id, OmniTaskRecord.task_id, OmniTaskRecord.submission_time).filter(
        OmniTaskRecord.status == "pending"
    ).order_by(OmniTaskRecord.submission_time).all()
    return rows


def poll_task_status(event_id: str) -> Optional[dict]:
    """通过 Gradio SSE API 轮询任务状态

    OmniVoice Gradio 返回的是事件流格式，每个 event_id 包含所有历史任务记录。
    返回格式示例:
        event: complete
        data: [{"headers": [...], "data": [[id, 模式, 状态, 内容, 输出文件], ...]}]

    Returns:
        None  = 仍在进行中
        dict  = 完成或出错，dict 包含:
          - status: 'completed' | 'error'
          - task_id: str
          - output_file: str (completed时)
          - content: str (输出内容/文件名)
          - message: str (error时)
    """
    try:
        session = _get_session()
        resp = session.get(
            f"{OMNIVOICE_GRADIO_URL}/gradio_api/call/add_clone_task/{event_id}",
            timeout=10
        )
        if resp.status_code != 200:
            return None

        text = resp.text

        for line in text.strip().split('\n'):
            if line.startswith('data: '):
                import json
                try:
                    data = json.loads(line[6:])
                    if not (data and isinstance(data, list) and len(data) > 0):
                        continue

                    rows = data[0].get('data', [])
                    for row in rows:
                        if not isinstance(row, (list, tuple)) or len(row) < 4:
                            continue

                        task_id_from_row = str(row[0]) if row[0] else ''
                        mode = str(row[1]) if len(row) > 1 and row[1] else ''
                        status = str(row[2]) if len(row) > 2 and row[2] else ''
                        content = str(row[3]) if len(row) > 3 and row[3] else ''
                        output_file = str(row[4]) if len(row) > 4 and row[4] else ''

                        is_complete = '完成' in status or 'complete' in status.lower()
                        is_error = 'error' in status.lower() or '错误' in status or '失败' in status

                        if is_complete:
                            return {
                                'status': 'completed',
                                'task_id': task_id_from_row,
                                'output_file': output_file,
                                'content': content,
                                'mode': mode
                            }
                        elif is_error:
                            return {
                                'status': 'error',
                                'task_id': task_id_from_row,
                                'message': f"{status}: {content}"
                            }
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue

        return None

    except Exception as e:
        print(f">>> OmniVoice 轮询出错: {e}")
        return None
