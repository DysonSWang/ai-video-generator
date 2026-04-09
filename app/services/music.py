#!/usr/bin/env python3
"""配乐服务 - 背景音乐混合"""

import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

@dataclass
class MusicOptions:
    volume: float = 0.3        # 音乐音量 (0.0-1.0)
    fade_in: float = 0        # 淡入时长(秒)
    fade_out: float = 0       # 淡出时长(秒)
    start_time: float = 0     # 音乐开始时间(秒)

def add_music(
    video_path: str,
    music_path: str,
    output_path: Optional[str] = None,
    options: Optional[MusicOptions] = None
) -> str:
    """添加背景音乐

    Args:
        video_path: 视频路径
        music_path: 音乐文件路径
        output_path: 输出路径
        options: 音乐配置

    Returns:
        输出视频路径
    """
    if output_path is None:
        output_path = str(Path(video_path).with_suffix('_music.mp4'))

    if options is None:
        options = MusicOptions()

    # 获取视频时长
    duration = get_duration(video_path)

    # 构建 filter
    filters = []

    # 音乐处理：音量、淡入淡出
    music_filters = f"volume={options.volume}"

    if options.fade_in > 0:
        music_filters += f",afade=t=in:st=0:d={options.fade_in}"

    if options.fade_out > 0:
        fade_start = max(0, duration - options.fade_out)
        music_filters += f",afade=t=out:st={fade_start}:d={options.fade_out}"

    if options.start_time > 0:
        music_filters += f",adelay={int(options.start_time*1000)}"

    # 混合音频
    filters.append(f"[1:a]{music_filters}[music]")
    filters.append(f"[0:a][music]amix=inputs=2:duration=longest[aout]")

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', music_path,
        '-filter_complex', ';'.join(filters),
        '-map', '0:v',
        '-map', '[aout]',
        '-c:v', 'copy',
        '-shortest',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"配乐失败: {result.stderr}")

    print(f">>> 配乐完成: {output_path}")
    return output_path

def get_duration(file_path: str) -> float:
    """获取媒体文件时长"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip() or 0)

def extract_audio(video_path: str, output_path: Optional[str] = None) -> str:
    """提取视频音频"""
    if output_path is None:
        output_path = str(Path(video_path).with_suffix('.wav'))

    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le',
        '-ar', '44100', '-ac', '2',
        output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python3 music.py <视频> <音乐>")
        sys.exit(1)

    video = sys.argv[1]
    music = sys.argv[2]

    options = MusicOptions(volume=0.3, fade_in=1, fade_out=1)
    result = add_music(video, music, options=options)
    print(f"\n>>> 完成: {result}")
