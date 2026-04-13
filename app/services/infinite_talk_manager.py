#!/usr/bin/env python3
"""InfiniteTalk 任务管理器 - 通过 ComfyUI API 精确追踪"""

import time
import re
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

import httpx

from app.config import INFINITETALK_URL

COMFYUI_API = "http://117.50.250.191:8188"


def init_db(db: Session):
    """初始化任务数据库"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS infinite_talk_task_records (
            event_id TEXT PRIMARY KEY,
            prompt_id TEXT,
            task_id TEXT NOT NULL,
            submission_time REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            result_file TEXT,
            result_duration REAL,
            error TEXT
        )
    """)
    db.commit()


def record_submission(db: Session, event_id: str, task_id: str) -> None:
    """记录一次任务提交"""
    from app.auth.models import InfiniteTalkTaskRecord
    record = InfiniteTalkTaskRecord(
        event_id=event_id,
        task_id=task_id,
        submission_time=time.time(),
        status="pending",
    )
    db.merge(record)
    db.commit()


def update_prompt_id(db: Session, event_id: str, prompt_id: str) -> None:
    """从 SSE 消息中提取到 prompt_id 后更新"""
    from app.auth.models import InfiniteTalkTaskRecord
    record = db.query(InfiniteTalkTaskRecord).filter(InfiniteTalkTaskRecord.event_id == event_id).first()
    if record:
        record.prompt_id = prompt_id
        db.commit()


def get_pending_tasks(db: Session) -> List[Tuple]:
    """获取所有 pending 状态的任务"""
    from app.auth.models import InfiniteTalkTaskRecord
    rows = db.query(
        InfiniteTalkTaskRecord.event_id,
        InfiniteTalkTaskRecord.prompt_id,
        InfiniteTalkTaskRecord.task_id,
        InfiniteTalkTaskRecord.submission_time
    ).filter(InfiniteTalkTaskRecord.status == "pending").order_by(
        InfiniteTalkTaskRecord.submission_time
    ).all()
    return rows


def mark_completed(db: Session, event_id: str, result_file: str, duration: float) -> None:
    """标记任务完成"""
    from app.auth.models import InfiniteTalkTaskRecord
    record = db.query(InfiniteTalkTaskRecord).filter(InfiniteTalkTaskRecord.event_id == event_id).first()
    if record:
        record.status = "completed"
        record.result_file = result_file
        record.result_duration = duration
        db.commit()


def mark_failed(db: Session, event_id: str, error: str) -> None:
    """标记任务失败"""
    from app.auth.models import InfiniteTalkTaskRecord
    record = db.query(InfiniteTalkTaskRecord).filter(InfiniteTalkTaskRecord.event_id == event_id).first()
    if record:
        record.status = "failed"
        record.error = error
        db.commit()


def get_queue_position() -> Tuple[int, int]:
    """返回 (running数量, pending数量)"""
    try:
        resp = httpx.get(f"{COMFYUI_API}/queue", timeout=10, trust_env=False)
        data = resp.json()
        running = len(data.get('queue_running', []))
        pending = len(data.get('queue_pending', []))
        return running, pending
    except Exception as e:
        print(f">>> 队列查询失败: {e}")
        return -1, -1


def check_history_completion(prompt_id: str) -> Optional[dict]:
    """查询 ComfyUI history，返回输出文件信息或 None

    优先返回 video 文件。如果只找到 audio 文件（ComfyUI 的 VHS_VideoCombine
    有时会返回 audio 而非 video），则返回 audio 信息让调用方去 SFTP 验证 video。
    """
    try:
        resp = httpx.get(f"{COMFYUI_API}/history/{prompt_id}", timeout=10, trust_env=False)
        data = resp.json()
        if prompt_id not in data:
            return None

        task_data = data[prompt_id]
        outputs = task_data.get('outputs', {})

        video_file = None
        audio_file = None

        for node_id, node_output in outputs.items():
            if 'gifs' in node_output:
                for video in node_output['gifs']:
                    filename = video.get('filename', '')
                    if filename.endswith('.mp4') and not filename.endswith('-audio.mp4'):
                        return {
                            'filename': filename,
                            'subfolder': video.get('subfolder', ''),
                            'type': video.get('type', 'output'),
                            'node_id': node_id
                        }
                    elif filename.endswith('-audio.mp4'):
                        audio_file = filename

            if 'videos' in node_output:
                for video in node_output['videos']:
                    filename = video[0] if isinstance(video, list) else video
                    if not filename.endswith('-audio.mp4'):
                        return {
                            'filename': filename,
                            'subfolder': node_output.get('subfolder', ''),
                            'type': node_output.get('type', 'output'),
                            'node_id': node_id
                        }
                    elif not audio_file:
                        audio_file = filename

            if 'filename' in node_output:
                filename = node_output['filename']
                if not filename.endswith('-audio.mp4'):
                    return {
                        'filename': filename,
                        'subfolder': node_output.get('subfolder', ''),
                        'type': node_output.get('type', 'output'),
                        'node_id': node_id
                    }
                elif not audio_file:
                    audio_file = filename

        if audio_file:
            return {
                'audio_filename': audio_file,
                'derived_video': audio_file.replace('-audio.mp4', '.mp4')
            }

        return None
    except Exception as e:
        print(f">>> History查询失败: {e}")
        return None


def find_task_by_input_files(audio_filename: str, image_filename: str = None) -> Optional[str]:
    """从 ComfyUI queue 中查找匹配输入文件的 prompt_id"""
    try:
        resp = httpx.get(f"{COMFYUI_API}/queue", timeout=10, trust_env=False)
        data = resp.json()

        for queue_key in ('queue_running', 'queue_pending'):
            for item in data.get(queue_key, []):
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue

                prompt_id = item[1] if isinstance(item[1], str) and len(item[1]) > 20 else None
                if not prompt_id:
                    continue

                workflow = item[2] if isinstance(item[2], dict) else {}
                if not workflow:
                    continue

                for node in workflow.values():
                    if not isinstance(node, dict):
                        continue
                    inputs = node.get('inputs', {})
                    audio_val = inputs.get('audio', '')
                    image_val = inputs.get('image', '')
                    if audio_val and isinstance(audio_val, str) and audio_filename in audio_val:
                        print(f">>> 匹配到任务 [{queue_key}] audio={audio_filename}: prompt_id={prompt_id}")
                        return prompt_id
                    if image_val and isinstance(image_val, str) and image_filename in image_val:
                        print(f">>> 匹配到任务 [{queue_key}] image={image_filename}: prompt_id={prompt_id}")
                        return prompt_id

        return None
    except Exception as e:
        print(f">>> Queue查询失败: {e}")
        return None


def interrupt_task() -> bool:
    """发送中断指令到 ComfyUI"""
    try:
        resp = httpx.post(
            f"{COMFYUI_API}/interrupt",
            json={},
            timeout=10,
            trust_env=False
        )
        return resp.status_code == 200
    except Exception as e:
        print(f">>> 中断指令失败: {e}")
        return False


def extract_prompt_id_from_sse(sse_text: str) -> Optional[str]:
    """从 SSE 响应文本中提取 Prompt ID"""
    patterns = [
        r'Prompt ID[:\s]+([a-f0-9-]{20,})',
        r'prompt_id["\']?\s*[:=]\s*["\']?([a-f0-9-]{20,})',
        r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
    ]
    for pattern in patterns:
        match = re.search(pattern, sse_text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
