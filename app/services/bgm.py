#!/usr/bin/env python3
"""内置BGM服务 - 热门背景音乐库"""

import os
import requests
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum

_no_proxy_session = requests.Session()
_no_proxy_session.trust_env = False

BASE_DIR = Path(__file__).parent.parent.parent
BGM_DIR = BASE_DIR / "assets" / "music"

# BGM 分类
class BGMCategory(Enum):
    UPBEAT = "upbeat"          # 活力动感
    CALM = "calm"             # 安静舒缓
    EMOTIONAL = "emotional"    # 情感叙事
    TRENDY = "trendy"          # 网红热门
    CHINESE = "chinese"        # 国风中医
    CINEMATIC = "cinematic"    # 电影感"

@dataclass
class BGMTrack:
    id: str
    name: str
    artist: str
    category: BGMCategory
    duration: float      # 时长(秒)
    path: Optional[str] = None   # 本地路径
    url: Optional[str] = None    # 或远程URL

# 内置BGM列表 (可扩展)
# 实际使用时需确保文件已下载
BUILT_IN_BGMS: List[BGMTrack] = [
    BGMTrack(
        id="vibrant_days",
        name="阳光活力",
        artist="SoundHelix",
        category=BGMCategory.UPBEAT,
        duration=370.0,
        path=str(BGM_DIR / "vibrant_days.mp3"),
        url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
    ),
    BGMTrack(
        id="peaceful_mind",
        name="平静心灵",
        artist="SoundHelix",
        category=BGMCategory.CALM,
        duration=370.0,
        path=str(BGM_DIR / "peaceful_mind.mp3"),
        url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3"
    ),
    BGMTrack(
        id="warm_memory",
        name="温暖记忆",
        artist="SoundHelix",
        category=BGMCategory.EMOTIONAL,
        duration=370.0,
        path=str(BGM_DIR / "warm_memory.mp3"),
        url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-7.mp3"
    ),
    BGMTrack(
        id="Inspiring_Cinematic",
        name="励志电影",
        artist="SoundHelix",
        category=BGMCategory.CINEMATIC,
        duration=370.0,
        path=str(BGM_DIR / "Inspiring_Cinematic.mp3"),
        url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3"
    ),
    BGMTrack(
        id="sunny_morning",
        name="阳光早晨",
        artist="SoundHelix",
        category=BGMCategory.TRENDY,
        duration=370.0,
        path=str(BGM_DIR / "sunny_morning.mp3"),
        url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3"
    ),
    BGMTrack(
        id="gentle_chill",
        name="轻柔 Chill",
        artist="SoundHelix",
        category=BGMCategory.CALM,
        duration=370.0,
        path=str(BGM_DIR / "gentle_chill.mp3"),
        url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-4.mp3"
    ),
]

def get_bgm_by_id(bgm_id: str) -> Optional[BGMTrack]:
    """根据ID获取BGM"""
    for bgm in BUILT_IN_BGMS:
        if bgm.id == bgm_id:
            return bgm
    return None

def get_bgm_by_category(category: BGMCategory) -> List[BGMTrack]:
    """获取指定分类的所有BGM"""
    return [bgm for bgm in BUILT_IN_BGMS if bgm.category == category]

def list_all_bgm() -> List[BGMTrack]:
    """列出所有BGM"""
    return BUILT_IN_BGMS

def list_bgm_by_category() -> dict:
    """按分类列出BGM"""
    result = {}
    for category in BGMCategory:
        bgms = get_bgm_by_category(category)
        if bgms:
            result[category.value] = bgms
    return result

def ensure_bgm_downloaded(bgm: BGMTrack) -> str:
    """确保BGM已下载，返回本地路径"""
    if bgm.path and Path(bgm.path).exists():
        return bgm.path

    # 确保目录存在
    BGM_DIR.mkdir(parents=True, exist_ok=True)

    # 下载
    if bgm.url:
        print(f">>> 下载BGM: {bgm.name} ({bgm.url})")
        response = _no_proxy_session.get(bgm.url, stream=True, timeout=60)
        response.raise_for_status()

        local_path = bgm.path
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f">>> BGM下载完成: {local_path}")
        return local_path

    raise FileNotFoundError(f"BGM文件不存在: {bgm.id}")

def download_all_bgm():
    """下载所有内置BGM（首次使用前调用）"""
    BGM_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []
    failed = []

    for bgm in BUILT_IN_BGMS:
        if bgm.path and Path(bgm.path).exists():
            print(f">>> {bgm.name} 已存在，跳过")
            downloaded.append(bgm.name)
            continue

        try:
            ensure_bgm_downloaded(bgm)
            downloaded.append(bgm.name)
        except Exception as e:
            print(f">>> {bgm.name} 下载失败: {e}")
            failed.append(bgm.name)

    return downloaded, failed

def get_random_bgm() -> BGMTrack:
    """获取随机BGM"""
    import random
    return random.choice(BUILT_IN_BGMS)


if __name__ == "__main__":
    print("=" * 50)
    print("内置BGM列表")
    print("=" * 50)

    by_category = list_bgm_by_category()
    for cat, bgms in by_category.items():
        print(f"\n【{cat}】")
        for bgm in bgms:
            status = "✓" if bgm.path and Path(bgm.path).exists() else "✗"
            print(f"  {status} [{bgm.id}] {bgm.name} - {bgm.artist} ({bgm.duration}s)")

    print("\n" + "=" * 50)
    print("下载所有BGM: python3 -m app.services.bgm")
    print("=" * 50)
