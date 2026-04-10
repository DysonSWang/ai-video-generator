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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._download_sync, url)

    def _extract_video_id_from_url(self, url: str) -> Optional[str]:
        """从各种格式的分享文本中提取视频URL"""
        # 先从文本中提取第一个 http URL（处理抖音分享文本，如 "2.53 hBg:/... https://v.douyin.com/xxx..."）
        url_match = re.search(r'https?://[^\s<>"\']+', url)
        if url_match:
            url = url_match.group(0)

        # 格式1: https://www.douyin.com/video/7321451298934405416
        m = re.search(r'/video/(\d+)', url)
        if m:
            return m.group(1), f"https://www.douyin.com/video/{m.group(1)}"

        # 格式2: 短链接 https://v.douyin.com/xxxxx/
        m = re.search(r'v\.douyin\.com/([a-zA-Z0-9_]+)', url)
        if m:
            return None, f"https://v.douyin.com/{m.group(1)}/"

        # 格式3: 搜索页 https://www.douyin.com/search/关键词?modal_id=6889391315725946119
        if '/search/' in url:
            return None, None  # 需要访问页面后提取

        return None, None

    def _download_sync(self, url: str) -> VideoResult:
        """同步下载方法

        严格模式：必须使用 CDP（用户 Chrome），不使用 headless 降级。
        headless 容易被抖音检测拦截，返回错误结果，不应作为 fallback。
        """
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            # 检查 Chrome CDP 端口是否可用
            import socket
            try:
                with socket.create_connection(("localhost", self.cdp_port), timeout=2):
                    pass
            except (socket.timeout, OSError):
                raise ConnectionError(
                    f"无法连接到 Chrome CDP（端口 {self.cdp_port}）。"
                    "请确保已启动 Chrome 并开启远程调试：\n"
                    "chrome --remote-debugging-port=9223\n"
                    "或通过 Playwright 启动 Chrome。"
                )

            # CDP 可用：连接用户 Chrome，新开独立窗口
            try:
                browser = p.chromium.connect_over_cdp(
                    f"http://localhost:{self.cdp_port}",
                    timeout=30000
                )
            except Exception as e:
                raise ConnectionError(f"CDP 连接失败: {e}")

            # 创建独立 context 和 page，不复用用户现有的标签页
            context = browser.new_context()
            page = context.new_page()

            try:
                # 抖音视频URL处理
                video_id, direct_url = self._extract_video_id_from_url(url)

                if '/search/' in url:
                    # 搜索页：需要先访问，提取真实视频链接
                    print(f">>> 访问搜索页: {url}")
                    page.goto(url, timeout=60000, wait_until='domcontentloaded')
                    page.wait_for_timeout(3000)

                    # 从页面提取真实视频链接（避免 modal_id 广告ID）
                    real_url = page.evaluate("""() => {
                        // 找第一个非广告的视频链接
                        const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
                        for (const link of links) {
                            const href = link.href;
                            // 排除广告链接（通常包含 modal_id 或特殊参数）
                            if (href && !href.includes('modal_id=') && !href.includes('source=')) {
                                return href;
                            }
                        }
                        // 如果都包含modal_id，取第一个
                        if (links.length > 0) {
                            return links[0].href;
                        }
                        return null;
                    }""")

                    if not real_url:
                        page.screenshot(path='/tmp/video_download_debug.png')
                        raise ValueError("未找到视频链接")

                    # 从提取的链接重新获取 video_id
                    m = re.search(r'/video/(\d+)', real_url)
                    if m:
                        video_id = m.group(1)
                        direct_url = f"https://www.douyin.com/video/{video_id}"
                        print(f">>> 提取到真实视频ID: {video_id}")
                    else:
                        direct_url = real_url
                        video_id = None

                    # 跳转到视频页
                    print(f">>> 跳转到: {direct_url}")
                    page.goto(direct_url, timeout=60000, wait_until='domcontentloaded')
                    page.wait_for_timeout(2000)

                else:
                    # 直接视频页
                    if not direct_url:
                        direct_url = url
                    print(f">>> 访问: {direct_url}")
                    page.goto(direct_url, timeout=60000, wait_until='domcontentloaded')
                    page.wait_for_timeout(5000)

                    # 短链接会302重定向到这里，重新提取 video_id
                    if not video_id:
                        final_url = page.url
                        m = re.search(r'/video/(\d+)', final_url)
                        if m:
                            video_id = m.group(1)
                            print(f">>> 从重定向URL提取到video_id: {video_id}")

                # 多次尝试提取视频URL（抖音视频URL有窗口期）
                video_url = None
                for attempt in range(10):
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
                        pass
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
                        const el = document.querySelector('h1, [data-e2e="video-title"], .desc, [data-e2e="video-detail-desc"], title');
                        return (el?.innerText || document.title || '视频').split('-')[0].split('\\n')[0].trim();
                    }""")
                except Exception:
                    title = "视频"
                title = re.sub(r'[\\/:*?"<>|]', '_', title)[:50] or "视频"

                if not video_url or not video_url.startswith('http'):
                    page.screenshot(path='/tmp/video_download_debug.png')
                    raise ValueError("未找到视频地址")

                print(f">>> 标题: {title}")
                print(f">>> 视频URL: {video_url[:80]}...")

                # 获取视频时长
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
                # 用 video_id（如果有）作为文件名，避免 title 不稳定导致文件错乱
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:50]
                if video_id:
                    filepath = OUTPUT_DIR / f"dy_{video_id}.mp4"
                else:
                    filepath = OUTPUT_DIR / f"{safe_title}.mp4"

                # 检查是否已有同文件且有音轨，避免重复覆盖
                import subprocess
                if filepath.exists():
                    check = subprocess.run(
                        ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(filepath)],
                        capture_output=True, text=True
                    )
                    if check.stdout.strip() == 'audio':
                        print(f">>> 文件已存在且有音轨，跳过下载: {filepath.name}")
                        return VideoResult(video_path=str(filepath), duration=duration, desc=title)
                    # 无音轨（如纯视频或下载不完整），重新下载
                    print(f">>> 文件已存在但无音轨，重新下载: {filepath.name}")

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
