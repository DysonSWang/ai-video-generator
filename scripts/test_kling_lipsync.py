#!/usr/bin/env python3
"""可灵 Kling Lip Sync API 测试"""
import requests
import time
import jwt
import json

# API配置
ACCESS_KEY = "AfhKRaCB49agkfBaL3JKTaKeKrrydpNA"
SECRET_KEY = "hGMdHJdDNMnae9DKypKGFDnkeQamJbBf"
API_BASE = "https://api-beijing.klingai.com"


def encode_jwt_token(ak, sk):
    """生成JWT token"""
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,  # 30分钟有效
        "nbf": int(time.time()) - 5
    }
    return jwt.encode(payload, sk, headers=headers)


def call_api(method, path, data=None):
    """调用可灵API"""
    url = f"{API_BASE}{path}"
    token = encode_jwt_token(ACCESS_KEY, SECRET_KEY)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    print(f"\n{method} {url}")

    if method == "GET":
        resp = requests.get(url, headers=headers, params=data)
    else:
        resp = requests.post(url, headers=headers, json=data)

    print(f"Status: {resp.status_code}")
    try:
        result = resp.json()
        print(f"Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    except:
        print(f"Raw: {resp.text}")
        return None


def step1_identify_face(video_url):
    """步骤1: 人脸识别"""
    print("\n" + "="*60)
    print("步骤1: 人脸识别")
    print("="*60)

    data = {
        "video_url": video_url,
        "video_id": ""
    }

    result = call_api("POST", "/v1/videos/identify-face", data)

    if result and result.get("code") == 0:
        session_id = result["data"]["session_id"]
        face_data = result["data"]["face_data"]
        print(f"\n✅ 人脸识别成功!")
        print(f"Session ID: {session_id}")
        print(f"检测到 {len(face_data)} 个人脸:")
        for face in face_data:
            print(f"  - face_id: {face['face_id']}")
            print(f"    时间: {face['start_time']}ms ~ {face['end_time']}ms")
        return session_id, face_data
    else:
        print(f"❌ 人脸识别失败: {result}")
        return None, None


def step2_create_lip_sync(session_id, face_id, audio_url=None):
    """步骤2: 创建对口型任务"""
    print("\n" + "="*60)
    print("步骤2: 创建对口型任务")
    print("="*60)

    data = {
        "session_id": session_id,
        "face_choose": [
            {
                "face_id": face_id,
                "sound_file": audio_url,
                "sound_insert_time": 1000,
                "sound_start_time": 0,
                "sound_end_time": 3000,
                "sound_volume": 1.0,
                "original_audio_volume": 1.0
            }
        ]
    }

    result = call_api("POST", "/v1/videos/advanced-lip-sync", data)

    if result and result.get("code") == 0:
        task_id = result["data"]["task_id"]
        print(f"\n✅ 任务创建成功!")
        print(f"Task ID: {task_id}")
        print(f"状态: {result['data']['task_status']}")
        return task_id
    else:
        print(f"❌ 任务创建失败: {result}")
        return None


def step3_query_task(task_id):
    """步骤3: 查询任务状态"""
    print("\n" + "="*60)
    print(f"查询任务 {task_id}")
    print("="*60)

    result = call_api("GET", f"/v1/videos/advanced-lip-sync/{task_id}")

    if result and result.get("code") == 0:
        data = result["data"]
        print(f"状态: {data['task_status']}")
        if data['task_status'] == 'succeed':
            print(f"✅ 成功! 视频:")
            for video in data['task_result']['videos']:
                print(f"  URL: {video['url']}")
                print(f"  时长: {video['duration']}s")
        elif data['task_status'] == 'failed':
            print(f"❌ 失败: {data.get('task_status_msg', '未知')}")
        return data['task_status']
    return None


def main():
    print("="*60)
    print("可灵 Kling Lip Sync API 测试")
    print("="*60)

    # 测试视频和音频URL (阿里云OSS)
    TEST_VIDEO_URL = "https://annsight-images.oss-cn-shenzhen.aliyuncs.com/test/sun_short.mp4"
    TEST_AUDIO_URL = "https://annsight-images.oss-cn-shenzhen.aliyuncs.com/test/tts_6s_test.mp3"

    # 步骤1: 人脸识别
    session_id, face_data = step1_identify_face(TEST_VIDEO_URL)
    if not session_id or not face_data:
        return

    face_id = face_data[0]['face_id']

    # 步骤2: 创建任务
    task_id = step2_create_lip_sync(session_id, face_id, TEST_AUDIO_URL)
    if not task_id:
        return

    # 步骤3: 轮询
    print("\n等待任务完成...")
    for i in range(30):
        time.sleep(5)
        status = step3_query_task(task_id)
        if status in ['succeed', 'failed']:
            break
        print(f"等待中... {i+1}/30")


if __name__ == "__main__":
    main()
