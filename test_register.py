#!/usr/bin/env python3
"""直接测试注册和生图接口"""
import json
import time
import requests

BASE = "http://127.0.0.1:8792"

# 1. 注册
print("=== 注册测试账户 ===")
resp = requests.post(f"{BASE}/api/auth/register", json={
    "email": "test2@example.com",
    "password": "test1234567890",
    "displayName": "测试2"
})
print(f"状态码: {resp.status_code}")
print(f"响应: {resp.text}\n")

if resp.status_code in (200, 409):
    if resp.status_code == 409:
        print("账户已存在")
    print("尝试登录...")
    resp = requests.post(f"{BASE}/api/auth/login", json={
        "email": "test2@example.com",
        "password": "test1234567890"
    })
    print(f"登录状态码: {resp.status_code}")
    print(f"登录响应: {resp.text}\n")

if resp.status_code == 200:
    data = resp.json()
    if "token" in data:
        token = data["token"]
        print(f"✓ Token: {token[:20]}...\n")

        # 2. 调用生图
        print("=== 测试 nano-banana-2 生图 ===")
        gen_resp = requests.post(
            f"{BASE}/api/generate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "request": {
                    "model": "nano-banana-2",
                    "prompt": "现代简约办公空间室内效果图",
                    "imageSize": "1K",
                    "count": 1
                },
                "idempotencyKey": "test-nano-" + str(int(time.time()))
            }
        )
        print(f"生成状态码: {gen_resp.status_code}")
        print(f"生成响应: {json.dumps(gen_resp.json(), indent=2, ensure_ascii=False)}")
