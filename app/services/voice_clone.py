#!/usr/bin/env python3
"""音色克隆服务 - 基于硅基流动IndexTTS-2"""

import base64
import asyncio
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from app.config import SILICONFLOW_API_KEY, SILICONFLOW_URL, VOICE_CLONE_URL

MAX_RETRIES = 5
RETRY_DELAY = 2.0

# 音色缓存
_voice_cache = {}

@dataclass
class VoiceCloneResult:
    voice_uri: str       # 克隆音色ID
    voice_name: str      # 音色名称

@dataclass
class SynthesisResult:
    audio_path: str      # 生成的音频文件路径
    duration: float      # 时长(秒)

def _get_audio_base64(audio_path: str) -> str:
    """获取音频的base64编码"""
    with open(audio_path, 'rb') as f:
        return base64.b64encode(f.read()).decode()

async def clone_voice(
    audio_path: str,
    voice_name: str = "my_voice",
    reference_text: str = "这是参考语音。"
) -> VoiceCloneResult:
    """克隆用户声音

    Args:
        audio_path: 参考音频文件路径 (10-20秒)
        voice_name: 音色名称标识
        reference_text: 参考文本

    Returns:
        VoiceCloneResult: 包含voice_uri
    """
    # 检查缓存
    if voice_name in _voice_cache:
        print(f">>> 使用缓存音色: {voice_name}")
        return _voice_cache[voice_name]

    # 读取音频并转为base64
    audio_data = _get_audio_base64(audio_path)
    audio_url = f"data:audio/mpeg;base64,{audio_data}"

    payload = {
        "model": "IndexTeam/IndexTTS-2",
        "custom_name": voice_name,
        "text": reference_text,
        "audio": audio_url
    }

    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }

    loop = asyncio.get_event_loop()

    async def _clone():
        return await loop.run_in_executor(
            None,
            lambda: requests.post(VOICE_CLONE_URL, headers=headers, json=payload, timeout=120)
        )

    response = await _clone()

    if response.status_code != 200:
        raise RuntimeError(f"音色克隆失败: {response.status_code} - {response.text}")

    result = response.json()
    voice_uri = result.get('uri')

    voice_result = VoiceCloneResult(voice_uri=voice_uri, voice_name=voice_name)
    _voice_cache[voice_name] = voice_result

    print(f">>> 音色克隆成功: {voice_uri}")
    return voice_result

async def synthesize(
    text: str,
    voice_uri: str,
    output_path: Optional[str] = None,
    speed: float = 1.0
) -> SynthesisResult:
    """使用指定音色合成语音

    Args:
        text: 要合成的文本
        voice_uri: 音色URI
        output_path: 输出文件路径
        speed: 语速 (0.5-2.0)

    Returns:
        SynthesisResult: 包含音频路径和时长
    """
    if output_path is None:
        output_path = str(Path(__file__).parent.parent.parent / "assets" / "audios" / "tts_output.mp3")

    # 确保目录存在
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "model": "IndexTeam/IndexTTS-2",
        "input": text,
        "voice": voice_uri,
        "response_format": "mp3",
        "speed": speed
    }

    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }

    loop = asyncio.get_event_loop()

    for attempt in range(MAX_RETRIES):
        try:
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(SILICONFLOW_URL, headers=headers, json=payload, timeout=120)
            )

            if response.status_code == 200:
                break
            if response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            raise RuntimeError(f"TTS合成失败: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            raise RuntimeError(f"网络错误: {e}")
    else:
        raise RuntimeError("TTS合成失败: 达到最大重试次数")

    # 保存音频
    with open(output_path, 'wb') as f:
        f.write(response.content)

    # 获取时长
    import subprocess
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip() or 0)

    print(f">>> TTS合成成功: {output_path} ({duration:.1f}s)")
    return SynthesisResult(audio_path=output_path, duration=duration)

async def clone_and_synthesize(
    reference_audio: str,
    text: str,
    voice_name: str = "my_voice"
) -> SynthesisResult:
    """一键：克隆音色并合成

    Args:
        reference_audio: 参考音频路径
        text: 要合成的文本
        voice_name: 音色名称

    Returns:
        SynthesisResult: 包含音频路径和时长
    """
    # 1. 克隆音色
    clone_result = await clone_voice(reference_audio, voice_name)

    # 2. 合成语音
    return await synthesize(text, clone_result.voice_uri)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python3 voice_clone.py <参考音频> <文本>")
        sys.exit(1)

    reference = sys.argv[1]
    text = sys.argv[2]

    # 测试
    print(f">>> 参考音频: {reference}")
    print(f">>> 文本: {text}")

    result = asyncio.run(clone_and_synthesize(reference, text))
    print(f"\n>>> 完成: {result.audio_path}")
    print(f">>> 时长: {result.duration:.1f}s")
