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

    # 构建force_style参数（包含边距防止字幕贴边）
    HORIZONTAL_MARGIN = 50  # 水平边距，防止字幕贴边
    force_style = (
        f"FontSize={style.font_size},"
        f"PrimaryColour=&H{style.font_color[2:]},"
        f"OutlineColour=&H{style.outline_color[2:]},"
        f"Outline={style.outline_width},"
        f"Bold={1 if style.bold else 0},"
        f"MarginL={HORIZONTAL_MARGIN},"
        f"MarginR={HORIZONTAL_MARGIN},"
        f"MarginV={style.margin_v}"
    )

    # 位置调整（ASS Alignment: 7=左上 8=上中 9=右上, 4=左中 5=居中 6=右中, 1=左下 2=下中 3=右下）
    if style.position == "bottom":
        force_style += ",Alignment=2"
    elif style.position == "top":
        force_style += ",Alignment=8"
    elif style.position == "center":
        force_style += ",Alignment=5"

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
        text = text.strip()
        if not text:
            continue
        start_sec = (i / num_sentences) * total_duration
        end_sec = ((i + 1) / num_sentences) * total_duration
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


def _strip_punctuation(text: str) -> str:
    """去除所有中文标点符号，保留纯文字，标点处用空格替换"""
    import re
    # 常见中文标点 + 英文标点 -> 替换为空格
    return re.sub(r'[，。！？、：；""''（）【】《》—…\.,!?;:\"\'\(\)\[\]\-–—]', ' ', text)


def _format_ass_time(seconds: float) -> str:
    """ASS时间格式: H:MM:SS.cc (厘秒)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _wrap_text(text: str, max_chars: int = 14) -> str:
    """将长字幕文本拆分为多行，避免超出视频边界

    原理：ASS的\\N替换效果是真正的换行，不会溢出。
    按 max_chars 拆分，优先在标点（，或、）处断开。
    """
    if not text or len(text) <= max_chars:
        return text

    import re
    lines = []
    start = 0
    while start < len(text):
        remaining = len(text) - start
        if remaining <= max_chars:
            lines.append(text[start:])
            break

        chunk = text[start:start + max_chars]
        break_pos = -1

        for i in range(len(chunk) - 1, -1, -1):
            if chunk[i] in '，、':
                break_pos = i + 1
                break

        if break_pos > 0:
            lines.append(chunk[:break_pos])
            start += break_pos
        else:
            lines.append(chunk)
            start += max_chars

    return '\\N'.join(lines)


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

    # 按自然停顿点拆分（句末标点 + 逗号/顿号）
    # 逗号和顿号是语音停顿点，适合做字幕分段
    all_chunks = []
    paragraphs = rewritten_text.split('\n')
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 先按句末标点拆成句子
        parts = re.split(r'([。！？])', para)
        for i in range(0, len(parts) - 1, 2):
            s = parts[i].strip()
            p = parts[i + 1] if i + 1 < len(parts) else ''
            if not s:
                continue
            sentence = s + p
            # 句子太长则按逗号/顿号再拆
            comma_parts = re.split(r'([，、])', s)
            sub_chunks = []
            for j in range(0, len(comma_parts) - 1, 2):
                chunk = (comma_parts[j].strip() + (comma_parts[j + 1] if j + 1 < len(comma_parts) else ''))
                if chunk:
                    sub_chunks.append(chunk)
            if len(comma_parts) % 2 == 1 and comma_parts[-1].strip():
                sub_chunks.append(comma_parts[-1].strip())
            # 只有一个chunk时，加上句末标点
            if len(sub_chunks) == 1:
                all_chunks.append(sentence)
            else:
                all_chunks.extend(sub_chunks)
        if len(parts) % 2 == 1 and parts[-1].strip():
            all_chunks.append(parts[-1].strip())

    sentences = [s for s in all_chunks if s.strip()]

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
Style: Default,SimHei,{style.font_size},&H00{style.font_color[2:]},&H000000FF,&H00{style.outline_color[2:]},&H00000000,{1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline_width},{style.outline_width},2,50,50,120,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Alignment=5 = middle-center in ASS
    dialogue_lines = []
    num_sentences = len(sentences)

    # ASS \N 替换效果：让字幕逐条替换（不叠加）
    REPLACE_EFFECT = "\\N"

    # 按字数比例分配时长：每句话的时长 = (句子字数 / 总字数) * 总音频时长
    # 中文字数（含标点）作为权重，标点也占一点时间
    char_counts = []
    for s in sentences:
        s = s.strip()
        if not s:
            char_counts.append(0)
        else:
            # 中文字符每个算1，英文每个算0.5，空格忽略
            count = sum(1 if '\u4e00' <= c <= '\u9fff' else 0.5 if c.isalnum() else 0.3 for c in s)
            char_counts.append(max(count, 1))
    total_chars = sum(char_counts) or 1

    cumulative_time = 0.0
    import re
    for i, text in enumerate(sentences):
        text = text.strip()
        if not text:
            continue
        # 去掉标点符号用于显示，并自动换行超长文本
        text_display = re.sub(r'[，。！？、：；""''（）【】《》—…\.,!?;:"\'\(\)\[\]\-–—\s·]', '', text)
        text_display = _wrap_text(text_display, max_chars=14)

        char_weight = char_counts[i] / total_chars
        duration = char_weight * total_duration
        start_sec = cumulative_time
        end_sec = cumulative_time + duration
        cumulative_time = end_sec

        # 只用\N替换效果，不做mid-sentence拆分
        # ASS的WrapStyle=0会根据视频宽度自动换行
        # MarginL=50,MarginR=50 防止贴边
        dialogue_lines.append(
            f"Dialogue: 0,{_format_ass_time(start_sec)},{_format_ass_time(end_sec)},Default,,50,50,120,{REPLACE_EFFECT},{text_display}"
        )

    content = ass_header + '\n'.join(dialogue_lines) + '\n'

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f">>> ASS字幕生成（改写文案）: {output_path} ({num_sentences} 句)")

    return content


async def generate_ass_from_tts_audio(
    rewritten_text: str,
    tts_audio_path: str,
    output_path: Optional[str] = None,
    style: Optional[SubtitleStyle] = None,
) -> str:
    """用Whisper word-level时间戳生成ASS字幕

    步骤：
    1. 用medium模型转写TTS音频（word_timestamps=True）
    2. 把Whisper识别的每个字转为简体，取得每个字的精确时间戳
    3. 把rewrite_text按句子拆分
    4. 对每个rewrite句子，用字符级LCS匹配到Whisper识别结果
    5. 匹配到的字符用Whisper实际时间戳；未匹配的字符按上下文插值

    Args:
        rewritten_text: 改写后的完整文案
        tts_audio_path: TTS生成的音频文件路径
        output_path: ASS文件输出路径
        style: 字幕样式

    Returns:
        ASS文件路径
    """
    import re

    if style is None:
        style = SubtitleStyle()

    # 简繁映射（逐字替换，按长度降序排列避免部分替换）
    T2S = {
        '應該': '应该', '陰陽': '阴阳', '問題': '问题', '覺得': '觉得',
        '雖然': '虽然', '影響': '影响', '處理': '处理', '獲得': '获得',
        '標準': '标准', '什麼': '什么',
        # 单字
        '關': '关', '註': '注', '論': '论', '語': '语', '說': '说', '為': '为', '個': '个',
        '過': '过', '時': '时', '來': '来', '業': '业', '師': '师', '務': '务', '經': '经',
        '濟': '济', '開': '开', '門': '门', '間': '间', '題': '题', '員': '员', '責': '责',
        '學': '学', '習': '习', '國': '国', '會': '会', '長': '长', '種': '种',
        '還': '还', '點': '点', '與': '与', '這': '这', '無': '无', '處': '处',
        '總': '总', '給': '给', '義': '义', '質': '质', '觀': '观', '頭': '头', '對': '对',
        '於': '于', '補': '补', '訊': '讯', '聽': '听', '讓': '让', '變': '变',
        '愛': '爱', '親': '亲', '孤': '独', '證': '证', '據': '据', '複': '复', '擔': '担',
        '協': '协', '認': '认', '識': '识', '標': '标', '樣': '样', '報': '报', '紙': '纸',
        '誤': '误', '議': '议', '從': '从', '織': '织', '線': '线', '結': '结',
        '車': '车', '網': '网', '電': '电', '靈': '灵', '廣': '广', '異': '异', '餘': '余',
        '確': '确', '應': '应', '負': '负', '們': '们', '別': '别', '夠': '够', '裡': '里',
        '請': '请', '陰': '阴', '陽': '阳', '壓': '压', '機': '机', '價': '价',
        '諮': '咨', '雖': '虽', '處': '处', '麼': '么',
        '覺': '觉', '著': '着', '見': '见', '現': '现', '資': '资', '東': '东',
        '遠': '远', '產': '产', '場': '场', '爭': '争',
        # 异体/常见错误
        '陰陽': '阴阳',  # 重申
    }

    def to_simp(text):
        # 按长度降序排列，避免短匹配优先于长匹配
        sorted_keys = sorted(T2S.keys(), key=len, reverse=True)
        for k in sorted_keys:
            if k in text:
                text = text.replace(k, T2S[k])
        return text

    def strip_punc(text):
        return re.sub(r'[，。！？、：；""''（）【】《》—…\.,!?;:"\'\(\)\[\]\-–—\s·]', '', text)

    # 1. Whisper转写（word-level timestamps）
    from .speech_to_text import transcribe
    result = await transcribe(tts_audio_path, model_name="medium")

    # 2. 收集所有Whisper word（转为简体）
    ws_words = []
    for seg in result.segments:
        if seg.words:
            for w in seg.words:
                ws_words.append({
                    'word': to_simp(w.word.strip()),
                    'start': w.start,
                    'end': w.end
                })
        else:
            # 无word级，用整段（很少见）
            ws_words.append({
                'word': to_simp(seg.text.strip()),
                'start': seg.start,
                'end': seg.end
            })

    if not ws_words:
        print(">>> Whisper无word输出，回退到字数比例估算")
        return generate_ass_from_rewritten(
            rewritten_text, [],
            output_path,
            audio_duration=result.segments[-1].end if result.segments else 0,
            style=style
        )

    total_duration = ws_words[-1]['end'] - ws_words[0]['start']
    ws_text = ''.join(w['word'] for w in ws_words)
    print(f">>> Whisper word数: {len(ws_words)}, 总时长: {ws_words[-1]['end']:.2f}s")
    print(f">>> Whisper文本: {ws_text[:80]}...")

    # 3. 按句子拆分rewrite_text
    all_chunks = []
    paragraphs = rewritten_text.split('\n')
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 先按句末标点拆
        parts = re.split(r'([。！？])', para)
        for i in range(0, len(parts) - 1, 2):
            s = parts[i].strip()
            p = parts[i + 1] if i + 1 < len(parts) else ''
            if not s:
                continue
            sentence = s + p
            # 句子内按顿号/逗号再拆分
            comma_parts = re.split(r'([，、])', s)
            sub_chunks = []
            for j in range(0, len(comma_parts) - 1, 2):
                chunk = (comma_parts[j].strip() + (comma_parts[j + 1] if j + 1 < len(comma_parts) else ''))
                if chunk:
                    sub_chunks.append(chunk)
            if len(comma_parts) % 2 == 1 and comma_parts[-1].strip():
                sub_chunks.append(comma_parts[-1].strip())
            if len(sub_chunks) == 1:
                all_chunks.append(sentence)
            else:
                all_chunks.extend(sub_chunks)
        if len(parts) % 2 == 1 and parts[-1].strip():
            all_chunks.append(parts[-1].strip())

    sentences = [s.strip() for s in all_chunks if s.strip()]
    if not sentences:
        return ""
    print(f">>> 句子数: {len(sentences)}")

    # 4. 对每个句子，在Whisper结果中贪心匹配
    REPLACE_EFFECT = "\\N"
    dialogue_lines = []
    ws_pos = 0  # Whisper words 遍历位置（贪心）

    for sent in sentences:
        sent_stripped = strip_punc(sent)
        if not sent_stripped:
            continue

        # 去掉标点符号用于显示，并自动换行超长文本
        sent_display = re.sub(r'[，。！？、：；""''（）【】《》—…\.,!?;:"\'\(\)\[\]\-–—\s·]', '', sent)
        sent_display = _wrap_text(sent_display, max_chars=14)

        # 在Whisper words剩余部分找最佳匹配（贪心）
        best_len = 0
        best_i = -1
        best_j = -1
        best_score = 0

        for i in range(ws_pos, len(ws_words)):
            combined = ''
            for j in range(i, len(ws_words)):
                combined += ws_words[j]['word']
                score = 2 * len(set(sent_stripped) & set(combined)) / (len(sent_stripped) + len(combined)) if combined else 0
                if score > best_score:
                    best_score = score
                    best_i = i
                    best_j = j
                    best_len = len(combined)

        if best_i >= 0 and best_score >= 0.20:
            start_sec = ws_words[best_i]['start']
            end_sec = ws_words[best_j]['end']
            dialogue_lines.append(
                f"Dialogue: 0,{_format_ass_time(start_sec)},{_format_ass_time(end_sec)},Default,,50,50,120,{REPLACE_EFFECT},{sent_display}"
            )
            ws_pos = best_j + 1
        else:
            # 未匹配：按剩余时间均分
            if ws_pos < len(ws_words):
                used_dur = ws_words[ws_pos - 1]['end'] if ws_pos > 0 else ws_words[0]['start']
                remaining_dur = ws_words[-1]['end'] - used_dur
            else:
                remaining_dur = total_duration
            rem_sents = len(sentences) - len(dialogue_lines)
            dur = remaining_dur / max(rem_sents, 1)
            prev_end = ws_words[ws_pos - 1]['end'] if ws_pos > 0 else (ws_words[0]['start'] if ws_words else 0)
            start_sec = prev_end
            end_sec = start_sec + dur
            dialogue_lines.append(
                f"Dialogue: 0,{_format_ass_time(start_sec)},{_format_ass_time(end_sec)},Default,,50,50,120,{REPLACE_EFFECT},{sent_display}"
            )

    print(f">>> ASS字幕: {len(dialogue_lines)}条")

    # 5. 生成ASS文件（底部居中，两行显示）
    ass_header = f"""[Script Info]
Title=AI Video Subtitles
ScriptType=v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,SimHei,{style.font_size},&H00{style.font_color[2:]},&H000000FF,&H00{style.outline_color[2:]},&H00000000,{1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline_width},{style.outline_width},2,50,50,120,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    content = ass_header + '\n'.join(dialogue_lines) + '\n'

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f">>> ASS字幕生成（Word对齐）: {output_path} ({len(dialogue_lines)}句）")

    return content
