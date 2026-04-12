#!/usr/bin/env python3
"""OmniVoice 音色克隆合成服务 - 基于自托管GPU服务器"""

import asyncio
import time
import httpx
import paramiko
import uuid
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from app.config import (
    OMNIVOICE_HOST, OMNIVOICE_PORT, OMNIVOICE_USER, OMNIVOICE_PASSWORD,
    OMNIVOICE_GRADIO_URL, OMNIVOICE_OUTPUT_DIR, OMNIVOICE_SAVED_VOICES
)
from .omni_voice_manager import record_submission, mark_completed, mark_failed

_no_proxy_session = httpx.Client(timeout=30.0, trust_env=False)

SSH_TIMEOUT = 30
POLL_INTERVAL = 3  # 秒
POLL_MAX_WAIT = 300  # 最多等待5分钟

@dataclass
class OmniVoiceResult:
    audio_path: str      # 生成的音频文件路径（本地）
    duration: float      # 时长(秒)
    task_id: str        # 任务ID


async def _transcribe_reference_audio(audio_path: str) -> str:
    """转录参考音频内容，用于填充 ref_text 字段

    OmniVoice 的"上传参考音频"模式要求 ref_text 准确描述参考音频说了什么，
    否则模型无法正确处理，导致输出异常（过长/杂音等）。
    """
    try:
        from app.services.speech_to_text import transcribe
        result = await transcribe(audio_path)
        text = result.text.strip() if hasattr(result, 'text') else str(result).strip()
        if text:
            print(f">>> OmniVoice 参考音频转录: {text[:50]}...")
            return text
    except Exception as e:
        print(f">>> OmniVoice 参考音频转录失败: {e}")
    return "语音参考"


def make_file_data(path: str, orig_name: str = None, mime_type: str = None) -> dict:
    """构建 Gradio FileData 对象"""
    return {
        "path": path,
        "url": None,
        "size": None,
        "orig_name": orig_name,
        "mime_type": mime_type,
        "is_stream": False,
        "meta": {"_type": "gradio.FileData"}
    }


def _upload_to_gradio(local_path: str) -> str:
    """上传本地文件到 OmniVoice Gradio 服务器，返回服务器路径"""
    with open(local_path, 'rb') as f:
        resp = _no_proxy_session.post(
            f"{OMNIVOICE_GRADIO_URL}/gradio_api/upload",
            files={"files": f},
            timeout=60.0
        )
    result = resp.json()
    server_path = result[0] if isinstance(result, list) else result.get('path', result)
    print(f">>> OmniVoice 文件上传完成: {server_path}")
    return server_path


async def _submit_task(voice_name: str, text: str, ref_audio_path: Optional[str] = None) -> str:
    """提交合成任务，返回 event_id"""
    if ref_audio_path:
        # 上传参考音频
        remote_ref = _upload_to_gradio(ref_audio_path)

        # 获取参考音频的实际文本内容（通过Whisper转录）
        # ref_text 必须准确描述参考音频说了什么，否则模型无法正确处理
        ref_text = await _transcribe_reference_audio(ref_audio_path)

        # 构造 Gradio FileData 格式
        file_data = make_file_data(
            path=remote_ref,
            orig_name=Path(ref_audio_path).name,
            mime_type="audio/wav"
        )
        source_mode = "上传参考音频"
        saved_name = ""
    else:
        file_data = None
        source_mode = "使用已存音色"
        saved_name = voice_name
        ref_text = ""

    payload = {
        "data": [
            source_mode,     # 音色来源
            file_data,       # 参考音频
            ref_text,        # 参考文本
            saved_name,      # 选择已保存的音色
            text,            # 待合成文本
            "Auto",          # 语种
            "",              # 指令
            32,              # 推理步数
            1.0,             # CFG
            True,            # 降噪
            1.0,             # 语速
            None,            # 时长
            False,           # 预处理
            False            # 后处理
        ]
    }

    response = _no_proxy_session.post(
        f"{OMNIVOICE_GRADIO_URL}/gradio_api/call/add_clone_task",
        json=payload,
        timeout=30
    )
    result = response.json()
    return result.get('event_id')


def _sftp_connect():
    """建立 SFTP 连接"""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=OMNIVOICE_HOST,
        port=OMNIVOICE_PORT,
        username=OMNIVOICE_USER,
        password=OMNIVOICE_PASSWORD,
        timeout=SSH_TIMEOUT,
        banner_timeout=SSH_TIMEOUT
    )
    return ssh


def _get_output_files(sftp) -> dict:
    """获取输出目录中所有文件的 mtime"""
    files = {}
    try:
        for f in sftp.listdir(OMNIVOICE_OUTPUT_DIR):
            if f.startswith('.'):
                continue
            try:
                stat = sftp.stat(f'{OMNIVOICE_OUTPUT_DIR}/{f}')
                files[f] = stat.st_mtime
            except Exception:
                pass
    except Exception:
        pass
    return files


def _wait_for_output(ssh, sftp, baseline_files: dict, text: str) -> Optional[str]:
    """通过 SFTP mtime 轮询等待新输出文件出现

    注意：OmniVoice 队列非 FIFO，可能不按提交顺序完成。
    因此检测任意新文件（mtime > baseline max）即返回。

    Returns:
        输出文件名，或 None（超时）
    """
    start = time.time()
    baseline_max = max(baseline_files.values()) if baseline_files else 0

    for i in range(POLL_MAX_WAIT // POLL_INTERVAL):
        time.sleep(POLL_INTERVAL)

        files = _get_output_files(sftp)

        # 找任意新文件（mtime 比 baseline 更大的）
        for fname, mtime in files.items():
            is_newer = mtime > baseline_max

            if is_newer:
                # 等待文件稳定（连续两次检查大小不变）
                for _ in range(5):
                    time.sleep(2)
                    try:
                        new_size = sftp.stat(f'{OMNIVOICE_OUTPUT_DIR}/{fname}').st_size
                        time.sleep(1)
                        next_size = sftp.stat(f'{OMNIVOICE_OUTPUT_DIR}/{fname}').st_size
                        if new_size == next_size and new_size > 1024:
                            elapsed = int(time.time() - start)
                            print(f">>> OmniVoice 检测到输出文件: {fname} ({new_size/1024:.1f}KB, {elapsed}s)")
                            return fname
                    except Exception:
                        pass

        elapsed = int(time.time() - start)
        if i % 10 == 0:
            print(f">>> OmniVoice 等待中... ({elapsed}s)")

    return None


def _download_result(output_filename: str, local_output_dir: str) -> str:
    """从 GPU 服务器下载结果文件到本地"""
    local_output_dir = Path(local_output_dir)
    local_output_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_output_dir / output_filename

    ssh = _sftp_connect()
    sftp = ssh.open_sftp()

    remote_path = f"{OMNIVOICE_OUTPUT_DIR}/{output_filename}"
    try:
        sftp.get(remote_path, str(local_path))
    except FileNotFoundError:
        # 尝试从 /tmp/gradio 目录查找
        cmd = f'find /tmp/gradio -name "{output_filename}" 2>/dev/null | head -1'
        stdin, stdout, stderr = ssh.exec_command(cmd)
        remote_from_tmp = stdout.read().decode().strip()
        if remote_from_tmp:
            sftp.get(remote_from_tmp, str(local_path))
        else:
            raise FileNotFoundError(f"找不到文件: {output_filename}")
    finally:
        sftp.close()
        ssh.close()

    return str(local_path)


def _get_duration(audio_path: str) -> float:
    """获取音频时长"""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip() or 0)
    except Exception:
        return 0


async def synthesize(
    text: str,
    voice_name: str = "liangzi",
    ref_audio_path: Optional[str] = None,
    output_path: Optional[str] = None,
    speed: float = 1.0
) -> OmniVoiceResult:
    """使用 OmniVoice 合成语音

    Args:
        text: 要合成的文本
        voice_name: 预置音色名称 (liangzi 或 sichuanfenda)
        ref_audio_path: 参考音频路径（可选，使用上传参考音频模式）
        output_path: 输出文件路径
        speed: 语速 (0.5-2.0)

    Returns:
        OmniVoiceResult: 包含本地音频路径和时长
    """
    if output_path is None:
        output_dir = Path(__file__).parent.parent.parent / "assets" / "audios"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"omnivoice_{uuid.uuid4().hex[:8]}.wav")

    # 1. 连接 SFTP 获取基准文件列表
    ssh = _sftp_connect()
    sftp = ssh.open_sftp()
    baseline_files = _get_output_files(sftp)
    sftp.close()
    ssh.close()
    print(f">>> OmniVoice 基准文件数: {len(baseline_files)}")

    # 2. 提交任务
    print(f">>> OmniVoice 提交任务: text='{text[:30]}...' voice={voice_name}")
    event_id = await _submit_task(voice_name, text, ref_audio_path)
    print(f">>> OmniVoice event_id: {event_id}")

    # 3. 记录到本地 DB
    record_submission(event_id, event_id, voice_name, text)

    # 4. 通过 SFTP mtime 轮询等待输出文件
    ssh = _sftp_connect()
    sftp = ssh.open_sftp()
    output_filename = _wait_for_output(ssh, sftp, baseline_files, text)
    sftp.close()
    ssh.close()

    if not output_filename:
        mark_failed(event_id, "等待输出文件超时")
        raise RuntimeError("OmniVoice 等待输出文件超时")

    # 5. 下载结果文件
    local_path = _download_result(output_filename, str(Path(output_path).parent))

    # 6. 移动到指定路径
    final_path = Path(output_path)
    if Path(local_path) != final_path:
        import shutil
        shutil.move(local_path, str(final_path))
        local_path = str(final_path)

    # 7. 验证时长
    duration = _get_duration(local_path)
    mark_completed(event_id, local_path, duration)

    print(f">>> OmniVoice 合成成功: {local_path} ({duration:.1f}s)")
    return OmniVoiceResult(audio_path=local_path, duration=duration, task_id=event_id)


async def clone_and_synthesize(
    reference_audio: str,
    text: str,
    voice_name: str = "my_voice",
    output_path: Optional[str] = None,
    speed: float = 1.0
) -> OmniVoiceResult:
    """一键：克隆音色并合成（使用上传参考音频模式）

    Args:
        reference_audio: 参考音频路径
        text: 要合成的文本
        voice_name: 音色名称（用于标识）
        output_path: 输出音频路径
        speed: 语速

    Returns:
        OmniVoiceResult: 包含音频路径和时长
    """
    return await synthesize(
        text=text,
        voice_name=voice_name,
        ref_audio_path=reference_audio,
        output_path=output_path,
        speed=speed
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 omni_voice.py <文本> [音色名]")
        print("示例: python3 omni_voice.py '今天天气真好' liangzi")
        sys.exit(1)

    text = sys.argv[1]
    voice = sys.argv[2] if len(sys.argv) > 2 else "liangzi"

    print(f">>> 文本: {text}")
    print(f">>> 音色: {voice}")

    result = asyncio.run(synthesize(text, voice))
    print(f"\n>>> 完成: {result.audio_path}")
    print(f">>> 时长: {result.duration:.1f}s")
