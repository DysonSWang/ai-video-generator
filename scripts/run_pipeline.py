#!/usr/bin/env python3
"""完整Pipeline测试脚本

测试完整流程：
1. 下载同行视频
2. Whisper识别文案
3. 千问改写原创
4. 音色克隆 + TTS配音
5. 口型同步
6. 字幕生成
7. 配乐（可选）
8. 画中画（可选）

用法:
python3 run_pipeline.py \
    --video-link "https://v.douyin.com/xxxxx" \
    --user-video /path/to/user.mp4 \
    --user-audio /path/to/user_voice.wav \
    --music /path/to/music.mp3 \
    --output /path/to/output.mp4
"""

import asyncio
import argparse
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.video_downloader import download_video
from app.services.speech_to_text import transcribe
from app.services.text_rewrite import rewrite
from app.services.voice_clone import clone_and_synthesize
from app.services.lip_sync import generate_lip_sync, download_result, generate_lip_sync_by_provider
from app.services.subtitle import generate_srt, burn_subtitle
from app.services.music import add_music, MusicOptions
from app.services.pip import add_pip

@dataclass
class PipelineOptions:
    """Pipeline配置选项"""
    # 文案改写风格
    rewrite_style: str = "口语化"

    # 是否添加字幕
    add_subtitle: bool = True

    # 字幕样式
    subtitle_position: str = "bottom"

    # 配乐配置 (None表示不加配乐)
    music_path: Optional[str] = None
    music_volume: float = 0.3
    music_fade_in: float = 1.0
    music_fade_out: float = 1.0

    # 画中画配置 (None表示不加画中画)
    pip_video: Optional[str] = None
    pip_position: str = "右下角"

    # 字幕样式
    font_size: int = 24

    # 口型同步服务
    lip_sync_provider: str = "infinite_talk"  # "infinite_talk" 或 "kling"

@dataclass
class PipelineResult:
    """Pipeline执行结果"""
    original_video_path: str = ""     # 同行视频
    user_video_path: str = ""          # 用户视频
    user_audio_path: str = ""          # 用户声音
    original_text: str = ""            # 原始文案
    rewritten_text: str = ""           # 改写后文案
    tts_audio_path: str = ""          # TTS音频
    lip_sync_url: str = ""            # 口型同步视频URL
    lip_sync_path: str = ""           # 口型同步视频本地路径
    final_video_path: str = ""         # 最终视频

async def run_pipeline(
    video_link: str,
    user_video: str,
    user_audio: str,
    output_dir: str = "./results",
    options: Optional[PipelineOptions] = None
) -> PipelineResult:
    """执行完整Pipeline

    Args:
        video_link: 同行视频链接
        user_video: 用户自己的视频(不说话)
        user_audio: 用户声音参考音频
        output_dir: 输出目录
        options: 配置选项

    Returns:
        PipelineResult: 执行结果
    """
    if options is None:
        options = PipelineOptions()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = PipelineResult(
        user_video_path=user_video,
        user_audio_path=user_audio
    )

    print("=" * 60)
    print("AI口播视频生成 Pipeline")
    print("=" * 60)

    # Step 1: 下载同行视频
    print("\n[Step 1/8] 下载同行视频...")
    video_result = await download_video(video_link)
    result.original_video_path = video_result.video_path
    print(f"  视频: {video_result.video_path}")
    print(f"  时长: {video_result.duration}s")

    # Step 2: Whisper识别文案
    print("\n[Step 2/8] Whisper识别文案...")
    transcription = await transcribe(video_result.video_path)
    result.original_text = transcription.text
    print(f"  识别文字数: {len(transcription.text)}")
    print(f"  分段数: {len(transcription.segments)}")

    # Step 3: 千问改写
    print("\n[Step 3/8] 千问改写文案...")
    result.rewritten_text = await rewrite(transcription.text, options.rewrite_style)
    print(f"  改写后: {result.rewritten_text[:50]}...")

    # Step 4: 音色克隆 + TTS配音
    print("\n[Step 4/8] 音色克隆 + TTS配音...")
    tts_result = await clone_and_synthesize(user_audio, result.rewritten_text)
    result.tts_audio_path = tts_result.audio_path
    print(f"  音频: {tts_result.audio_path}")
    print(f"  时长: {tts_result.duration}s")

    # Step 5: 口型同步
    print(f"\n[Step 5/8] 口型同步({options.lip_sync_provider})...")
    lip_sync_result = await generate_lip_sync_by_provider(
        user_video, tts_result.audio_path, provider=options.lip_sync_provider
    )
    result.lip_sync_url = lip_sync_result.get("video_path", "")
    result.lip_sync_path = lip_sync_result["video_path"]
    print(f"  提供商: {lip_sync_result['provider']}")
    print(f"  视频: {result.lip_sync_path}")
    print(f"  时长: {lip_sync_result['duration']}s")

    # Step 6: 字幕生成
    current_video = result.lip_sync_path
    if options.add_subtitle:
        print("\n[Step 6/8] 生成字幕...")
        subtitle_path = generate_srt(tts_result.audio_path)
        print(f"  字幕: {subtitle_path}")

        # 烧录字幕
        print("  烧录字幕到视频...")
        current_video = burn_subtitle(
            current_video,
            subtitle_path,
            str(output_dir / "step6_subtitle.mp4")
        )
        print(f"  完成: {current_video}")

    # Step 7: 配乐
    if options.music_path:
        print("\n[Step 7/8] 添加配乐...")
        music_opts = MusicOptions(
            volume=options.music_volume,
            fade_in=options.music_fade_in,
            fade_out=options.music_fade_out
        )
        current_video = add_music(
            current_video,
            options.music_path,
            str(output_dir / "step7_music.mp4"),
            music_opts
        )
        print(f"  完成: {current_video}")

    # Step 8: 画中画
    if options.pip_video:
        print("\n[Step 8/8] 添加画中画...")
        current_video = add_pip(
            current_video,
            options.pip_video,
            options.pip_position,
            str(output_dir / "step8_pip.mp4")
        )
        print(f"  完成: {current_video}")

    # 最终结果
    result.final_video_path = current_video

    print("\n" + "=" * 60)
    print("Pipeline 执行完成!")
    print("=" * 60)
    print(f"最终视频: {result.final_video_path}")

    return result


def main():
    parser = argparse.ArgumentParser(description="AI口播视频生成 Pipeline")
    parser.add_argument("--video-link", required=True, help="同行视频链接")
    parser.add_argument("--user-video", required=True, help="用户视频(不说话)")
    parser.add_argument("--user-audio", required=True, help="用户声音参考音频")
    parser.add_argument("--output", default="./results", help="输出目录")
    parser.add_argument("--style", default="口语化", help="改写风格")
    parser.add_argument("--no-subtitle", action="store_true", help="不加字幕")
    parser.add_argument("--music", help="配乐文件")
    parser.add_argument("--pip-video", help="画中画视频")
    parser.add_argument("--pip-position", default="右下角", help="画中画位置")
    parser.add_argument("--lip-sync-provider", default="infinite_talk",
                        choices=["infinite_talk", "kling"],
                        help="口型同步服务 (默认: infinite_talk)")

    args = parser.parse_args()

    options = PipelineOptions(
        rewrite_style=args.style,
        add_subtitle=not args.no_subtitle,
        music_path=args.music,
        pip_video=args.pip_video,
        pip_position=args.pip_position,
        lip_sync_provider=args.lip_sync_provider
    )

    result = asyncio.run(run_pipeline(
        args.video_link,
        args.user_video,
        args.user_audio,
        args.output,
        options
    ))

    print("\n" + "=" * 60)
    print("执行摘要")
    print("=" * 60)
    print(f"原始文案: {result.original_text[:100]}...")
    print(f"改写文案: {result.rewritten_text[:100]}...")
    print(f"最终视频: {result.final_video_path}")


if __name__ == "__main__":
    main()
