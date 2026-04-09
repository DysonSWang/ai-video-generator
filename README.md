# AI口播视频生成系统

**日期**: 2026-04-08
**状态**: 系统架构设计完成，核心服务已封装

---

## 产品介绍

复制类似D-ID的AI口播视频生成工具：

**核心功能**：用户上传自己的形象视频（不说话）+ 声音示例，系统自动生成"用你的形象、你的声音、说改写的原创内容"的视频。

### 目标用户
- 个人创业者
- 中小实体商家
- 需要批量生成口播视频的用户

---

## 完整流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户输入层                                  │
├─────────────────────────────────────────────────────────────────────┤
│  1. 同行视频链接 (抖音/快手/小红书)                                    │
│     → 下载视频 → Whisper提取文案 → 千问改写原创                         │
│                                                                      │
│  2. 用户自己的视频 (不说话，只露脸)  ← 数字人素材                      │
│                                                                      │
│  3. 用户自己的声音 (10-20秒参考音频)                                   │
│     → 音色克隆                                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                           AI处理层                                   │
├─────────────────────────────────────────────────────────────────────┤
│  改写文案 + 克隆声音 → TTS配音                                        │
│                                    ↓                                 │
│                    配音 + 用户视频 → 口型同步                          │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                           后期处理层                                  │
├─────────────────────────────────────────────────────────────────────┤
│  • 字幕生成 (Whisper时间戳)                                          │
│  • 画中画 (可选)                                                     │
│  • 配乐 (可选)                                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                           输出层                                     │
├─────────────────────────────────────────────────────────────────────┤
│  • 预览/下载 (MP4)                                                   │
│  • 分享链接                                                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
ai-video-generator/
├── app/                          # Web应用 (FastAPI)
│   ├── main.py                   # 主入口
│   ├── services/                 # 核心服务
│   │   ├── video_downloader.py  # 视频下载 (Playwright CDP)
│   │   ├── speech_to_text.py    # Whisper语音识别
│   │   ├── text_rewrite.py      # 千问文案改写
│   │   ├── voice_clone.py       # 音色克隆 + TTS
│   │   ├── lip_sync.py          # 口型同步 (Kling API)
│   │   ├── subtitle.py          # 字幕生成/烧录
│   │   ├── pip.py               # 画中画
│   │   └── music.py             # 配乐混合
│   └── routes/                  # API路由
│
├── scripts/                     # 测试脚本
│   ├── test_voice_clone.py      # 音色克隆测试 ✓
│   ├── test_kling_lipsync.py    # Kling API测试 ✓
│   └── run_pipeline.py          # 完整Pipeline测试
│
├── assets/                      # 素材目录
│   ├── videos/                  # 用户上传视频
│   ├── audios/                  # 用户上传音频
│   ├── outputs/                 # 输出结果
│   └── music/                   # 配乐文件
│
├── models/                      # 本地模型
│   └── whisper/                 # Whisper模型
│
└── docs/                        # 技术文档
```

---

## 核心服务

| 服务 | 技术方案 | 状态 |
|------|---------|------|
| 视频下载 | Playwright CDP (复用dyd项目) | ✅ 已封装 |
| 语音识别 | Whisper (本地) | ✅ 已封装 |
| 文案改写 | 阿里云百炼 qwen-plus | ✅ 已封装 |
| 音色克隆 | 硅基流动 IndexTTS-2 | ✅ 已封装 |
| 口型同步 | 可灵 Kling Lip Sync API | ✅ 已封装 |
| 字幕生成 | Whisper时间戳 + FFmpeg | ✅ 已封装 |
| 画中画 | FFmpeg overlay | ✅ 已封装 |
| 配乐 | FFmpeg amix | ✅ 已封装 |

---

## API接口

| 接口 | 方法 | 功能 |
|------|------|------|
| `POST /api/upload/video` | 上传 | 用户视频 |
| `POST /api/upload/audio` | 上传 | 用户声音 |
| `POST /api/extract` | 提取 | 同行视频文案 |
| `POST /api/pipeline/run` | 执行 | 启动Pipeline |
| `GET /api/task/{id}` | 查询 | 任务状态 |
| `GET /api/result/{id}` | 下载 | 最终视频 |

### 启动服务

```bash
cd /home/admin/ai-video-generator
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web框架 | FastAPI | 现代、高性能、自动API文档 |
| 数据库 | SQLite | 轻量、无需独立服务 |
| 画中画 | 需要 | 参考视频中有此功能 |

---

## 外部依赖

| 服务 | Key | 成本 |
|------|-----|------|
| 阿里云百炼 | `sk-d4d0824db5e847de8ddbef4cda0b4e34` | ¥0.02/千tokens |
| 硅基流动 | `sk-cnfczetwmgwynbwezbadzhvceilpivocpaltgwtodnukpwpd` | ¥0.3/千次 |
| 可灵Kling | `AfhKRaCB49agkfBaL3JKTaKeKrrydpNA` | ¥0.5-1/条 |
| Whisper | 本地 | ¥0 |

---

## Pipeline测试

```bash
# 完整Pipeline测试
python3 scripts/run_pipeline.py \
    --video-link "https://v.douyin.com/xxxxx" \
    --user-video /path/to/user.mp4 \
    --user-audio /path/to/user_voice.wav \
    --output ./results

# 带字幕+配乐
python3 scripts/run_pipeline.py \
    --video-link "https://v.douyin.com/xxxxx" \
    --user-video /path/to/user.mp4 \
    --user-audio /path/to/user_voice.wav \
    --music /path/to/music.mp3
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn whisper requests PyJWT oss2 playwright
playwright install chromium
```

### 2. 启动Chrome远程调试 (用于下载视频)

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug
```

### 3. 启动API服务

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. 调用API

```bash
# 上传用户视频
curl -X POST -F "file=@user.mp4" http://localhost:8000/api/upload/video

# 上传用户声音
curl -X POST -F "file=@voice.wav" http://localhost:8000/api/upload/audio

# 提取同行视频文案
curl -X POST -d '{"url":"https://v.douyin.com/xxx"}' http://localhost:8000/api/extract

# 执行Pipeline
curl -X POST -d '{
  "video_link": "https://v.douyin.com/xxx",
  "user_video_id": "xxx",
  "user_audio_id": "xxx"
}' http://localhost:8000/api/pipeline/run
```

---

## 组件验证状态

| 组件 | 状态 | 验证日期 |
|------|------|---------|
| Whisper | ✅ | 2026-04-08 |
| 千问改写 | ✅ | 2026-04-08 |
| 硅基流动TTS | ✅ | 2026-04-08 |
| 语音克隆 | ✅ | 2026-04-08 |
| Kling口型同步 | ✅ | 2026-04-08 |
| 字幕烧录 | ✅ | 2026-04-08 |
| 画中画 | ✅ | 2026-04-08 |
| 配乐 | ✅ | 2026-04-08 |
| Pipeline集成 | 🔄 | 待测试 |

---

## 下一步

1. [ ] 安装依赖并测试Pipeline
2. [ ] 配置Chrome远程调试
3. [ ] 测试完整流程
4. [ ] 开发Web界面
5. [ ] 添加用户管理

