# 语音克隆 - 经验总结

## 方案

**SiliconFlow IndexTTS-2** - 中文语音克隆

## 核心流程

```
用户参考音频 → 上传创建音色(voice_uri) → 输入文本 → 合成克隆语音
```

## API 详情

### 1. 创建音色克隆

```python
POST https://api.siliconflow.cn/v1/uploads/audio/voice

Headers:
  Authorization: Bearer {API_KEY}

Body:
{
  "model": "IndexTeam/IndexTTS-2",
  "custom_name": "my_voice_clone",
  "text": "参考文本",
  "audio": "data:audio/mpeg;base64,{base64音频数据}"
}
```

### 2. 使用克隆音色合成

```python
POST https://api.siliconflow.cn/v1/audio/speech

Headers:
  Authorization: Bearer {API_KEY}

Body:
{
  "model": "IndexTeam/IndexTTS-2",
  "input": "要合成的文本",
  "voice": voice_uri  # 从步骤1获取
}
```

## 配置信息

| 项目 | 值 |
|------|------|
| API服务商 | SiliconFlow (硅基流动) |
| 模型 | IndexTeam/IndexTTS-2 |
| API Key | sk-cnfczetwmgwynbwezbadzhvceilpivocpaltgwtodnukpwpd |
| 参考音频 | user_voice.wav (311KB) |

## 测试结果

| 文件 | 大小 | 状态 |
|------|------|------|
| cloned_voice_test.mp3 | 120KB | ✅ 成功 |
| final_with_cloned_voice.mp4 | 206KB | ✅ 成功 (克隆音色+Wav2Lip) |

## 完整测试脚本

```python
#!/usr/bin/env python3
"""测试硅基流动声音克隆"""
import requests
import base64
import os

API_KEY = "sk-cnfczetwmgwynbwezbadzhvceilpivocpaltgwtodnukpwpd"
REF_AUDIO = "/home/admin/Downloads/user_voice.wav"
TEST_TEXT = "你好，这是用你自己的声音克隆出来的测试语音。效果还不错吧？"

def create_voice_clone():
    """上传参考音频创建音色"""
    with open(REF_AUDIO, "rb") as f:
        audio_data = base64.b64encode(f.read()).decode()
        audio_url = f"data:audio/mpeg;base64,{audio_data}"

    payload = {
        "model": "IndexTeam/IndexTTS-2",
        "custom_name": "my_voice_clone",
        "text": "这是参考语音，用于克隆音色。",
        "audio": audio_url
    }

    response = requests.post(
        "https://api.siliconflow.cn/v1/uploads/audio/voice",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=payload
    )

    if response.status_code == 200:
        return response.json().get('uri')
    return None

def synthesize_with_voice(voice_uri):
    """使用克隆的音色合成语音"""
    payload = {
        "model": "IndexTeam/IndexTTS-2",
        "input": TEST_TEXT,
        "voice": voice_uri
    }

    response = requests.post(
        "https://api.siliconflow.cn/v1/audio/speech",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=payload
    )

    if response.status_code == 200:
        with open("cloned_voice_test.mp3", "wb") as f:
            f.write(response.content)
        return True
    return False
```

## 注意事项

1. **参考音频质量很重要** - 清晰、无背景音效果更好
2. **音色URI有时效** - 建议每次合成前重新创建
3. **base64编码** - 音频需要完整base64编码
4. **API额度** - 注意SiliconFlowAPI用量限制

## 后续应用

克隆音色 + 口型同步 = 完整数字人视频

Pipeline:
```
文本 → IndexTTS克隆音色合成 → Wav2Lip/MuseTalk口型同步 → 最终视频
```
