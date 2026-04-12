#!/usr/bin/env python3
"""OmniVoice 任务管理器 - 通过 Gradio SSE API 追踪异步任务"""

import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Tuple
from app.config import OMNIVOICE_GRADIO_URL

MANAGER_DB = Path(__file__).parent.parent.parent / "omnivoice_tasks.db"

_no_proxy_session = None

def _get_session():
    global _no_proxy_session
    if _no_proxy_session is None:
        import requests
        _no_proxy_session = requests.Session()
        _no_proxy_session.trust_env = False
    return _no_proxy_session


def init_db():
    """初始化任务数据库"""
    conn = sqlite3.connect(MANAGER_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS omni_task_records (
            event_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            voice_name TEXT,
            text TEXT,
            status TEXT DEFAULT 'pending',
            result_file TEXT,
            result_duration REAL,
            submission_time REAL NOT NULL,
            completed_time REAL,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("DELETE FROM omni_task_records WHERE created_at < datetime('now', '-7 days')")
    conn.commit()
    conn.close()


def record_submission(event_id: str, task_id: str, voice_name: str = "", text: str = "") -> None:
    """记录一次任务提交"""
    conn = sqlite3.connect(MANAGER_DB)
    conn.execute(
        """INSERT OR REPLACE INTO omni_task_records
           (event_id, task_id, voice_name, text, submission_time, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (event_id, task_id, voice_name, text, time.time())
    )
    conn.commit()
    conn.close()


def update_result(event_id: str, status: str, result_file: str = None,
                  duration: float = None, error: str = None) -> None:
    """更新任务结果"""
    conn = sqlite3.connect(MANAGER_DB)
    if status == 'completed':
        conn.execute(
            """UPDATE omni_task_records
               SET status=?, result_file=?, result_duration=?, completed_time=?
               WHERE event_id=?""",
            (status, result_file, duration, time.time(), event_id)
        )
    else:
        conn.execute(
            "UPDATE omni_task_records SET status=?, error=? WHERE event_id=?",
            (status, error, event_id)
        )
    conn.commit()
    conn.close()


def mark_completed(event_id: str, result_file: str, duration: float = None) -> None:
    """标记任务完成"""
    conn = sqlite3.connect(MANAGER_DB)
    conn.execute(
        "UPDATE omni_task_records SET status='completed', result_file=?, result_duration=?, completed_time=? WHERE event_id=?",
        (result_file, duration, time.time(), event_id)
    )
    conn.commit()
    conn.close()


def mark_failed(event_id: str, error: str) -> None:
    """标记任务失败"""
    conn = sqlite3.connect(MANAGER_DB)
    conn.execute(
        "UPDATE omni_task_records SET status='failed', error=? WHERE event_id=?",
        (error, event_id)
    )
    conn.commit()
    conn.close()


def get_pending_tasks() -> List[Tuple]:
    """获取所有 pending 状态的任务"""
    conn = sqlite3.connect(MANAGER_DB)
    rows = conn.execute(
        "SELECT event_id, task_id, submission_time FROM omni_task_records WHERE status='pending' ORDER BY submission_time"
    ).fetchall()
    conn.close()
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

        # 解析 SSE 格式响应，data: [...]

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

                        # 状态: "✅ 完成" / "⏳ 等待中" / "❌ 错误"
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


# 初始化数据库
init_db()
