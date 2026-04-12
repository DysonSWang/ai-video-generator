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

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 导入服务
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.video_downloader import download_video, VideoResult
from app.services.speech_to_text import transcribe, TranscriptionSegment
from app.services.text_rewrite import rewrite, polish
from app.services.voice_clone import clone_and_synthesize
from app.services.lip_sync import generate_lip_sync_by_provider
from app.services.subtitle import generate_srt_async, generate_srt_from_rewritten, generate_ass_from_rewritten, generate_ass_from_tts_audio, burn_subtitle, SubtitleStyle
from app.services.speech_to_text import extract_audio
from app.services.music import add_music, MusicOptions
from app.services.pip import add_pip
from app.config import CDP_PORT

# Auth模块
from app.auth.database import init_auth_db
from app.auth.router import router as auth_router, get_current_user
from app.auth.models import User as AuthUser
from app.middleware.auth import AuthMiddleware

# ============== 辅助函数 ==============
def _merge_audio_to_video(video_path: str, audio_path: str, output_path: str) -> str:
    """将音频合并到视频（生成中间文件，供后续重新烧录字幕使用）"""
    import subprocess
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-map', '0:v',
        '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'fast',
        '-c:a', 'aac',
        '-shortest',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"音频合并失败: {result.stderr}")
    return output_path


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
            task_start_time REAL,
            pipeline_step INTEGER DEFAULT 0
        )
    """)
    # 兼容已有数据：若无 task_start_time 列则添加
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN task_start_time REAL")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 兼容已有数据：若无 pipeline_step 列则添加
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN pipeline_step INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # Auth: 兼容已有数据：若无 user_id 列则添加
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN user_id TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    conn.commit()
    conn.close()

def save_task(task_id: str, status: str, progress: int, message: str,
              result: Optional[dict] = None, task_start_time: Optional[float] = None,
              pipeline_step: Optional[int] = None, user_id: Optional[str] = None):
    """保存任务状态到数据库"""
    conn = sqlite3.connect(DB_PATH)
    result_json = json.dumps(result) if result else None
    if pipeline_step is None:
        # 保留现有值
        row = conn.execute("SELECT pipeline_step FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        pipeline_step = row[0] if row else 0
    conn.execute(
        "INSERT OR REPLACE INTO tasks (task_id, status, progress, message, result, task_start_time, pipeline_step, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, status, progress, message, result_json, task_start_time, pipeline_step, user_id)
    )
    conn.commit()
    conn.close()

def merge_task_result(task_id: str, updates: dict, user_id: Optional[str] = None):
    """只更新 result 字段中的某些键，保留其他键不变"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT status, progress, message, result, task_start_time, pipeline_step, user_id FROM tasks WHERE task_id = ?",
        (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    current_result = json.loads(row[3]) if row[3] else {}
    current_result.update(updates)
    pipeline_step = updates.get("pipeline_step", row[5] if len(row) > 5 else 0)
    # user_id 保留已有值
    existing_user_id = row[6] if len(row) > 6 else None
    conn.execute(
        "INSERT OR REPLACE INTO tasks (task_id, status, progress, message, result, task_start_time, pipeline_step, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, row[0], row[1], row[2], json.dumps(current_result), row[4], pipeline_step, existing_user_id or user_id)
    )
    conn.commit()
    conn.close()

def get_task(task_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """从数据库获取任务状态，含 elapsed_seconds 和 pipeline_step"""
    conn = sqlite3.connect(DB_PATH)
    if user_id:
        cursor = conn.execute(
            "SELECT task_id, status, progress, message, result, created_at, task_start_time, pipeline_step, user_id FROM tasks WHERE task_id = ? AND user_id = ?",
            (task_id, user_id)
        )
    else:
        cursor = conn.execute(
            "SELECT task_id, status, progress, message, result, created_at, task_start_time, pipeline_step, user_id FROM tasks WHERE task_id = ?",
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
            "elapsed_seconds": elapsed,
            "video_duration": json.loads(row[4]).get("video_duration") if row[4] else None,
            "pipeline_step": row[7] if len(row) > 7 else 0,
            "user_id": row[8] if len(row) > 8 else None,
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

class ExtractOnlyRequest(BaseModel):
    url: str

class RewriteTextRequest(BaseModel):
    text: str
    style: str = "口语化"


class ReburnSubtitleRequest(BaseModel):
    subtitle_text: str = ""

class PolishTextRequest(BaseModel):
    text: str

class PipelineRequest(BaseModel):
    video_link: str
    user_video_id: str
    user_audio_id: str
    options: Optional[PipelineOptions] = None
    confirmed_text: Optional[str] = None
    extracted_video_path: Optional[str] = None
    extracted_segments: Optional[list] = None  # 原始视频的Whisper段落（用于字幕时间戳）
    video_duration: Optional[float] = None  # 视频时长（秒），用于ETA估算

class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    result_url: Optional[str] = None
    video_duration: Optional[float] = None

# ============== FastAPI 应用 ==============
app = FastAPI(
    title="AI口播视频生成系统",
    description="用户上传自己的形象视频和声音，系统自动生成会说话的数字人视频",
    version="1.0.0"
)

# 注册Auth中间件和路由
app.add_middleware(AuthMiddleware)
app.include_router(auth_router)

@app.on_event("startup")
async def startup_recover_tasks():
    """启动时初始化Auth数据库 & 检测被中断的 processing 任务"""
    # 初始化Auth数据库
    init_auth_db()

    import time as time_module
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT task_id, message, result, task_start_time FROM tasks WHERE status = 'processing'"
    ).fetchall()
    conn.close()
    if not rows:
        return
    now = time_module.time()
    for row in rows:
        task_id, message, result_json, task_start = row
        elapsed = now - (task_start or now)
        last_step = 0
        video_path = None
        if result_json:
            try:
                r = json.loads(result_json)
                last_step = r.get("pipeline_step", 0)
                video_path = r.get("lip_sync_video_path") or r.get("subtitle_srt_path")
            except Exception:
                pass
        # 如果任务运行超过30分钟还没完成，视为被中断
        if elapsed > 1800:
            conn2 = sqlite3.connect(DB_PATH)
            conn2.execute(
                "UPDATE tasks SET status = 'failed', message = ? WHERE task_id = ?",
                (f"中断恢复（step {last_step}），上次运行 {int(elapsed//60)} 分钟前，请重新开始", task_id)
            )
            conn2.commit()
            conn2.close()
            print(f"[恢复] 任务 {task_id} 被中断（step={last_step}），已标记为失败")

# 挂载静态文件（用于视频预览）
app.mount("/assets", StaticFiles(directory=str(UPLOAD_DIR)), name="assets")
# 挂载静态文件（用于CSS和JS本地化）
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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

async def save_upload_file(upload_file: UploadFile, subdir: str, user_id: Optional[str] = None) -> str:
    """保存上传文件（多租户隔离）"""
    if user_id:
        save_dir = UPLOAD_DIR / user_id / subdir
    else:
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
    """从视频中提取一帧作为图片，并在上方添加padding防止头部被裁切

    Args:
        video_path: 视频文件路径
        output_path: 输出图片路径
        timestamp: 提取时间点(秒)，默认1秒

    Returns:
        str: 生成的图片路径
    """
    import subprocess
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    # 先提取帧
    temp_frame = output_path + '.temp.jpg'
    subprocess.run([
        'ffmpeg', '-y', '-ss', str(timestamp), '-i', video_path,
        '-vframes', '1', '-q:v', '2', temp_frame
    ], capture_output=True)
    # 获取原图尺寸
    size_proc = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'csv=p=0', temp_frame],
        capture_output=True, text=True)
    if size_proc.returncode == 0:
        w, h = map(int, size_proc.stdout.strip().split(','))
        # 在图片上方添加 padding（原图高度的15%），让头部往下移
        pad_top = int(h * 0.15)
        subprocess.run([
            'ffmpeg', '-y', '-i', temp_frame,
            '-vf', f'pad=iw:ih+{pad_top}:0:{pad_top}:color=black@0',
            '-q:v', '2', output_path
        ], capture_output=True)
        Path(temp_frame).unlink(missing_ok=True)
        print(f">> 从视频提取帧(加padding): {output_path}")
    else:
        Path(temp_frame).rename(output_path)
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

@app.get("/admin")
async def admin_page(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """渲染Admin后台页面（需管理员权限）"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    with open(Path(__file__).parent / "templates" / "admin.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/api/upload/video")
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    user: AuthUser = Depends(get_current_user),
):
    """上传用户视频(不说话)"""
    try:
        file_path = await save_upload_file(file, "videos", user_id=user.id)
        return {"video_id": Path(file_path).stem, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/audio")
async def upload_audio(
    request: Request,
    file: UploadFile = File(...),
    user: AuthUser = Depends(get_current_user),
):
    """上传用户声音参考音频"""
    try:
        file_path = await save_upload_file(file, "audios", user_id=user.id)
        return {"audio_id": Path(file_path).stem, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/music")
async def upload_music(
    request: Request,
    file: UploadFile = File(...),
    user: AuthUser = Depends(get_current_user),
):
    """上传配乐"""
    try:
        file_path = await save_upload_file(file, "music", user_id=user.id)
        return {"music_id": Path(file_path).stem, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/extract")
async def extract_from_link(
    request_body: VideoLinkRequest,
    user: AuthUser = Depends(get_current_user),
):
    """从抖音链接提取视频文案"""
    try:
        video_result = await download_video(request_body.url)
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

@app.post("/api/extract-only")
async def extract_only(
    request_body: ExtractOnlyRequest,
    user: AuthUser = Depends(get_current_user),
):
    """下载抖音视频并转录，返回原始文案（不启动pipeline）"""
    try:
        video_result = await download_video(request_body.url)
        transcription = await transcribe(video_result.video_path)
        # 转换为 HTTP 可访问的 URL
        video_url = video_result.video_path
        if video_url.startswith("/"):
            # 生成相对 URL 路径
            video_url = f"/assets/videos/{Path(video_result.video_path).name}"
        return {
            "video_path": video_result.video_path,
            "video_url": video_url,
            "duration": video_result.duration,
            "original_text": transcription.text,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in transcription.segments
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/polish-text")
async def polish_text(
    request: PolishTextRequest,
    user: AuthUser = Depends(get_current_user),
):
    """AI润色转录稿：修正识别错误、补全缺失"""
    try:
        polished = await polish(request.text)
        return {"polished_text": polished}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/rewrite-text")
async def rewrite_text(
    request: RewriteTextRequest,
    user: AuthUser = Depends(get_current_user),
):
    """AI改写文案"""
    try:
        rewritten = await rewrite(request.text, request.style)
        return {"rewritten_text": rewritten}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/pipeline/run")
async def run_pipeline(
    request: PipelineRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
):
    """启动完整Pipeline"""
    task_id = str(uuid.uuid4())

    # 保存初始状态到数据库
    save_task(task_id, "pending", 0, "任务已创建", user_id=user.id)

    # 后台执行
    background_tasks.add_task(
        execute_pipeline,
        task_id,
        user.id,
        request.video_link,
        request.user_video_id,
        request.user_audio_id,
        request.options,
        request.confirmed_text,
        request.extracted_video_path,
        request.extracted_segments,
        request.video_duration,
    )

    return {"task_id": task_id}

async def execute_pipeline(
    task_id: str,
    user_id: str,
    video_link: str,
    user_video_id: str,
    user_audio_id: str,
    options: Optional[PipelineOptions],
    confirmed_text: Optional[str] = None,
    extracted_video_path: Optional[str] = None,
    extracted_segments: Optional[list] = None,
    video_duration: Optional[float] = None,
):
    """执行Pipeline

    Args:
        user_id: 用户ID（多租户隔离）
        confirmed_text: 用户已确认的文案（有则跳过下载/转录/改写步骤）
        extracted_video_path: 已下载的视频路径（有则复用，避免重复下载）
        extracted_segments: 原始视频的Whisper段落（用于字幕时间戳）
    """
    loop = asyncio.get_event_loop()
    task_start_time = time_module.time()

    try:
        save_task(task_id, "processing", 5, "准备中...", task_start_time=task_start_time, user_id=user_id)

        # 解析文件路径 (根据file_id查找实际文件，多租户路径)
        user_video = _resolve_file_path(UPLOAD_DIR / user_id / "videos", user_video_id, ['.mp4', '.mov', '.avi', '.mkv', '.jpg', '.jpeg', '.png', '.webp', '.gif'])
        user_audio = _resolve_file_path(UPLOAD_DIR / user_id / "audios", user_audio_id, ['.wav', '.mp3', '.m4a', '.aac'])

        if not user_video:
            raise FileNotFoundError(f"用户视频不存在: {user_video_id}")
        if not user_audio:
            raise FileNotFoundError(f"用户音频不存在: {user_audio_id}")

        # Step 1: 下载同行视频（若有已确认文案则复用已下载的视频；无视频时跳过）
        if confirmed_text and extracted_video_path:
            # 复用已下载视频（识别流程过来的）
            save_task(task_id, "processing", 10, "复用已确认视频...", task_start_time=task_start_time, user_id=user_id)
            video_result = VideoResult(
                video_path=extracted_video_path,
                duration=0, desc=""
            )
            original_text = confirmed_text
            rewritten = confirmed_text
            original_segments = [
                TranscriptionSegment(**seg) if isinstance(seg, dict) else seg
                for seg in (extracted_segments or [])
            ]  # 用于字幕时间戳
            merge_task_result(task_id, {
                "original_video_path": extracted_video_path,
                "video_duration": video_duration or 0,
                "pipeline_step": 1
            }, user_id=user_id)
        elif confirmed_text and (not video_link or not video_link.strip()):
            # 直接粘贴文案模式：没有视频，跳过下载/转录/改写
            save_task(task_id, "processing", 10, "准备生成...", task_start_time=task_start_time, user_id=user_id)
            video_result = VideoResult(video_path="", duration=0, desc="")
            original_text = confirmed_text
            rewritten = confirmed_text
            original_segments = []
            merge_task_result(task_id, {
                "original_video_path": "",
                "video_duration": 0,
                "pipeline_step": 1
            }, user_id=user_id)
        else:
            # 正常流程：下载 → 转录 → 改写
            save_task(task_id, "processing", 10, "下载同行视频...", task_start_time=task_start_time, user_id=user_id)
            video_result = await download_video(video_link)
            merge_task_result(task_id, {
                "original_video_path": video_result.video_path,
                "video_duration": getattr(video_result, 'duration', 0),
                "pipeline_step": 1
            }, user_id=user_id)

            # Step 2: Whisper识别
            save_task(task_id, "processing", 25, "识别语音文案...", task_start_time=task_start_time, user_id=user_id)
            transcription = await transcribe(video_result.video_path)
            original_segments = transcription.segments
            merge_task_result(task_id, {
                "original_text": transcription.text,
                "video_duration": getattr(video_result, 'duration', 0),
                "pipeline_step": 2
            }, user_id=user_id)

            # Step 3: 千问改写
            save_task(task_id, "processing", 40, "改写文案...", task_start_time=task_start_time, user_id=user_id)
            original_text = transcription.text
            rewritten = await rewrite(original_text, options.rewrite_style if options else "口语化")
            merge_task_result(task_id, {"rewritten_text": rewritten, "pipeline_step": 3}, user_id=user_id)


        # Step 4: 音色克隆 + TTS
        save_task(task_id, "processing", 55, "克隆声音并配音...", task_start_time=task_start_time, user_id=user_id)
        tts_audio_path = str(TASKS_DIR / f"{task_id}_tts.mp3")
        # 创建数据库会话用于音色库查询/保存
        from app.auth.database import SessionLocal
        voice_db = SessionLocal()
        try:
            tts_result = await clone_and_synthesize(
                user_audio, rewritten,
                voice_name=f"user_{user_id[:8]}",
                output_path=tts_audio_path,
                db=voice_db,
                user_id=user_id,
            )
        finally:
            voice_db.close()
        merge_task_result(task_id, {
            "tts_audio_path": tts_result.audio_path,
            "pipeline_step": 4
        }, user_id=user_id)

        # Step 5: 口型同步
        save_task(task_id, "processing", 70, "生成口型同步视频...", task_start_time=task_start_time, user_id=user_id)
        provider = options.lip_sync_provider if options else "infinite_talk"

        from app.services.lip_sync import generate_lip_sync_by_provider

        # 判断上传的是图片还是视频
        VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
        user_ext = Path(user_video).suffix.lower()
        is_image = user_ext not in VIDEO_EXTS

        # 自动决定数字人模式：传视频→视频数字人，传图片→图片数字人
        lip_sync_mode = "视频数字人" if not is_image else "图片数字人"

        # InfiniteTalk：图片直接用，视频作为ref_video
        if provider == "infinite_talk":
            person_image_path = str(TASKS_DIR / f"{task_id}_person.jpg")
            if is_image:
                import shutil
                shutil.copy2(user_video, person_image_path)
                print(f">>> 使用上传图片作为形象: {person_image_path}")
            else:
                # 视频模式：提取一帧作为预览图，原始视频作为ref_video
                _extract_frame_from_video(user_video, person_image_path)

            # 视频数字人模式：上传的原始视频作为参考视频
            ref_video = user_video if not is_image else None

            lip_sync_result = await generate_lip_sync_by_provider(
                person_image_path, tts_result.audio_path,
                provider=provider,
                mode=lip_sync_mode,
                ref_video=ref_video,
                output_path=str(TASKS_DIR / f"{task_id}_lipsync.mp4"),
                task_id=task_id,
                max_wait=1800  # 30分钟，支持长任务
            )
        else:
            # Kling只支持视频，不支持图片
            if is_image:
                raise ValueError("可灵（Kling）不支持图片模式，请上传视频或切换到 InfiniteTalk 图片数字人模式")
            lip_sync_result = await generate_lip_sync_by_provider(
                user_video, tts_result.audio_path, provider=provider,
                output_path=str(TASKS_DIR / f"{task_id}_lipsync.mp4"),
                task_id=task_id,
                max_wait=1800  # 30分钟，支持长任务
            )
        current_video = lip_sync_result["video_path"]
        merge_task_result(task_id, {
            "lip_sync_video_path": current_video,
            "pipeline_step": 5
        }, user_id=user_id)

        # Step 6: 字幕
        if options and options.add_subtitle:
            save_task(task_id, "processing", 85, "添加字幕...", task_start_time=task_start_time, user_id=user_id)
            subtitle_style = SubtitleStyle(
                font_size=72,
                font_color="&HFFFFFF",
                outline_color="&H000000",
                outline_width=4,
                bold=True,
                position="bottom",
                margin_v=100
            )
            # 先合并音视频为中间文件（保留原始合并结果，供后续重新烧录字幕使用）
            lipsync_audio_path = str(TASKS_DIR / f"{task_id}_lipsync_audio.mp4")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _merge_audio_to_video,
                current_video, tts_result.audio_path, lipsync_audio_path)

            # 用Whisper转录TTS音频，获得真实词级时间戳，生成精确字幕
            subtitle_path = str(TASKS_DIR / f"{task_id}_subtitle.ass")
            await generate_ass_from_tts_audio(
                rewritten, tts_result.audio_path, subtitle_path, style=subtitle_style
            )

            # 烧录字幕（基于已合并音视频的视频，不再传audio_path避免重复）
            import uuid
            final_video_name = f"{task_id}_{uuid.uuid4().hex[:8]}_subtitled.mp4"
            current_video = await loop.run_in_executor(
                None, burn_subtitle, lipsync_audio_path, subtitle_path,
                str(TASKS_DIR / final_video_name), subtitle_style,
                None  # 不再传audio_path，避免音轨重复
            )
            merge_task_result(task_id, {
                "subtitle_ass_path": subtitle_path,
                "lipsync_audio_path": lipsync_audio_path,
                "tts_audio_path": tts_result.audio_path,
                "audio_duration": tts_result.duration,
                "rewritten_text": rewritten,
                "pipeline_step": 6
            }, user_id=user_id)

        # Step 7: 配乐
        if options and (options.music_path or options.music_bgm_id):
            save_task(task_id, "processing", 90, "添加配乐...", task_start_time=task_start_time, user_id=user_id)
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
                merge_task_result(task_id, {"pipeline_step": 7}, user_id=user_id)

        # Step 8: 画中画
        if options and options.pip_video:
            save_task(task_id, "processing", 95, "添加画中画...", task_start_time=task_start_time, user_id=user_id)
            current_video = await loop.run_in_executor(
                None, add_pip, current_video, options.pip_video, options.pip_position,
                str(TASKS_DIR / f"{task_id}_pip.mp4")
            )
            merge_task_result(task_id, {"pipeline_step": 8}, user_id=user_id)

        # 完成
        final_result = {
            "video_path": current_video,
            "original_video_path": lipsync_audio_path if options and options.add_subtitle else current_video,
            "original_text": original_text,
            "rewritten_text": rewritten,
            "video_duration": video_duration,
            "pipeline_step": 9,
            # 记录输入参数，便于历史追溯
            "video_link": video_link,
            "user_video_id": user_video_id,
            "user_audio_id": user_audio_id,
        }
        # 保留Step6的音频信息
        if options and options.add_subtitle:
            final_result["subtitle_ass_path"] = subtitle_path
            final_result["lipsync_audio_path"] = lipsync_audio_path
            final_result["tts_audio_path"] = tts_result.audio_path
            final_result["audio_duration"] = tts_result.duration
        save_task(task_id, "completed", 100, "完成!", final_result, task_start_time=task_start_time, user_id=user_id)

        # 记录用量
        try:
            from app.auth.usage_service import record_usage
            from app.auth.database import SessionLocal
            db = SessionLocal()
            try:
                duration = tts_result.duration if 'tts_result' in dir() else (video_duration or 0)
                record_usage(db, user_id, "task_count", 1, task_id=task_id)
                record_usage(db, user_id, "video_duration_seconds", int(duration), task_id=task_id)
            finally:
                db.close()
        except Exception as ue:
            print(f"[用量记录失败] {ue}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        save_task(task_id, "failed", 0, f"失败: {str(e)}", task_start_time=task_start_time, user_id=user_id)

@app.get("/api/tasks")
async def list_tasks(
    limit: int = 20,
    offset: int = 0,
    user: AuthUser = Depends(get_current_user),
):
    """获取任务历史列表（多租户隔离）"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT task_id, status, progress, message, result, created_at, task_start_time, pipeline_step
           FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (user.id, limit, offset)
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
            "pipeline_step": r[7] if len(r) > 7 else 0,
        }
        for r in rows
    ]

@app.get("/api/task/{task_id}")
async def get_task_status(
    task_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """获取任务状态"""
    task = get_task(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@app.get("/api/result/{task_id}")
async def get_result(
    task_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """获取生成结果"""
    task = get_task(task_id, user_id=user.id)
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


@app.post("/api/task/{task_id}/reburn-subtitle")
async def reburn_subtitle(
    task_id: str,
    request: dict,
    user: AuthUser = Depends(get_current_user),
):
    """重新烧录字幕（不改视频，只改字幕）

    优先使用 lipsync_audio_path（有独立音视频合并文件）。
    旧任务没有该文件时，直接用 video_path（含已合并音频）重新烧录。
    """
    task = get_task(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务未完成")

    result = task.get("result") or {}
    video_path = result.get("video_path")
    lipsync_audio = result.get("lipsync_audio_path")  # 新任务有
    tts_audio = result.get("tts_audio_path")
    audio_duration = result.get("audio_duration") or 0
    rewritten_text = request.get("subtitle_text", result.get("rewritten_text", ""))

    if not audio_duration and video_path and Path(video_path).exists():
        # 从视频文件获取音频时长
        import subprocess
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'csv=p=0', video_path],
                capture_output=True, text=True, timeout=10
            )
            audio_duration = float(probe.stdout.strip() or 0)
        except Exception:
            pass

    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=500, detail="视频文件不存在，请重新生成")

    # 优先用 original_video_path / lipsync_audio_path（无字幕的原版视频）
    # 新任务有 lipsync_audio_path；旧任务没有则尝试在任务目录里找 lipsync_audio.mp4
    original_video = result.get("original_video_path")
    lipsync_candidate = lipsync_audio or str(TASKS_DIR / f"{task_id}_lipsync_audio.mp4")
    source_video = original_video if (original_video and Path(original_video).exists()) else (
        lipsync_candidate if (Path(lipsync_candidate).exists()) else video_path
    )

    subtitle_style = SubtitleStyle(
        font_size=72,
        font_color="&HFFFFFF",
        outline_color="&H000000",
        outline_width=4,
        bold=True,
        position="bottom",
        margin_v=120
    )

    # 生成新ASS字幕
    subtitle_path = str(TASKS_DIR / f"{task_id}_subtitle_v2.ass")

    # 确定用于Whisper对齐的音频来源：
    # 优先用 tts_audio_path（独立TTS文件），但如果文件不存在或路径可疑则从lipsync提取
    loop = asyncio.get_event_loop()
    audio_for_whisper = None
    if tts_audio and Path(tts_audio).exists():
        # 检查tts_audio是否为共享路径（可能被覆盖），优先从lipsync提取
        if "tts_output.mp3" in tts_audio and lipsync_audio and Path(lipsync_audio).exists():
            # tts_output.mp3是共享路径，可能被覆盖，从lipsync提取
            audio_for_whisper = await loop.run_in_executor(
                None, extract_audio, lipsync_audio, str(TASKS_DIR / f"{task_id}_whisper_audio.wav")
            )
        else:
            audio_for_whisper = tts_audio
    elif lipsync_candidate and Path(lipsync_candidate).exists():
        # 旧任务没有tts_audio，从lipsync提取音频
        audio_for_whisper = await loop.run_in_executor(
            None, extract_audio, lipsync_candidate, str(TASKS_DIR / f"{task_id}_whisper_audio.wav")
        )

    if audio_for_whisper:
        await generate_ass_from_tts_audio(
            rewritten_text, audio_for_whisper, subtitle_path, style=subtitle_style
        )
    else:
        # 旧任务没有任何音频，退化为估算
        generate_ass_from_rewritten(
            rewritten_text, [],
            subtitle_path,
            audio_duration=audio_duration,
            style=subtitle_style
        )

    # 烧录字幕（source_video 已有音轨，不传audio_path避免重复）
    import uuid
    final_video_name = f"{task_id}_{uuid.uuid4().hex[:8]}_subtitled.mp4"
    final_path = await loop.run_in_executor(
        None, burn_subtitle, source_video, subtitle_path,
        str(TASKS_DIR / final_video_name), subtitle_style, None
    )

    return {
        "video_path": final_path,
        "subtitle_path": subtitle_path,
        "message": "字幕重新烧录完成"
    }


# ============== 启动 ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
