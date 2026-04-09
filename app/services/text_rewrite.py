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

    system_prompt = f"""你是一个专业的文案改写专家。你的任务是将给定的文案改写成原创内容。

改写要求：
1. 保持原文的核心意思不变
2. 用你自己的话重新表达
3. {style}
4. {"保留原文的关键词" if options.keep_keywords else "可以适当调整关键词"}
5. 长度适中，不要太长也不要太短
6. 不要添加原文没有的内容
7. **必须全部使用简体中文（简体汉字），不要使用繁体字、异体字**

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
