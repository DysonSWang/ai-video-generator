#!/usr/bin/env python3
"""测试硅基流动声音克隆"""
import requests
import base64
import os
import json

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

    print("🎙️ 正在上传参考音频创建音色...")
    response = requests.post(
        "https://api.siliconflow.cn/v1/uploads/audio/voice",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=payload
    )

    if response.status_code == 200:
        result = response.json()
        print(f"✅ 音色创建成功!")
        print(f"   voice_uri: {result.get('uri')}")
        return result.get('uri')
    else:
        print(f"❌ 音色创建失败: {response.status_code}")
        print(f"   {response.text}")
        return None

def synthesize_with_voice(voice_uri):
    """使用克隆的音色合成语音"""
    payload = {
        "model": "IndexTeam/IndexTTS-2",
        "input": TEST_TEXT,
        "voice": voice_uri
    }

    print(f"\n🎵 正在使用克隆音色合成: {TEST_TEXT[:30]}...")
    response = requests.post(
        "https://api.siliconflow.cn/v1/audio/speech",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=payload
    )

    if response.status_code == 200:
        output_path = "/home/admin/Downloads/cloned_voice_test.mp3"
        with open(output_path, "wb") as f:
            f.write(response.content)
        size = os.path.getsize(output_path)
        print(f"✅ 语音合成成功!")
        print(f"   输出文件: {output_path}")
        print(f"   文件大小: {size/1024:.1f} KB")
        return output_path
    else:
        print(f"❌ 语音合成失败: {response.status_code}")
        print(f"   {response.text}")
        return None

def main():
    print("=" * 50)
    print("🔬 硅基流动声音克隆测试")
    print("=" * 50)
    print(f"\n参考音频: {REF_AUDIO}")
    print(f"音频大小: {os.path.getsize(REF_AUDIO)/1024:.1f} KB")

    # 1. 创建音色克隆
    voice_uri = create_voice_clone()
    if not voice_uri:
        return

    # 2. 使用克隆音色合成
    output = synthesize_with_voice(voice_uri)
    if output:
        print("\n" + "=" * 50)
        print("✅ 测试完成！")
        print(f"播放方式: ffplay {output}")
        print("=" * 50)

if __name__ == "__main__":
    main()
