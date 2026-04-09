#!/usr/bin/env python3
"""视频下载服务 - 基于dyd项目Playwright CDP方式"""

import re
import time
import asyncio
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from playwright.sync_api import sync_playwright, Playwright
from playwright_stealth import Stealth

# CDP配置
CDP_PORT = 9223
OUTPUT_DIR = Path(__file__).parent.parent.parent / "assets" / "videos"

@dataclass
class VideoResult:
    video_path: str
    duration: float
    desc: str  # 视频描述/文案

class VideoDownloader:
    def __init__(self, cdp_port: int = CDP_PORT):
        self.cdp_port = cdp_port

    async def download(self, url: str) -> VideoResult:
        """下载抖音/快手/小红书视频"""
        # 同步方法需要在线程池中运行
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._download_sync, url)

    def _download_sync(self, url: str) -> VideoResult:
        """同步下载方法"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(
                    f"http://localhost:{self.cdp_port}",
                    timeout=30000
                )
            except Exception as e:
                raise ConnectionError(f"CDP连接失败: {e}")

            context = browser.contexts[0]
            page = context.new_page()
            Stealth().apply_stealth_sync(page)

            try:
                print(f">>> 访问: {url}")
                page.goto(url, timeout=60000, wait_until='domcontentloaded')
                # 抖音视频URL动态加载，需要等待窗口期（约8秒出现后很快消失）
                page.wait_for_timeout(2000)

                # 多次尝试提取视频URL
                video_url = None
                for attempt in range(8):
                    try:
                        video_url = page.evaluate("""() => {
                            const v = document.querySelector('video');
                            if (!v) return null;
                            return v.currentSrc || v.src || null;
                        }""")
                        if video_url and video_url.startswith('http'):
                            print(f">>> 视频URL在第{attempt*2}秒提取成功")
                            break
                    except Exception:
                        pass  # 页面导航导致evaluate失败，重试
                    page.wait_for_timeout(2000)

                # 如果 JS 提取失败，尝试从 HTML 源码提取
                if not video_url or not video_url.startswith('http'):
                    html = page.content()
                    for pattern in [
                        r'"playApiMark["\']\s*:\s*["\']([^"\']+)',
                        r'playAddr["\']\s*:\s*["\']([^"\']+)',
                        r'playwm["\']\s*:\s*["\']([^"\']+)',
                        r'"video_url["\']\s*:\s*["\']([^"\']+)',
                    ]:
                        m = re.search(pattern, html)
                        if m:
                            video_url = m.group(1)
                            break

                # 获取标题
                try:
                    title = page.evaluate("""() => {
                        const el = document.querySelector('h1, [data-e2e="video-title"], .desc, title');
                        return (el?.innerText || document.title || '视频').split('-')[0].split('\\n')[0].trim();
                    }""")
                except Exception:
                    title = "视频"
                title = re.sub(r'[\\/:*?"<>|]', '_', title)[:50] or "视频"

                if not video_url or not video_url.startswith('http'):
                    # 截图保存调试
                    page.screenshot(path='/tmp/video_download_debug.png')
                    raise ValueError("未找到视频地址")

                print(f">>> 标题: {title}")
                print(f">>> 视频URL: {video_url[:80]}...")

                # 获取视频时长（视频URL已获取后再等一下让它加载）
                page.wait_for_timeout(2000)
                try:
                    duration = page.evaluate("""() => {
                        const v = document.querySelector('video');
                        return (v && v.readyState > 0) ? v.duration : 0;
                    }""")
                except Exception:
                    duration = 0

                page.close()

                # 下载视频
                filepath = OUTPUT_DIR / f"{title}.mp4"

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.douyin.com/'
                }

                response = requests.get(video_url, headers=headers, stream=True, timeout=300)
                if not response.ok:
                    raise ValueError(f"下载失败: {response.status_code}")

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                size = filepath.stat().st_size // 1024
                print(f">>> 完成: {title}.mp4 ({size}KB)")

                return VideoResult(
                    video_path=str(filepath),
                    duration=duration,
                    desc=title
                )

            except Exception as e:
                raise RuntimeError(f"下载失败: {e}")
            finally:
                page.close()
                browser.close()


async def download_video(url: str) -> VideoResult:
    """快捷函数"""
    downloader = VideoDownloader()
    return await downloader.download(url)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 video_downloader.py <视频链接>")
        sys.exit(1)

    result = asyncio.run(download_video(sys.argv[1]))
    print(f"\n结果:")
    print(f"  路径: {result.video_path}")
    print(f"  时长: {result.duration}s")
    print(f"  文案: {result.desc}")
