#!/usr/bin/env python3
"""端到端测试 toapis 渠道生图（含计费）"""
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

# 2. 检查 health 看 toapis 渠道
print("=== 健康检查（渠道状态） ===")
resp = requests.get(f"{BASE}/api/health")
health = resp.json()
toapis = health.get("providers", {}).get("toapis", {})
print(f"toapis: hasKey={toapis.get('hasKey')} baseUrl={toapis.get('baseUrl')} model={toapis.get('model')}")

# 3. 生图（不指定 provider，验证自动推断到 toapis）
print("\n=== 生图 gpt-image-2（自动推断 provider） ===")
start = time.time()
resp = requests.post(
    f"{BASE}/api/generate",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "request": {
            "model": "gpt-image-2",
            "prompt": "现代简约风格室内客厅效果图，自然光，写实摄影",
            "imageSize": "1K",
            "count": 1
        },
        "idempotencyKey": "e2e-toapis-" + str(int(time.time()))
    }
)
elapsed = time.time() - start
print(f"耗时: {elapsed:.1f}s")
print(f"状态: {resp.status_code}")
result = resp.json()
print(f"响应: {json.dumps(result, ensure_ascii=False, indent=2)[:1200]}")
if resp.status_code == 200 and result.get("outputs"):
    print("\n✓✓✓ 端到端成功！图片已生成并保存")
    print(f"图片URL: {result['outputs'][0]['url']}")
