#!/usr/bin/env python3
"""测试 nano-banana-2 Gemini 原生接口"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from render_core import GenerateRequest, call_gemini_native

api_key = os.getenv("NANO_BANANA_API_KEY", "")
base_url = os.getenv("NANO_BANANA_BASE_URL", "https://pdhlzy.com")

if not api_key:
    print("错误：未设置 NANO_BANANA_API_KEY 环境变量")
    sys.exit(1)

req = GenerateRequest(
    provider="banana",
    prompt="生成一张现代简约风格的室内客厅效果图，自然光线",
    model="nano-banana-2",
    aspectRatio="16:9",
    imageSize="1K",
)

print(f"请求地址：{base_url}/v1beta/models/nano-banana-2:generateContent")
print(f"提示词：{req.prompt}")
print("开始调用...")

try:
    result = call_gemini_native(req, req.prompt, [], api_key, base_url)
    print("\n✓ 调用成功")
    print(f"模型：{result.get('model')}")
    print(f"状态：{result.get('status')}")
    print(f"返回图片数量：{len(result.get('data', []))}")

    for index, item in enumerate(result.get("data", []), start=1):
        url = item.get("url", "")
        if url.startswith("data:"):
            print(f"图片 {index}：Base64 data URL（长度 {len(url)} 字符）")
        else:
            print(f"图片 {index}：{url}")
except Exception as exc:
    print(f"\n✗ 调用失败：{exc}")
    sys.exit(1)
