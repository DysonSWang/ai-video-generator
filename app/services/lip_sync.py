#!/usr/bin/env python3
"""口型同步服务 - 基于可灵Kling AI Lip Sync API"""

import asyncio
import time
import jwt
import requests
import oss2
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from app.config import KLING_ACCESS_KEY, KLING_SECRET_KEY, KLING_API_BASE
from app.config import OSS_ACCESS_KEY, OSS_SECRET_KEY, OSS_BUCKET, OSS_ENDPOINT

MAX_RETRIES = 3
RETRY_DELAY = 1.0

@dataclass
class LipSyncResult:
    video_url: str       # 生成视频的URL
    duration: float      # 视频时长(秒)
    task_id: str         # 任务ID

def encode_jwt_token(ak: str, sk: str) -> str:
    """生成JWT Token"""
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5
    }
    return jwt.encode(payload, sk, headers=headers)

def upload_to_oss(local_path: str, oss_key: str) -> str:
    """上传文件到阿里云OSS，返回公开URL"""
    auth = oss2.Auth(OSS_ACCESS_KEY, OSS_SECRET_KEY)
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)

    result = bucket.put_object_from_file(oss_key, local_path)
    if result.status != 200:
        raise RuntimeError(f"OSS上传失败: {result.status}")

    return f"https://{OSS_BUCKET}.{OSS_ENDPOINT}/{oss_key}"

async def generate_lip_sync(
    video_path: str,
    audio_path: str,
    poll_interval: float = 5.0,
    max_wait: float = 300.0
) -> LipSyncResult:
    """生成口型同步视频

    Args:
        video_path: 用户视频路径 (不说话的视频)
        audio_path: 配音音频路径
        poll_interval: 轮询间隔(秒)
        max_wait: 最大等待时间(秒)

    Returns:
        LipSyncResult: 包含视频URL和任务ID
    """
    loop = asyncio.get_event_loop()

    # 生成JWT Token
    token = encode_jwt_token(KLING_ACCESS_KEY, KLING_SECRET_KEY)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # 获取视频时长(毫秒)
    print(">>> 获取视频时长...")
    import subprocess
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True
    )
    video_duration = float(result.stdout.strip() or 0)
    video_duration_ms = int(video_duration * 1000)
    print(f">>> 视频时长: {video_duration}s ({video_duration_ms}ms)")

    # 获取音频时长(毫秒)
    print(">>> 获取音频时长...")
    audio_result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
        capture_output=True, text=True
    )
    audio_duration = float(audio_result.stdout.strip() or 0)
    audio_duration_ms = int(audio_duration * 1000)
    print(f">>> 音频时长: {audio_duration}s ({audio_duration_ms}ms)")

    # sound_insert_time: 音频从视频0ms开始插入
    # sound_end_time: 音频结束时间点（视频时间轴），不能超过视频时长
    sound_insert_time = 0
    sound_end_time = min(audio_duration_ms, video_duration_ms)
    print(f">>> sound_end_time: {sound_end_time}ms (取音频和视频的较小值)")

    # 1. 上传视频到OSS
    print(">>> 上传视频到OSS...")
    video_key = f"lipsync/{int(time.time())}_video.mp4"
    video_url = await loop.run_in_executor(
        None, upload_to_oss, video_path, video_key
    )
    print(f">>> 视频URL: {video_url}")

    # 2. 上传音频到OSS
    print(">>> 上传音频到OSS...")
    audio_key = f"lipsync/{int(time.time())}_audio.mp3"
    audio_url = await loop.run_in_executor(
        None, upload_to_oss, audio_path, audio_key
    )
    print(f">>> 音频URL: {audio_url}")

    # 3. 人脸识别
    print(">>> 人脸识别...")
    identify_data = {
        "video_url": video_url
    }

    async def _identify():
        return await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{KLING_API_BASE}/v1/videos/identify-face",
                headers=headers, json=identify_data, timeout=60
            )
        )

    identify_resp = await _identify()
    identify_result = identify_resp.json()

    if identify_result.get('code') != 0:
        raise RuntimeError(f"人脸识别失败: {identify_result}")

    session_id = identify_result['data']['session_id']
    face_data = identify_result['data']['face_data'][0]
    face_id = face_data['face_id']
    print(f">>> 人脸识别成功: face_id={face_id}, session_id={session_id}")

    # 4. 创建口型同步任务
    print(">>> 创建口型同步任务...")
    lip_sync_data = {
        "session_id": session_id,
        "face_choose": [
            {
                "face_id": face_id,
                "sound_file": audio_url,
                "sound_insert_time": 0,
                "sound_start_time": 0,
                "sound_end_time": sound_end_time,
                "sound_volume": 1.0,
                "original_audio_volume": 1.0
            }
        ]
    }

    async def _create_task():
        return await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{KLING_API_BASE}/v1/videos/advanced-lip-sync",
                headers=headers, json=lip_sync_data, timeout=60
            )
        )

    create_resp = await _create_task()
    create_result = create_resp.json()

    if create_result.get('code') != 0:
        raise RuntimeError(f"创建任务失败: {create_result}")

    task_id = create_result['data']['task_id']
    print(f">>> 任务创建成功: task_id={task_id}")

    # 5. 轮询等待完成
    print(">>> 等待处理完成...")
    start_time = time.time()

    async def _poll():
        return await loop.run_in_executor(
            None,
            lambda: requests.get(
                f"{KLING_API_BASE}/v1/videos/advanced-lip-sync/{task_id}",
                headers=headers, timeout=60
            )
        )

    while True:
        if time.time() - start_time > max_wait:
            raise TimeoutError(f"等待超时: {max_wait}秒")

        poll_resp = await _poll()
        poll_result = poll_resp.json()

        status = poll_result['data']['task_status']
        print(f">>> 状态: {status} ({time.time() - start_time:.0f}s)")

        if status == 'succeed':
            video_info = poll_result['data']['task_result']['videos'][0]
            return LipSyncResult(
                video_url=video_info['url'],
                duration=float(video_info['duration']),
                task_id=task_id
            )
        elif status == 'failed':
            raise RuntimeError(f"任务失败: {poll_result['data'].get('task_status_msg')}")

        await asyncio.sleep(poll_interval)


def _download_file_sync(url: str, output_path: str):
    """同步下载文件"""
    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

async def download_result(result: LipSyncResult, output_path: Optional[str] = None) -> str:
    """下载生成结果到本地"""
    if output_path is None:
        output_path = str(Path(__file__).parent.parent.parent / "assets" / "outputs" / "lipsync_result.mp4")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _download_file_sync, result.video_url, output_path
    )

    print(f">>> 下载完成: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python3 lip_sync.py <视频> <音频>")
        sys.exit(1)

    video = sys.argv[1]
    audio = sys.argv[2]

    print(f">>> 视频: {video}")
    print(f">>> 音频: {audio}")

    result = asyncio.run(generate_lip_sync(video, audio))
    print(f"\n>>> 完成!")
    print(f">>> 视频URL: {result.video_url}")
    print(f">>> 时长: {result.duration}s")
    print(f">>> 任务ID: {result.task_id}")


# ============== 口型同步服务选择器 ==============

async def generate_lip_sync_by_provider(
    video_path: str,
    audio_path: str,
    provider: str = "infinite_talk",
    **kwargs
) -> dict:
    """生成口型同步视频（根据provider选择服务）

    Args:
        video_path: 用户视频/照片路径
        audio_path: 配音音频路径
        provider: "infinite_talk" (默认) 或 "kling"
        **kwargs: 传递给具体服务的额外参数

    Returns:
        dict: 包含 video_path, duration, provider
    """
    if provider == "infinite_talk":
        from app.services.infinite_talk import generate_infinite_talk
        result = await generate_infinite_talk(
            person_image=video_path,
            audio_path=audio_path,
            **kwargs
        )
        return {
            "video_path": result.video_path,
            "duration": result.duration,
            "provider": "infinite_talk"
        }
    elif provider == "kling":
        result = await generate_lip_sync(video_path, audio_path, **kwargs)
        # Kling返回的是URL，需要下载
        local_path = await download_result(result)
        return {
            "video_path": local_path,
            "duration": result.duration,
            "provider": "kling"
        }
    else:
        raise ValueError(f"不支持的provider: {provider}，可选: infinite_talk, kling")
