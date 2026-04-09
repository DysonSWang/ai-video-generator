#!/usr/bin/env python3
"""语音转文字服务 - 基于Whisper"""

import asyncio
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import whisper
import numpy as np

# 模型缓存
_model = None

@dataclass
class TranscriptionSegment:
    start: float  # 秒
    end: float    # 秒
    text: str

@dataclass
class TranscriptionResult:
    text: str           # 完整文本
    segments: List[TranscriptionSegment]  # 分段
    language: str       # 语言

def get_model(model_name: str = "base"):
    """获取Whisper模型（单例）"""
    global _model
    if _model is None:
        print(f">>> 加载Whisper {model_name} 模型...")
        _model = whisper.load_model(model_name)
        print(">>> 模型加载完成")
    return _model

def extract_audio(video_path: str, output_path: Optional[str] = None) -> str:
    """从视频提取音频"""
    if output_path is None:
        output_path = str(Path(video_path).with_suffix('.wav'))

    # 先检查是否有音轨
    check_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'json', video_path]
    result = subprocess.run(check_cmd, capture_output=True, text=True)
    if 'audio' not in result.stdout.lower():
        raise ValueError(f"视频不包含音轨: {Path(video_path).name}")

    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le',
        '-ar', '16000', '-ac', '1',
        output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path

async def transcribe(
    video_path: str,
    model_name: str = "base",
    language: str = "zh"
) -> TranscriptionResult:
    """将视频/音频转为文字

    Args:
        video_path: 视频或音频文件路径
        model_name: Whisper模型 (tiny/base/small/medium/large)
        language: 语言代码 (zh/en)

    Returns:
        TranscriptionResult: 包含完整文本和分段
    """
    loop = asyncio.get_event_loop()

    # 如果是视频，先提取音频
    audio_path = video_path
    if Path(video_path).suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']:
        audio_path = await loop.run_in_executor(
            None, extract_audio, video_path, None
        )

    # 在线程池中执行Whisper推理
    def _transcribe_sync():
        model = get_model(model_name)
        result = model.transcribe(
            audio_path,
            language=language,
            task="transcribe"
        )
        return result

    result = await loop.run_in_executor(None, _transcribe_sync)

    # 转换为 TranscriptionResult
    segments = [
        TranscriptionSegment(
            start=seg['start'],
            end=seg['end'],
            text=seg['text'].strip()
        )
        for seg in result['segments']
    ]

    return TranscriptionResult(
        text=result['text'].strip(),
        segments=segments,
        language=result.get('language', language)
    )

def segments_to_srt(segments: List[TranscriptionSegment]) -> str:
    """将分段转为SRT格式"""
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        start_time = _format_srt_time(seg.start)
        end_time = _format_srt_time(seg.end)
        srt_lines.append(f"{i}")
        srt_lines.append(f"{start_time} --> {end_time}")
        srt_lines.append(seg.text)
        srt_lines.append("")
    return "\n".join(srt_lines)

def _format_srt_time(seconds: float) -> str:
    """秒数转为 SRT 时间格式 (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 speech_to_text.py <视频文件>")
        sys.exit(1)

    result = asyncio.run(transcribe(sys.argv[1]))

    print(f"\n识别结果 (语言: {result.language}):")
    print("=" * 50)
    print(result.text)
    print("=" * 50)
    print(f"\n分段 ({len(result.segments)} 段):")
    for seg in result.segments:
        print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")
