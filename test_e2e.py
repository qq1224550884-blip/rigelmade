#!/usr/bin/env python3
"""端到端测试：登录 + 生图（nano-banana-2）"""
import json
import time
import requests

BASE = "http://127.0.0.1:8792"

# 1. 登录
print("=== 登录 ===")
resp = requests.post(f"{BASE}/api/auth/login", json={
    "email": "test2@example.com",
    "password": "test1234567890"
})
print(f"状态: {resp.status_code}")
if resp.status_code != 200:
    print(resp.text)
    raise SystemExit(1)
data = resp.json()
token = data["token"]
print(f"✓ 登录成功 token={token[:20]}...")
print(f"用户积分: {data['user']['credits']}\n")

# 2. 检查模型价格存在（nano-banana-2）
print("=== 检查价格 ===")
resp = requests.get(f"{BASE}/v1/models", headers={"Authorization": f"Bearer {token}"})
print(f"模型列表: {resp.status_code}")

# 3. 生图
print("\n=== 生图 nano-banana-2 (imageSize=1K) ===")
start = time.time()
resp = requests.post(
    f"{BASE}/api/generate",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "request": {
            "provider": "banana",
            "model": "nano-banana-2",
            "prompt": "现代简约风格的室内客厅效果图，自然光，写实摄影",
            "imageSize": "1K",
            "count": 1
        },
        "idempotencyKey": "e2e-nano-" + str(int(time.time()))
    }
)
elapsed = time.time() - start
print(f"耗时: {elapsed:.1f}s")
print(f"状态: {resp.status_code}")
print(f"响应: {json.dumps(resp.json(), ensure_ascii=False, indent=2)[:1500]}")
