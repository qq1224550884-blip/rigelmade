#!/usr/bin/env python3
"""快速测试 nano-banana-2 接口（Key 从环境变量读取，勿硬编码）"""
import base64
import json
import os
import sys
import requests

# 从你的截图确认的信息
BASE_URL = os.getenv("NANO_BANANA_BASE_URL", "https://pdhlzy.com")
MODEL = "nano-banana-2"
API_KEY = os.getenv("NANO_BANANA_API_KEY", "")
if not API_KEY:
    print("错误：未设置 NANO_BANANA_API_KEY 环境变量")
    sys.exit(1)

url = f"{BASE_URL}/v1beta/models/{MODEL}:generateContent"

payload = {
    "contents": [
        {
            "role": "user",
            "parts": [
                {
                    "text": "生成一张现代简约客厅效果图，自然光线"
                }
            ],
        }
    ],
    "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"]
    },
}

print(f"测试地址：{url}")
print(f"第一次尝试：x-goog-api-key")
print(f"Key 前缀：{API_KEY[:15]}...")
print("开始调用...\n")

headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": API_KEY,
}


try:
    response = requests.post(url, headers=headers, json=payload, timeout=300)
    print(f"HTTP 状态码：{response.status_code}")

    if response.status_code >= 400:
        print(f"❌ 请求失败")
        print(f"响应内容：{response.text[:1000]}")
    else:
        data = response.json()
        print(f"✓ 请求成功\n")
        print(f"完整响应（前 2000 字符）：")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

        # 尝试解析图片
        urls = []
        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                # Check inlineData (Base64)
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data:
                    image_base64 = inline_data.get("data")
                    mime_type = inline_data.get("mimeType") or inline_data.get("mime_type", "image/png")
                    if image_base64:
                        urls.append(f"data:{mime_type};base64,{image_base64[:50]}...")

                # Check fileData (URL)
                file_data = part.get("fileData") or part.get("file_data")
                if file_data:
                    file_uri = file_data.get("fileUri") or file_data.get("file_uri")
                    if file_uri:
                        urls.append(file_uri)

        if urls:
            print(f"\n找到 {len(urls)} 张图片")
            for i, url in enumerate(urls, 1):
                print(f"  图片 {i}：{url}")
        else:
            print("\n⚠️ 未找到图片数据")

except requests.exceptions.Timeout:
    print("❌ 请求超时（300秒）")
except Exception as exc:
    print(f"❌ 异常：{exc}")
