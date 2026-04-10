#!/usr/bin/env python3
"""应用配置 - 从环境变量读取敏感信息"""

import os

# ============== API Keys ==============

# 阿里云百炼 (千问)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "sk-d4d0824db5e847de8ddbef4cda0b4e34")
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_MODEL = "qwen-turbo"

# 硅基流动 (TTS + 音色克隆)
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "sk-cnfczetwmgwynbwezbadzhvceilpivocpaltgwtodnukpwpd")
SILICONFLOW_URL = "https://api.siliconflow.cn/v1/audio/speech"
VOICE_CLONE_URL = "https://api.siliconflow.cn/v1/uploads/audio/voice"

# 可灵Kling (口型同步)
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "AfhKRaCB49agkfBaL3JKTaKeKrrydpNA")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "hGMdHJdDNMnae9DKypKGFDnkeQamJbBf")
KLING_API_BASE = "https://api-beijing.klingai.com"

# 阿里云OSS (文件存储)
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY", "LTAI5t99BtSw6NCuU8PVxhvy")
OSS_SECRET_KEY = os.getenv("OSS_SECRET_KEY", "TkmMeBbOzRRQXzc0Uy6HDctxkP9wBJ")
OSS_BUCKET = "annsight-images"
OSS_ENDPOINT = "oss-cn-shenzhen.aliyuncs.com"

# ============== 其他配置 ==============

# Whisper模型
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANGUAGE = "zh"

# CDP端口 (视频下载)
CDP_PORT = int(os.getenv("CDP_PORT", "9222"))

# ============== MuseTalk (本地GPU服务器) ==============
# GPU服务器SSH配置
MUSETALK_HOST = os.getenv("MUSETALK_HOST", "117.50.226.177")
MUSETALK_PORT = int(os.getenv("MUSETALK_PORT", "23"))
MUSETALK_USER = os.getenv("MUSETALK_USER", "root")
MUSETALK_PASSWORD = os.getenv("MUSETALK_PASSWORD", "avh1Q96G750XR32Y")
MUSETALK_URL = os.getenv("MUSETALK_URL", "http://117.50.226.177:7860")

# ============== InfiniteTalk (ComfyUI GPU服务器) ==============
# InfiniteTalk 使用 ComfyUI Web界面，比 MuseTalk 更稳定
INFINITETALK_HOST = os.getenv("INFINITETALK_HOST", "117.50.250.191")
INFINITETALK_PORT = int(os.getenv("INFINITETALK_PORT", "23"))
INFINITETALK_USER = os.getenv("INFINITETALK_USER", "root")
INFINITETALK_PASSWORD = os.getenv("INFINITETALK_PASSWORD", "07u9x45sJF8i3m1T")
INFINITETALK_URL = os.getenv("INFINITETALK_URL", "http://117.50.250.191:7860")
INFINITETALK_OUTPUT_PATH = "/root/ComfyUI/output"
