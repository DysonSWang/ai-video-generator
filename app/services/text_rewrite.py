#!/usr/bin/env python3
"""文案改写服务 - 基于阿里云百炼千问"""

import asyncio
import json
import requests
from dataclasses import dataclass
from typing import Optional
from app.config import QWEN_API_KEY, QWEN_API_URL, QWEN_MODEL

@dataclass
class RewriteOptions:
    style: str = "口语化"           # 改写风格
    keep_keywords: bool = True      # 保留关键词
    max_length: Optional[int] = None  # 最大长度

MAX_RETRIES = 3
RETRY_DELAY = 1.0

async def rewrite(
    text: str,
    style: str = "口语化",
    options: Optional[RewriteOptions] = None
) -> str:
    """千问改写文案为原创（带重试）"""
    if options is None:
        options = RewriteOptions(style=style)

    system_prompt = f"""你是一个抖音网红博主。你的任务是将给定的文案改写成自己的风格。

改写要求（以抖音网红博主的口吻和视角）：
1. 保持原文的核心意思、关键数据和主要观点完全不变
2. 用自己的话说出来，表达更接地气、更自然
3. {style}
4. {"保留原文的关键词" if options.keep_keywords else "可以适当调整关键词"}
5. 长度适中，不要太长也不要太短
6. 不要添加原文没有的内容
7. **必须全部使用简体中文（简体汉字），不要使用繁体字、异体字**
8. 改写后要像你自己在镜头前说的话，不要书面语

请直接输出改写后的文案，不要解释。"""

    user_prompt = f"请将以下文案改写：\n\n{text}"

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    loop = asyncio.get_event_loop()

    for attempt in range(MAX_RETRIES):
        try:
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(QWEN_API_URL, headers=headers, json=payload, timeout=60)
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()

            if response.status_code >= 500:
                # 服务器错误，重试
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise RuntimeError(f"API服务器错误: {response.status_code}")

            raise RuntimeError(f"API调用失败: {response.status_code} - {response.text}")

        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            raise RuntimeError(f"网络错误: {e}")


async def polish(text: str) -> str:
    """润色转录稿：修正识别错误、补全缺失、让语言自然流畅

    Args:
        text: 原始转录文本（可能含识别错误、断句不完整、语气词等问题）

    Returns:
        润色后的文本
    """
    system_prompt = """你是一个专业的语音转录润色专家。

转录稿往往存在以下问题：识别错误、断句混乱、语气词冗余、成分缺失。
你的任务是把转录稿润色成通顺、准确、完整的书面文案。

润色要求：
1. 修正明显的语音识别错误（同音字、谐音词等）
2. 补全省略的主语、宾语等句子成分
3. 删除无意义的语气词（呃、啊、嗯、这个这个等）
4. 调整断句，让段落结构清晰
5. 保持原文的核心内容、观点、数据完全不变
6. **必须全部使用简体中文（简体汉字），不要使用繁体字、异体字**

请直接输出润色后的文案，不要解释，不要标注修改内容。"""

    user_prompt = f"请润色以下转录稿：\n\n{text}"

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4000
    }

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: requests.post(QWEN_API_URL, headers=headers, json=payload, timeout=60)
    )

    if response.status_code != 200:
        raise RuntimeError(f"API调用失败: {response.status_code} - {response.text}")

    result = response.json()
    return result['choices'][0]['message']['content'].strip()


async def batch_rewrite(
    texts: list[str],
    style: str = "口语化"
) -> list[str]:
    """批量改写文案"""
    results = []
    for text in texts:
        rewritten = await rewrite(text, style)
        results.append(rewritten)
        await asyncio.sleep(0.5)  # 避免API限流
    return results


if __name__ == "__main__":
    import sys

    # 测试
    test_text = "今天给大家分享一个装修的技巧，第一点就是要做好防水，第二点是选择环保材料，第三点是找专业的施工团队。"

    if len(sys.argv) > 1:
        test_text = sys.argv[1]

    print(f">>> 原文:\n{test_text}\n")

    result = asyncio.run(rewrite(test_text))

    print(f">>> 改写后:\n{result}")
