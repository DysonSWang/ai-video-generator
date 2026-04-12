#!/usr/bin/env python3
"""MuseTalk口型同步服务 - 通过Gradio API调用远程GPU服务器"""

import time
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from app.config import (
    MUSETALK_HOST, MUSETALK_PORT, MUSETALK_USER, MUSETALK_PASSWORD,
    MUSETALK_URL, OSS_ACCESS_KEY, OSS_SECRET_KEY, OSS_BUCKET, OSS_ENDPOINT
)

_no_proxy_session = requests.Session()
_no_proxy_session.trust_env = False

MAX_RETRIES = 3
RETRY_DELAY = 2.0

@dataclass
class MuseTalkResult:
    video_path: str   # 本地保存路径
    duration: float    # 视频时长(秒)

def upload_to_oss(local_path: str, oss_key: str) -> str:
    """上传文件到阿里云OSS"""
    import oss2
    auth = oss2.Auth(OSS_ACCESS_KEY, OSS_SECRET_KEY)
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)
    result = bucket.put_object_from_file(oss_key, local_path)
    if result.status != 200:
        raise RuntimeError(f"OSS上传失败: {result.status}")
    return f"https://{OSS_BUCKET}.{OSS_ENDPOINT}/{oss_key}"


def make_file_data(path: str) -> dict:
    """构建包含meta字段的FileData对象"""
    return {
        "path": path,
        "url": None,
        "size": None,
        "orig_name": None,
        "mime_type": None,
        "is_stream": False,
        "meta": {"_type": "gradio.FileData"}
    }


def make_video_data(path: str) -> dict:
    """构建VideoData对象"""
    return {
        "video": make_file_data(path),
        "subtitles": None
    }


async def musetalk_lip_sync(
    video_path: str,
    audio_path: str,
    output_path: Optional[str] = None,
    poll_interval: float = 10.0,
    max_wait: float = 600.0
) -> MuseTalkResult:
    """调用远程MuseTalk服务生成口型同步视频

    Args:
        video_path: 用户视频路径(不说话)
        audio_path: 配音音频路径
        output_path: 输出视频路径
        poll_interval: 轮询间隔(秒)
        max_wait: 最大等待时间(秒)

    Returns:
        MuseTalkResult: 包含本地视频路径和时长
    """
    import asyncio

    if output_path is None:
        output_path = str(Path(__file__).parent.parent.parent / "assets" / "outputs" / "musetalk_result.mp4")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print(f">>> 上传文件到MuseTalk服务器...")

    # 1. 上传视频
    with open(video_path, 'rb') as f:
        resp = _no_proxy_session.post(
            f"{MUSETALK_URL}/gradio_api/upload",
            files={"files": f},
            timeout=60
        )
    video_result = resp.json()
    video_server_path = video_result[0] if isinstance(video_result, list) else video_result.get('path', video_result)
    print(f">>> 视频上传完成: {video_server_path}")

    # 2. 上传音频
    with open(audio_path, 'rb') as f:
        resp = _no_proxy_session.post(
            f"{MUSETALK_URL}/gradio_api/upload",
            files={"files": f},
            timeout=60
        )
    audio_result = resp.json()
    audio_server_path = audio_result[0] if isinstance(audio_result, list) else audio_result.get('path', audio_result)
    print(f">>> 音频上传完成: {audio_server_path}")

    # 3. 调用inference
    print(f">>> 调用MuseTalk推理...")
    inference_data = {
        "data": [
            make_file_data(audio_server_path),   # audio_path (FileData)
            make_video_data(video_server_path),  # video_path (VideoData)
            0,                                   # bbox_shift
            10,                                  # extra_margin
            "jaw",                               # parsing_mode
            90,                                  # left_cheek_width
            90                                   # right_cheek_width
        ]
    }

    resp = _no_proxy_session.post(
        f"{MUSETALK_URL}/gradio_api/call/inference",
        json=inference_data,
        timeout=30
    )

    if resp.status_code != 200:
        raise RuntimeError(f"推理请求失败: {resp.status_code}")

    event_id = resp.json().get('event_id')
    if not event_id:
        raise RuntimeError(f"未获取到event_id: {resp.text}")

    print(f">>> 任务ID: {event_id}")

    # 4. 轮询等待结果
    start_time = time.time()
    result_url = None

    while time.time() - start_time < max_wait:
        await asyncio.sleep(poll_interval)

        try:
            resp = _no_proxy_session.get(
                f"{MUSETALK_URL}/gradio_api/call/inference/{event_id}",
                timeout=30
            )
            result = resp.json()
            status = result.get('status')

            if status == 'completed':
                # 获取输出文件路径
                if 'data' in result and len(result['data']) > 0:
                    output_data = result['data'][0]
                    if isinstance(output_data, dict):
                        result_url = output_data.get('video', {}).get('path')
                    else:
                        result_url = output_data
                print(f">>> 推理完成!")
                break
            elif status == 'error':
                error_msg = result.get('error', 'Unknown error')
                raise RuntimeError(f"推理出错: {error_msg}")

            elapsed = int(time.time() - start_time)
            print(f">>> 等待中... ({elapsed}s)")

        except Exception as e:
            print(f">>> 轮询错误: {e}")
            await asyncio.sleep(poll_interval)

    if not result_url:
        raise TimeoutError(f"等待推理完成超时: {max_wait}秒")

    # 5. 下载结果
    print(f">>> 下载结果...")
    # result_url 是服务器上的路径，需要通过 SFTP 下载
    # 但 Gradio 返回的是临时文件路径，需要先复制到可访问位置

    # 使用 paramiko 通过 SSH 下载
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        MUSETALK_HOST,
        port=MUSETALK_PORT,
        username=MUSETALK_USER,
        password=MUSETALK_PASSWORD,
        timeout=60
    )

    try:
        # 从 Gradio 临时路径复制到 results 目录
        # Gradio 的临时文件在 /tmp/gradio/ 下
        sftp = client.open_sftp()

        # 查找最新的输出视频
        stdin, stdout, stderr = client.exec_command(
            'ls -lt /root/MuseTalk/results/output/v15/*.mp4 2>/dev/null | head -1'
        )
        latest_file = stdout.read().decode().strip().split('\n')[0] if stdout.read().decode().strip() else ''
        if latest_file:
            parts = latest_file.split()
            if len(parts) >= 8:
                filename = parts[-1]
                remote_path = f"/root/MuseTalk/results/output/v15/{filename}"
                print(f">>> 找到输出文件: {remote_path}")
                sftp.get(remote_path, output_path)
                print(f">>> 下载完成: {output_path}")
        else:
            # 尝试直接下载 result_url（如果是完整路径）
            if result_url and result_url.startswith('/'):
                sftp.get(result_url, output_path)
            else:
                raise RuntimeError(f"无法找到输出文件")

        sftp.close()
    finally:
        client.close()

    # 6. 获取时长
    import subprocess
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip() or 0)

    print(f">>> MuseTalk完成: {output_path} ({duration:.1f}s)")
    return MuseTalkResult(video_path=output_path, duration=duration)


if __name__ == "__main__":
    import sys
    import asyncio

    if len(sys.argv) < 3:
        print("用法: python3 musetalk.py <视频> <音频>")
        sys.exit(1)

    video = sys.argv[1]
    audio = sys.argv[2]

    print(f">>> 视频: {video}")
    print(f">>> 音频: {audio}")

    result = asyncio.run(musetalk_lip_sync(video, audio))
    print(f"\n>>> 完成!")
    print(f">>> 视频: {result.video_path}")
    print(f">>> 时长: {result.duration}s")
