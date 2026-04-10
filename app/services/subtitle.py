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
    style: Optional[SubtitleStyle] = None,
    audio_path: Optional[str] = None
) -> str:
    """将字幕烧录到视频

    Args:
        video_path: 源视频路径
        subtitle_path: SRT/ASS字幕文件路径
        output_path: 输出视频路径
        style: 字幕样式
        audio_path: 可选音频路径（当视频无音轨时使用，如TTS音频）

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

    # 检查视频是否有音轨
    has_audio = False
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True
        )
        has_audio = 'audio' in probe.stdout
    except Exception:
        pass

    if has_audio:
        # 视频有音轨：重新编码视频（字幕滤镜需要），保留音频
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f'subtitles={subtitle_path}:force_style=\'{force_style}\'',
            '-c:v', 'libx264', '-preset', 'fast',
            '-c:a', 'aac',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            cmd = [
                'ffmpeg', '-y', '-i', video_path,
                '-vf', f'subtitles={subtitle_path}',
                '-c:v', 'libx264', '-preset', 'fast',
                '-c:a', 'aac',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
    elif audio_path and Path(audio_path).exists():
        # 视频无音轨但提供了音频：合并音频 + 烧录字幕
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-vf', f'subtitles={subtitle_path}:force_style=\'{force_style}\'',
            '-map', '0:v',
            '-map', '1:a',
            '-c:v', 'libx264', '-preset', 'fast',
            '-shortest',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # 尝试不用force_style
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-i', audio_path,
                '-vf', f'subtitles={subtitle_path}',
                '-map', '0:v',
                '-map', '1:a',
                '-c:v', 'libx264', '-preset', 'fast',
                '-shortest',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        # 无音轨且无音频：直接烧录（无音频）
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f'subtitles={subtitle_path}:force_style=\'{force_style}\'',
            '-c:v', 'libx264', '-preset', 'fast',
            '-shortest',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            cmd = [
                'ffmpeg', '-y', '-i', video_path,
                '-vf', f'subtitles={subtitle_path}',
                '-c:v', 'libx264', '-preset', 'fast',
                '-shortest',
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


def _format_ass_time(seconds: float) -> str:
    """ASS时间格式: H:MM:SS.cc (厘秒)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def generate_ass_from_rewritten(
    rewritten_text: str,
    original_segments: list,
    output_path: str,
    audio_duration: Optional[float] = None,
    style: Optional[SubtitleStyle] = None,
) -> str:
    """用改写文案生成ASS字幕（支持自动换行和边界控制）

    Args:
        rewritten_text: 改写后的完整文案
        original_segments: 原始视频的 Whisper 转录段落（含时间戳，用于取总时长）
        output_path: ASS 文件输出路径
        audio_duration: 音频总时长（秒）
        style: 字幕样式

    Returns:
        ASS文件路径
    """
    import re

    if style is None:
        style = SubtitleStyle()

    # 按句子拆分（和SRT版本一样）
    paragraphs = rewritten_text.split('\n')
    sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        parts = re.split(r'([。！？])', para)
        for i in range(0, len(parts) - 1, 2):
            s = parts[i].strip()
            p = parts[i + 1] if i + 1 < len(parts) else ''
            if s:
                sentences.append(s + p)
        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1].strip())

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

    # ASS头和样式
    # WrapStyle=0: 智能换行（按空格处换行，中文按句末标点）
    ass_header = f"""[Script Info]
Title=AI Video Subtitles
ScriptType=v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,SimHei,{style.font_size},&H00{style.font_color[2:]},&H000000FF,&H00{style.outline_color[2:]},&H00000000,{1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline_width},{style.outline_width},2,{style.margin_v},{style.margin_v},{style.margin_v},134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Alignment=2 means bottom-center in ASS
    # MarginL/MarginR 水平边距，MarginV 垂直边距
    dialogue_lines = []
    num_sentences = len(sentences)

    for i, text in enumerate(sentences):
        start_sec = (i / num_sentences) * total_duration
        end_sec = ((i + 1) / num_sentences) * total_duration

        # 如果句子太长（> 15秒），拆分
        if end_sec - start_sec > 15 and i < num_sentences - 1:
            mid_sec = (start_sec + end_sec) / 2
            text1 = text[:len(text)//2]
            text2 = text[len(text)//2:]
            dialogue_lines.append(
                f"Dialogue: 0,{_format_ass_time(start_sec)},{_format_ass_time(mid_sec)},Default,,0,0,0,,{text1}"
            )
            dialogue_lines.append(
                f"Dialogue: 0,{_format_ass_time(mid_sec)},{_format_ass_time(end_sec)},Default,,0,0,0,,{text2}"
            )
        else:
            dialogue_lines.append(
                f"Dialogue: 0,{_format_ass_time(start_sec)},{_format_ass_time(end_sec)},Default,,0,0,0,,{text}"
            )

    content = ass_header + '\n'.join(dialogue_lines) + '\n'

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f">>> ASS字幕生成（改写文案）: {output_path} ({num_sentences} 句)")

    return content
