#!/usr/bin/env python3
"""字幕服务 - 生成SRT字幕并烧录到视频"""

import asyncio
import subprocess
import re
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from .speech_to_text import transcribe, TranscriptionSegment, segments_to_srt, _format_srt_time

@dataclass
class SubtitleStyle:
    font_size: int = 26               # 竖屏视频字幕不能太大
    font_color: str = "&HFFFFFF"      # 白色
    outline_color: str = "&H000000"   # 黑色描边
    outline_width: int = 2             # 描边
    bold: bool = True
    position: str = "bottom"           # bottom / top / center
    margin_v: int = 100               # 垂直边距

@dataclass
class SubtitleResult:
    srt_path: str       # 字幕文件路径
    video_path: str     # 烧录后的视频路径

async def generate_srt_async(
    audio_path: str,
    output_path: Optional[str] = None
) -> str:
    """从音频生成SRT字幕文件 (异步版本)

    Args:
        audio_path: 音频文件路径
        output_path: 输出SRT路径

    Returns:
        SRT文件路径
    """
    if output_path is None:
        output_path = str(Path(audio_path).with_suffix('.srt'))

    # 使用Whisper识别
    result = await transcribe(audio_path)

    # 转为SRT格式
    srt_content = segments_to_srt(result.segments)

    # 保存
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)

    print(f">>> 字幕生成: {output_path} ({len(result.segments)}段)")
    return output_path

def generate_srt(
    audio_path: str,
    output_path: Optional[str] = None
) -> str:
    """从音频生成SRT字幕文件 (同步版本，用于独立运行)"""
    if output_path is None:
        output_path = str(Path(audio_path).with_suffix('.srt'))

    # 使用Whisper识别
    result = asyncio.run(transcribe(audio_path))

    # 转为SRT格式
    srt_content = segments_to_srt(result.segments)

    # 保存
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)

    print(f">>> 字幕生成: {output_path} ({len(result.segments)}段)")
    return output_path

def burn_subtitle(
    video_path: str,
    subtitle_path: str,
    output_path: Optional[str] = None,
    style: Optional[SubtitleStyle] = None
) -> str:
    """将字幕烧录到视频

    Args:
        video_path: 源视频路径
        subtitle_path: SRT字幕文件路径
        output_path: 输出视频路径
        style: 字幕样式

    Returns:
        烧录后的视频路径
    """
    if output_path is None:
        output_path = str(Path(video_path).with_suffix('_subtitled.mp4'))

    if style is None:
        style = SubtitleStyle()

    # 构建force_style参数
    force_style = (
        f"FontSize={style.font_size},"
        f"PrimaryColour=&H{style.font_color[2:]},"
        f"OutlineColour=&H{style.outline_color[2:]},"
        f"Outline={style.outline_width},"
        f"Bold={1 if style.bold else 0},"
        f"MarginV={style.margin_v},"
        f"MarginL=80,MarginR=80"  # 增大左右边距，防止字幕被裁切
    )

    # 位置调整
    if style.position == "bottom":
        force_style += ",Alignment=Bottom"
    elif style.position == "top":
        force_style += ",Alignment=Top"
    elif style.position == "center":
        force_style += ",Alignment=Center"

    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f'subtitles={subtitle_path}:force_style=\'{force_style}\'',
        '-c:a', 'copy',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # 尝试简单方式
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f'subtitles={subtitle_path}',
            '-c:a', 'copy',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"字幕烧录失败: {result.stderr}")

    print(f">>> 字幕烧录完成: {output_path}")
    return output_path


def generate_srt_from_rewritten(
    rewritten_text: str,
    original_segments: list,
    output_path: Optional[str] = None,
    audio_duration: Optional[float] = None
) -> str:
    """用改写文案生成SRT字幕（按句子数量均分音频时长）

    原理：改写句子数量和原始识别段落数量不一致，
    不再1:1映射，改为：按改写句子数均分总时长，独立生成时间戳。

    Args:
        rewritten_text: 改写后的完整文案
        original_segments: 原始视频的 Whisper 转录段落（含时间戳，用于取总时长）
        output_path: SRT 文件输出路径
        audio_duration: 音频总时长（秒），如果为None则用 original_segments 末尾段的 end

    Returns:
        SRT文件路径
    """
    import re

    # 按句子拆分改写文案
    # 先按换行拆分，再按句末标点合并
    paragraphs = rewritten_text.split('\n')
    sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 按句末标点拆分
        parts = re.split(r'([。！？])', para)
        for i in range(0, len(parts) - 1, 2):
            s = parts[i].strip()
            p = parts[i + 1] if i + 1 < len(parts) else ''
            if s:
                sentences.append(s + p)
        # 如果是奇数个parts，最后一个没有对应标点
        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1].strip())

    # 清理空句
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return ""

    # 计算总时长
    if audio_duration is not None:
        total_duration = audio_duration
    elif original_segments:
        total_duration = original_segments[-1].end if original_segments else 0.0
    else:
        total_duration = 0.0

    # 按句子数量均分时长
    srt_lines = []
    num_sentences = len(sentences)
    for i, text in enumerate(sentences):
        start_sec = (i / num_sentences) * total_duration
        end_sec = ((i + 1) / num_sentences) * total_duration

        # 如果句子太长（> 15秒），在中间加断点
        if end_sec - start_sec > 15 and i < num_sentences - 1:
            mid_sec = (start_sec + end_sec) / 2
            # 前半句
            srt_lines.append(f"{i * 2 + 1}")
            srt_lines.append(f"{_format_srt_time(start_sec)} --> {_format_srt_time(mid_sec)}")
            srt_lines.append(text[:len(text)//2] + "…" if len(text) > 20 else text)
            srt_lines.append("")
            # 后半句
            srt_lines.append(f"{i * 2 + 2}")
            srt_lines.append(f"{_format_srt_time(mid_sec)} --> {_format_srt_time(end_sec)}")
            srt_lines.append(text[len(text)//2:] if len(text) > 20 else "")
            srt_lines.append("")
        else:
            srt_lines.append(f"{i + 1}")
            srt_lines.append(f"{_format_srt_time(start_sec)} --> {_format_srt_time(end_sec)}")
            srt_lines.append(text)
            srt_lines.append("")

    content = '\n'.join(srt_lines)
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f">>> SRT字幕生成（改写文案）: {output_path} ({num_sentences} 句)")

    return content


async def generate_and_burn(
    video_path: str,
    audio_path: str,
    output_path: Optional[str] = None,
    style: Optional[SubtitleStyle] = None
) -> SubtitleResult:
    """一键生成并烧录字幕

    Args:
        video_path: 视频路径
        audio_path: 音频路径（用于识别）
        output_path: 输出视频路径
        style: 字幕样式

    Returns:
        SubtitleResult
    """
    loop = asyncio.get_event_loop()

    # 1. 生成SRT (异步版本，避免嵌套事件循环)
    srt_path = await generate_srt_async(audio_path, None)

    # 2. 烧录
    final_path = await loop.run_in_executor(
        None, burn_subtitle, video_path, srt_path, output_path, style
    )

    return SubtitleResult(srt_path=srt_path, video_path=final_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python3 subtitle.py <视频> <音频>")
        sys.exit(1)

    video = sys.argv[1]
    audio = sys.argv[2]

    result = asyncio.run(generate_and_burn(video, audio))
    print(f"\n>>> 完成!")
    print(f">>> 字幕: {result.srt_path}")
    print(f">>> 视频: {result.video_path}")
