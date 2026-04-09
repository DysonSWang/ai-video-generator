#!/usr/bin/env python3
"""AI口播视频生成系统 - FastAPI主入口"""

import asyncio
import uuid
import sqlite3
import json
import time as time_module
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from contextlib import contextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 导入服务
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.video_downloader import download_video
from app.services.speech_to_text import transcribe
from app.services.text_rewrite import rewrite
from app.services.voice_clone import clone_and_synthesize
from app.services.lip_sync import generate_lip_sync_by_provider
from app.services.subtitle import generate_srt_async, generate_srt_from_rewritten, burn_subtitle, SubtitleStyle
from app.services.music import add_music, MusicOptions
from app.services.pip import add_pip
from app.config import CDP_PORT

# ============== 配置 ==============
BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "assets"
OUTPUT_DIR = UPLOAD_DIR / "outputs"
TASKS_DIR = OUTPUT_DIR / "tasks"
DB_PATH = BASE_DIR / "tasks.db"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TASKS_DIR.mkdir(parents=True, exist_ok=True)

# ============== 模板配置 ==============
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# ============== 数据库 ==============

def init_db():
    """初始化SQLite数据库"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT,
            progress INTEGER,
            message TEXT,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            task_start_time REAL
        )
    """)
    # 兼容已有数据：若无 task_start_time 列则添加
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN task_start_time REAL")
    except sqlite3.OperationalError:
        pass  # 列已存在
    conn.commit()
    conn.close()

def save_task(task_id: str, status: str, progress: int, message: str,
              result: Optional[dict] = None, task_start_time: Optional[float] = None):
    """保存任务状态到数据库"""
    conn = sqlite3.connect(DB_PATH)
    result_json = json.dumps(result) if result else None
    conn.execute(
        "INSERT OR REPLACE INTO tasks (task_id, status, progress, message, result, task_start_time) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, status, progress, message, result_json, task_start_time)
    )
    conn.commit()
    conn.close()

def get_task(task_id: str) -> Optional[dict]:
    """从数据库获取任务状态，含 elapsed_seconds"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT task_id, status, progress, message, result, created_at, task_start_time FROM tasks WHERE task_id = ?",
        (task_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        now = time_module.time()
        task_start = row[6] if row[6] else now
        elapsed = now - task_start
        return {
            "task_id": row[0],
            "status": row[1],
            "progress": row[2],
            "message": row[3],
            "result": json.loads(row[4]) if row[4] else None,
            "created_at": row[5],
            "task_start_time": row[6],
            "elapsed_seconds": elapsed
        }
    return None

# 初始化数据库
init_db()

# ============== 数据模型 ==============

@dataclass
class PipelineOptions:
    rewrite_style: str = "口语化"
    add_subtitle: bool = True
    subtitle_position: str = "bottom"
    music_path: Optional[str] = None  # 自定义音乐文件路径
    music_bgm_id: Optional[str] = None  # 内置BGM ID (vibrant_days/peaceful_mind/warm_memory/Inspiring_Cinematic/sunny_morning/gentle_chill)
    music_volume: float = 0.3
    pip_video: Optional[str] = None
    pip_position: str = "右下角"
    lip_sync_provider: str = "infinite_talk"  # "infinite_talk" 或 "kling"
    lip_sync_mode: str = "图片数字人"  # InfiniteTalk模式: "图片数字人" 或 "视频数字人"

class VideoLinkRequest(BaseModel):
    url: str

class PipelineRequest(BaseModel):
    video_link: str
    user_video_id: str
    user_audio_id: str
    options: Optional[PipelineOptions] = None

class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    result_url: Optional[str] = None

# ============== FastAPI 应用 ==============
app = FastAPI(
    title="AI口播视频生成系统",
    description="用户上传自己的形象视频和声音，系统自动生成会说话的数字人视频",
    version="1.0.0"
)

# ============== 辅助函数 ==============

def _resolve_file_path(upload_dir: Path, file_id: str, extensions: list) -> Optional[str]:
    """根据file_id查找实际文件路径"""
    for ext in extensions:
        path = upload_dir / f"{file_id}{ext}"
        if path.exists():
            return str(path)
        # 也尝试不带后缀匹配
        for p in upload_dir.iterdir():
            if p.stem == file_id and p.suffix in extensions:
                return str(p)
    return None

async def save_upload_file(upload_file: UploadFile, subdir: str) -> str:
    """保存上传文件"""
    save_dir = UPLOAD_DIR / subdir
    save_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    ext = Path(upload_file.filename).suffix if upload_file.filename else ".mp4"
    file_path = save_dir / f"{file_id}{ext}"

    with open(file_path, "wb") as f:
        content = await upload_file.read()
        f.write(content)

    return str(file_path)

def _run_sync_in_executor(loop, func, *args):
    """在线程池中运行同步函数"""
    return loop.run_in_executor(None, func, *args)

def _extract_frame_from_video(video_path: str, output_path: str, timestamp: float = 1.0) -> str:
    """从视频中提取一帧作为图片

    Args:
        video_path: 视频文件路径
        output_path: 输出图片路径
        timestamp: 提取时间点(秒)，默认1秒

    Returns:
        str: 生成的图片路径
    """
    import subprocess
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'ffmpeg', '-y', '-ss', str(timestamp), '-i', video_path,
        '-vframes', '1', '-q:v', '2', output_path
    ], capture_output=True)
    print(f">> 从视频提取帧: {output_path}")
    return output_path

# ============== API路由 ==============

@app.get("/")
async def root():
    """渲染前端页面"""
    with open(Path(__file__).parent / "templates" / "index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...)):
    """上传用户视频(不说话)"""
    try:
        file_path = await save_upload_file(file, "videos")
        return {"video_id": Path(file_path).stem, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/audio")
async def upload_audio(file: UploadFile = File(...)):
    """上传用户声音参考音频"""
    try:
        file_path = await save_upload_file(file, "audios")
        return {"audio_id": Path(file_path).stem, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/music")
async def upload_music(file: UploadFile = File(...)):
    """上传配乐"""
    try:
        file_path = await save_upload_file(file, "music")
        return {"music_id": Path(file_path).stem, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/extract")
async def extract_from_link(request: VideoLinkRequest):
    """从抖音链接提取视频文案"""
    try:
        video_result = await download_video(request.url)
        transcription = await transcribe(video_result.video_path)
        return {
            "video_path": video_result.video_path,
            "duration": video_result.duration,
            "text": transcription.text,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in transcription.segments
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/pipeline/run")
async def run_pipeline(request: PipelineRequest, background_tasks: BackgroundTasks):
    """启动完整Pipeline"""
    task_id = str(uuid.uuid4())

    # 保存初始状态到数据库
    save_task(task_id, "pending", 0, "任务已创建")

    # 后台执行
    background_tasks.add_task(
        execute_pipeline,
        task_id,
        request.video_link,
        request.user_video_id,
        request.user_audio_id,
        request.options
    )

    return {"task_id": task_id}

async def execute_pipeline(task_id: str, video_link: str, user_video_id: str,
                          user_audio_id: str, options: Optional[PipelineOptions]):
    """执行Pipeline"""
    loop = asyncio.get_event_loop()
    task_start_time = time_module.time()

    try:
        save_task(task_id, "processing", 5, "准备中...", task_start_time=task_start_time)

        # 解析文件路径 (根据file_id查找实际文件)
        user_video = _resolve_file_path(UPLOAD_DIR / "videos", user_video_id, ['.mp4', '.mov', '.avi', '.mkv'])
        user_audio = _resolve_file_path(UPLOAD_DIR / "audios", user_audio_id, ['.wav', '.mp3', '.m4a', '.aac'])

        if not user_video:
            raise FileNotFoundError(f"用户视频不存在: {user_video_id}")
        if not user_audio:
            raise FileNotFoundError(f"用户音频不存在: {user_audio_id}")

        # Step 1: 下载同行视频
        save_task(task_id, "processing", 10, "下载同行视频...", task_start_time=task_start_time)
        video_result = await download_video(video_link)

        # Step 2: Whisper识别
        save_task(task_id, "processing", 25, "识别语音文案...", task_start_time=task_start_time)
        transcription = await transcribe(video_result.video_path)

        # Step 3: 千问改写
        save_task(task_id, "processing", 40, "改写文案...", task_start_time=task_start_time)
        rewritten = await rewrite(transcription.text, options.rewrite_style if options else "口语化")


        # Step 4: 音色克隆 + TTS
        save_task(task_id, "processing", 55, "克隆声音并配音...", task_start_time=task_start_time)
        tts_result = await clone_and_synthesize(user_audio, rewritten)

        # Step 5: 口型同步
        save_task(task_id, "processing", 70, "生成口型同步视频...", task_start_time=task_start_time)
        provider = options.lip_sync_provider if options else "infinite_talk"
        lip_sync_mode = options.lip_sync_mode if options and options.lip_sync_mode else "图片数字人"

        from app.services.lip_sync import generate_lip_sync_by_provider

        # InfiniteTalk需要从视频提取帧作为图片
        if provider == "infinite_talk":
            person_image_path = str(TASKS_DIR / f"{task_id}_person.jpg")
            _extract_frame_from_video(user_video, person_image_path)

            # 视频数字人模式需要传入ref_video
            ref_video = None
            if lip_sync_mode == "视频数字人":
                ref_video = user_video

            lip_sync_result = await generate_lip_sync_by_provider(
                person_image_path, tts_result.audio_path,
                provider=provider,
                mode=lip_sync_mode,
                ref_video=ref_video,
                output_path=str(TASKS_DIR / f"{task_id}_lipsync.mp4"),
                task_id=task_id
            )
        else:
            # Kling直接使用视频
            lip_sync_result = await generate_lip_sync_by_provider(
                user_video, tts_result.audio_path, provider=provider,
                output_path=str(TASKS_DIR / f"{task_id}_lipsync.mp4"),
                task_id=task_id
            )
        current_video = lip_sync_result["video_path"]

        # Step 6: 字幕
        if options and options.add_subtitle:
            save_task(task_id, "processing", 85, "添加字幕...", task_start_time=task_start_time)
            # 用改写文案 + 原始时间戳生成字幕（避免重新转录 TTS 音频造成的误差）
            subtitle_path = str(TASKS_DIR / f"{task_id}_subtitle.srt")
            generate_srt_from_rewritten(rewritten, transcription.segments, subtitle_path)
            current_video = await loop.run_in_executor(
                None, burn_subtitle, current_video, subtitle_path,
                str(TASKS_DIR / f"{task_id}_subtitled.mp4"), None
            )

        # Step 7: 配乐
        if options and (options.music_path or options.music_bgm_id):
            save_task(task_id, "processing", 90, "添加配乐...", task_start_time=task_start_time)
            # 优先使用自定义音乐，否则用内置BGM
            music_file = options.music_path
            if not music_file and options.music_bgm_id:
                from app.services.bgm import get_bgm_by_id
                bgm = get_bgm_by_id(options.music_bgm_id)
                if bgm and bgm.path:
                    music_file = bgm.path
            if music_file:
                music_opts = MusicOptions(volume=options.music_volume, fade_in=0.5, fade_out=0.5)
                current_video = await loop.run_in_executor(
                    None, add_music, current_video, music_file,
                    str(TASKS_DIR / f"{task_id}_music.mp4"), music_opts
                )

        # Step 8: 画中画
        if options and options.pip_video:
            save_task(task_id, "processing", 95, "添加画中画...", task_start_time=task_start_time)
            current_video = await loop.run_in_executor(
                None, add_pip, current_video, options.pip_video, options.pip_position,
                str(TASKS_DIR / f"{task_id}_pip.mp4")
            )

        # 完成
        save_task(task_id, "completed", 100, "完成!", {
            "video_path": current_video,
            "original_text": transcription.text,
            "rewritten_text": rewritten
        }, task_start_time=task_start_time)

    except Exception as e:
        save_task(task_id, "failed", 0, f"失败: {str(e)}", task_start_time=task_start_time)

@app.get("/api/tasks")
async def list_tasks(limit: int = 20, offset: int = 0):
    """获取任务历史列表"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT task_id, status, progress, message, result, created_at, task_start_time
           FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset)
    ).fetchall()
    conn.close()
    return [
        {
            "task_id": r[0],
            "status": r[1],
            "progress": r[2],
            "message": r[3],
            "result": json.loads(r[4]) if r[4] else None,
            "created_at": r[5],
            "task_start_time": r[6],
        }
        for r in rows
    ]

@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@app.get("/api/result/{task_id}")
async def get_result(task_id: str):
    """获取生成结果"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务未完成")
    result = task.get("result")
    if not result or "video_path" not in result:
        raise HTTPException(status_code=500, detail="结果文件不存在")
    video_path = result["video_path"]
    if not Path(video_path).exists():
        raise HTTPException(status_code=500, detail="视频文件不存在")
    return FileResponse(video_path, media_type="video/mp4", filename="result.mp4")

# ============== 启动 ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
