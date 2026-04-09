#!/usr/bin/env python3
"""InfiniteTalk 口型同步服务 - 调用远程ComfyUI GPU服务器"""

import json
import time
import asyncio
import subprocess
import httpx
import paramiko
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from app.config import (
    INFINITETALK_URL, INFINITETALK_HOST, INFINITETALK_PORT,
    INFINITETALK_USER, INFINITETALK_PASSWORD, INFINITETALK_OUTPUT_PATH
)

MAX_RETRIES = 3
RETRY_DELAY = 2.0

@dataclass
class InfiniteTalkResult:
    video_path: str   # 本地保存路径
    duration: float  # 视频时长(秒)


def make_file_data(path: str, orig_name: str = None, mime_type: str = None) -> dict:
    """构建FileData对象"""
    return {
        "path": path,
        "url": None,
        "size": None,
        "orig_name": orig_name,
        "mime_type": mime_type,
        "is_stream": False,
        "meta": {"_type": "gradio.FileData"}
    }

def make_video_data(video_path: str, orig_name: str = None, mime_type: str = None) -> dict:
    """构建VideoData对象 (用于ref_vid)"""
    return {
        "video": make_file_data(video_path, orig_name, mime_type),
        "subtitles": None
    }


def upload_file(file_path: str, server_url: str = INFINITETALK_URL) -> str:
    """上传文件到InfiniteTalk服务器"""
    with open(file_path, 'rb') as f:
        resp = httpx.post(
            f"{server_url}/gradio_api/upload",
            files={"files": f},
            timeout=60.0,
            trust_env=False  # 禁用代理，避免socks代理问题
        )
    result = resp.json()
    server_path = result[0] if isinstance(result, list) else result.get('path', result)
    print(f">>> 文件上传完成: {server_path}")
    return server_path


async def generate_infinite_talk(
    person_image: str,
    audio_path: str,
    output_path: Optional[str] = None,
    mode: str = "图片数字人",
    ref_video: Optional[str] = None,  # 视频数字人模式的参考视频
    poll_interval: float = 10.0,
    max_wait: float = 600.0,
    task_id: Optional[str] = None   # 用于追踪的 UUID
) -> InfiniteTalkResult:
    """调用InfiniteTalk生成口型同步视频

    Args:
        person_image: 用户照片路径(不说话，只露脸)
        audio_path: 配音音频路径
        output_path: 输出视频路径
        mode: "图片数字人" 或 "视频数字人"
        ref_video: 参考视频路径(视频数字人模式使用)
        poll_interval: 轮询间隔(秒)
        max_wait: 最大等待时间(秒)
        task_id: 可选的追踪ID，用于日志和任务记录

    Returns:
        InfiniteTalkResult: 包含本地视频路径和时长
    """
    if output_path is None:
        output_path = str(Path(__file__).parent.parent.parent / "assets" / "outputs" / "infinite_talk_result.mp4")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print(f">>> 上传图片到InfiniteTalk服务器...")

    # 1. 上传图片
    person_img_server = upload_file(person_image)

    # 2. 上传音频
    print(f">>> 上传音频到InfiniteTalk服务器...")
    audio_server = upload_file(audio_path)

    # 3. 上传参考视频(视频数字人模式)
    ref_vid_server = None
    if mode == "视频数字人" and ref_video:
        print(f">>> 上传参考视频到InfiniteTalk服务器...")
        ref_vid_server = upload_file(ref_video)

    # 4. 调用inference
    print(f">>> 调用InfiniteTalk推理 (mode={mode})...")

    # 根据文件扩展名推断mime_type
    img_ext = Path(person_image).suffix.lower()
    audio_ext = Path(audio_path).suffix.lower()

    img_mime = "image/jpeg" if img_ext in [".jpg", ".jpeg"] else "image/png" if img_ext == ".png" else "image/webp"
    audio_mime = "audio/wav" if audio_ext == ".wav" else "audio/mp4" if audio_ext == ".mp4" else "audio/mpeg" if audio_ext == ".mp3" else "audio/m4a"

    # ref_vid的mime_type
    ref_vid_mime = None
    if ref_vid_server:
        ref_ext = Path(ref_video).suffix.lower()
        ref_vid_mime = "video/mp4" if ref_ext == ".mp4" else "video/webm" if ref_ext == ".webm" else "video/mov"

    inference_data = {
        "data": [
            mode,                                           # mode
            make_file_data(person_img_server, Path(person_image).name, img_mime),  # person_img
            make_video_data(ref_vid_server, Path(ref_video).name, ref_vid_mime) if ref_vid_server else None,  # ref_vid (VideoData格式)
            make_file_data(audio_server, Path(audio_path).name, audio_mime),    # audio1
            None,                                           # audio2
            "",                                             # pos prompt
            "",                                             # neg prompt
            480,                                            # w (竖版视频宽度，9:16)
            832,                                            # h (竖版视频高度)
            4,                                              # st (推理步数, 已有质量平衡)
            0,                                              # bl (blocks_to_swap=0: 全GPU计算，速度最快)
            81,                                             # frame_size (81: 更大窗口，充分利用显存)
            -1,                                             # seed (-1表示随机)
            False,                                          # hd_enabled
            720,                                            # hd_res
            25,                                             # fps
            True,                                           # cam_ctrl
            True                                            # pose_stabilize
        ]
    }

    resp = httpx.post(
        f"{INFINITETALK_URL}/gradio_api/call/add_to_queue_wrapper",
        json=inference_data,
        timeout=30.0,
        trust_env=False
    )

    if resp.status_code != 200:
        raise RuntimeError(f"推理请求失败: {resp.status_code} - {resp.text}")
    event_id = resp.json().get('event_id')
    if not event_id:
        raise RuntimeError(f"未获取到event_id: {resp.text}")
    print(f">>> 任务ID: {event_id}")

    # 记录任务提交（用于追踪）
    from .infinite_talk_manager import (
        record_submission, update_prompt_id, get_queue_position,
        check_history_completion, extract_prompt_id_from_sse, interrupt_task,
        find_task_by_input_files, COMFYUI_API
    )
    _task_id = task_id or str(uuid.uuid4())
    record_submission(event_id, _task_id)

    # 记录提交前的最新文件 mtime（用于 mtime 兜底策略）
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        INFINITETALK_HOST, port=INFINITETALK_PORT,
        username=INFINITETALK_USER, password=INFINITETALK_PASSWORD, timeout=60
    )
    sftp = client.open_sftp()

    def get_latest_mtime():
        try:
            files = [f for f in sftp.listdir(INFINITETALK_OUTPUT_PATH)
                     if f.startswith('InfiniteTalk_') and f.endswith('.mp4')]
            return max((sftp.stat(f'{INFINITETALK_OUTPUT_PATH}/{f}').st_mtime for f in files), default=0)
        except Exception:
            return 0

    baseline_mtime = get_latest_mtime()
    sftp.close()
    client.close()

    audio_basename = Path(audio_path).name
    image_basename = Path(person_image).name

    start_time = time.time()

    # 方法1: 通过 ComfyUI /queue 查找 prompt_id（主方法）
    print(f">>> 通过 ComfyUI /queue 查找任务...")
    prompt_id = None
    while time.time() - start_time < max_wait:
        # 查询 ComfyUI queue，从 running/pending 任务中匹配我们的输入文件
        candidate_pid = find_task_by_input_files(audio_basename, image_basename)
        if candidate_pid:
            prompt_id = candidate_pid
            update_prompt_id(event_id, prompt_id)
            print(f">>> 获取到 Prompt ID: {prompt_id[:8]}...")
            break

        elapsed = int(time.time() - start_time)
        running, pending = get_queue_position()
        queue_info = f"队列:{running}运行/{pending}等待" if running >= 0 else ""
        print(f">>> 等待任务进入 ComfyUI... ({elapsed}s) {queue_info}")

        await asyncio.sleep(poll_interval)

    # 如果 queue 中找不到（任务已立即完成并出队），尝试 history
    if not prompt_id:
        print(f">>> 任务不在 queue 中，尝试 history...")
        from .infinite_talk_manager import check_history_completion
        # 遍历最近几条 history，查找匹配输入的
        try:
            resp = httpx.get(f"{COMFYUI_API}/history", timeout=10, trust_env=False)
            hist = resp.json()
            prompt_ids = list(hist.keys())
            for pid in reversed(prompt_ids[-10:]):
                outputs = hist[pid].get('outputs', {})
                for node_id, node_output in outputs.items():
                    for key in ('gifs', 'videos', 'filename'):
                        if key in node_output:
                            fname = node_output[key] if key != 'gifs' else node_output[key][0].get('filename', '')
                            if isinstance(fname, str) and audio_basename.lower() in fname.lower():
                                prompt_id = pid
                                update_prompt_id(event_id, prompt_id)
                                print(f">>> 从 history 找到 Prompt ID: {prompt_id[:8]}...")
                                break
                if prompt_id:
                    break
        except Exception as e:
            print(f">>> History 查询失败: {e}")

    # 初始化 audio_filename（用于后续下载段）
    audio_filename_in_history = None

    # 方法1: 如果拿到了 prompt_id，使用 ComfyUI API 精确追踪
    if prompt_id:
        print(f">>> 通过 ComfyUI API 精确追踪 Prompt ID: {prompt_id[:8]}...")
        poll_start = time.time()
        result_filename = None
        while time.time() - poll_start < max_wait:
            await asyncio.sleep(10)
            result = check_history_completion(prompt_id)
            if result:
                if 'filename' in result:
                    # 直接拿到 video 文件名
                    result_filename = result['filename']
                elif 'derived_video' in result:
                    # 只有 audio 文件，尝试推导 video 文件名
                    result_filename = result['derived_video']
                else:
                    result_filename = None

                if result_filename:
                    print(f">>> 任务完成! 输出文件: {result_filename}")
                    break
            running, pending = get_queue_position()
            elapsed = int(time.time() - poll_start)
            print(f">>> 等待中... ({elapsed}s) 队列:{running}运行/{pending}等待")
        else:
            # 超时，尝试中断
            print(f">>> ⚠️ 追踪超时，发送中断指令...")
            interrupt_task()
            raise TimeoutError(f"任务超时 {max_wait}s")

        if not result_filename:
            raise RuntimeError("未能从 history 中获取输出文件名")

        # 通过 ComfyUI API 拿到了输出文件名，构建路径
        remote_path = f'{INFINITETALK_OUTPUT_PATH}/{result_filename}'
        # audio 文件可能是 InfiniteTalk_00037-audio.mp4（history 返回 audio 时）
        audio_filename_in_history = result.get('audio_filename')
        new_file = result_filename  # 用于后续日志

        # 先等待文件稳定（文件可能在历史标记完成后仍在写入）
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            INFINITETALK_HOST, port=INFINITETALK_PORT,
            username=INFINITETALK_USER, password=INFINITETALK_PASSWORD, timeout=60
        )
        sftp = client.open_sftp()
        print(f">>> 等待文件稳定: {result_filename}")
        last_size = -1
        for _ in range(60):
            try:
                stat = sftp.stat(remote_path)
                current_size = stat.st_size
                if current_size > 10 * 1024 and current_size == last_size and last_size > 0:
                    print(f">>> 文件稳定: {current_size / 1024 / 1024:.1f}MB")
                    break
                print(f">>> 文件写入中: {current_size / 1024 / 1024:.1f}MB")
                last_size = current_size
            except FileNotFoundError:
                # 文件还不存在，继续等待
                current_size = 0
                if last_size > 0:
                    print(f">>> 文件还未出现，等待...")
                last_size = -1
            except Exception as e:
                print(f">>> 检查文件大小: {e}")
                current_size = 0
                last_size = -1
            await asyncio.sleep(5)
        else:
            print(f">>> 警告: 文件可能未完全写入")
        sftp.close()
        client.close()

    else:
        # 方法2: 兜底 - 使用 mtime 轮询
        print(f">>> ⚠️ 未获取到 Prompt ID，回退到 mtime 轮询...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            INFINITETALK_HOST, port=INFINITETALK_PORT,
            username=INFINITETALK_USER, password=INFINITETALK_PASSWORD, timeout=60
        )
        sftp = client.open_sftp()

        def get_infinite_talk_files():
            try:
                all_files = sftp.listdir(INFINITETALK_OUTPUT_PATH)
                return sorted(
                    [f for f in all_files if f.startswith('InfiniteTalk_') and f.endswith('.mp4') and not f.endswith('-audio.mp4')],
                    key=lambda f: sftp.stat(f'{INFINITETALK_OUTPUT_PATH}/{f}').st_mtime, reverse=True
                )
            except Exception as e:
                print(f">>> 获取文件列表失败: {e}")
                return []

        poll_start = time.time()
        new_file = None
        while time.time() - poll_start < max_wait:
            await asyncio.sleep(5)
            files = get_infinite_talk_files()
            if files:
                latest = files[0]
                latest_mtime = sftp.stat(f'{INFINITETALK_OUTPUT_PATH}/{latest}').st_mtime
                if latest_mtime > baseline_mtime:
                    print(f">>> 检测到新文件: {latest}")
                    new_file = latest
                    break
                elapsed = int(time.time() - poll_start)
                print(f">>> 等待中... ({elapsed}s)，最新: {latest}")
            else:
                print(f">>> 等待中... ({int(time.time() - poll_start)}s)，目录为空")

        if not new_file:
            files = get_infinite_talk_files()
            new_file = files[0] if files else None

        if not new_file:
            sftp.close()
            client.close()
            raise RuntimeError(f"输出目录中没有 InfiniteTalk 文件")

        remote_path = f'{INFINITETALK_OUTPUT_PATH}/{new_file}'
        audio_remote_path = f'{INFINITETALK_OUTPUT_PATH}/{new_file}-audio.mp4'

        # 等待文件稳定
        last_size = -1
        for _ in range(60):
            try:
                stat = sftp.stat(remote_path)
                current_size = stat.st_size
                if current_size > 10 * 1024 and current_size == last_size and last_size > 0:
                    print(f">>> 文件稳定: {current_size / 1024 / 1024:.1f}MB")
                    break
                print(f">>> 文件写入中: {current_size / 1024 / 1024:.1f}MB")
                last_size = current_size
            except FileNotFoundError:
                current_size = 0
                last_size = -1
                print(f">>> 文件还未出现，等待...")
            except Exception as e:
                print(f">>> 检查文件大小: {e}")
                current_size = 0
                last_size = -1
            await asyncio.sleep(5)
        else:
            print(f">>> 警告: 文件可能未完全写入")

        sftp.close()
        client.close()

    # 6. 下载视频文件
    print(f">>> 下载结果: {new_file}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        INFINITETALK_HOST,
        port=INFINITETALK_PORT,
        username=INFINITETALK_USER,
        password=INFINITETALK_PASSWORD,
        timeout=60
    )
    sftp = client.open_sftp()

    # 下载主视频
    remote_video_path = f'{INFINITETALK_OUTPUT_PATH}/{new_file}'
    sftp.get(remote_video_path, output_path)
    print(f">>> 视频下载完成: {output_path}")

    # 获取音频时长用于验证
    import subprocess as _subprocess
    audio_dur_result = _subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
        capture_output=True, text=True
    )
    expected_duration = float(audio_dur_result.stdout.strip() or 0)
    print(f">>> 期望视频时长: {expected_duration:.1f}s（基于音频）")

    # 验证时长
    dur_result = _subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
        capture_output=True, text=True
    )
    actual_duration = float(dur_result.stdout.strip() or 0)
    duration_diff = abs(actual_duration - expected_duration)

    # 如果时长不匹配，尝试重新下载最新的文件（最多重试2次）
    if duration_diff > 2.0:
        print(f">>> ⚠️ 时长不匹配: {actual_duration:.1f}s vs 期望 {expected_duration:.1f}s")
        for retry in range(2):
            await asyncio.sleep(10)
            # 重新获取最新文件
            files = sorted(
                [f for f in sftp.listdir(INFINITETALK_OUTPUT_PATH)
                 if f.startswith('InfiniteTalk_') and f.endswith('.mp4') and not f.endswith('-audio.mp4')],
                key=lambda f: sftp.stat(f'{INFINITETALK_OUTPUT_PATH}/{f}').st_mtime,
                reverse=True
            )
            if files and files[0] != new_file:
                new_file = files[0]
                remote_video_path = f'{INFINITETALK_OUTPUT_PATH}/{new_file}'
                sftp.get(remote_video_path, output_path)
                print(f">>> 重试下载: {new_file}")
                dur_result = _subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
                    capture_output=True, text=True
                )
                actual_duration = float(dur_result.stdout.strip() or 0)
                if abs(actual_duration - expected_duration) <= 2.0:
                    print(f">>> 时长验证通过: {actual_duration:.1f}s")
                    break
        else:
            print(f">>> ⚠️ 重试后仍不匹配，使用当前文件")

    # 下载对应的音频文件（InfiniteTalk 会生成 xxx-audio.mp4）
    # audio_filename_in_history 存在时使用它（如 InfiniteTalk_00037-audio.mp4）
    audio_remote_path = (
        f'{INFINITETALK_OUTPUT_PATH}/{audio_filename_in_history}'
        if audio_filename_in_history
        else f'{INFINITETALK_OUTPUT_PATH}/{new_file}-audio.mp4'
    )
    local_audio_path = output_path.replace('.mp4', '_audio.mp4')
    try:
        sftp.get(audio_remote_path, local_audio_path)
        print(f">>> 音频下载完成: {local_audio_path}")
    except FileNotFoundError:
        print(f">>> 音频文件不存在（{audio_remote_path}），跳过音频合并")
        local_audio_path = None

    sftp.close()
    client.close()

    print(f">>> InfiniteTalk完成: {output_path} ({actual_duration:.1f}s)")
    return InfiniteTalkResult(video_path=output_path, duration=actual_duration)


if __name__ == "__main__":
    import sys
    import asyncio

    if len(sys.argv) < 3:
        print("用法: python3 infinite_talk.py <照片> <音频>")
        sys.exit(1)

    person_img = sys.argv[1]
    audio = sys.argv[2]

    print(f">>> 照片: {person_img}")
    print(f">>> 音频: {audio}")

    result = asyncio.run(generate_infinite_talk(person_img, audio))
    print(f"\n>>> 完成!")
    print(f">>> 视频: {result.video_path}")
    print(f">>> 时长: {result.duration}s")