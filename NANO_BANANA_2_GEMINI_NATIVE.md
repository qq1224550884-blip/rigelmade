# nano-banana-2 Gemini 原生协议接入完成

## 修改内容

### 1. 新增 `call_gemini_native()` 函数
位置：`render_core.py` 第 512-589 行

实现 Gemini 原生 `generateContent` 协议：

```python
POST {base_url}/v1beta/models/nano-banana-2:generateContent
```

**请求结构：**
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {"text": "提示词"},
        {"inlineData": {"mimeType": "image/png", "data": "base64..."}}
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"]
  }
}
```

**响应解析：**
```python
candidates[].content.parts[].inlineData.data  # Base64 图片数据
candidates[].content.parts[].inlineData.mimeType  # MIME 类型
```

**鉴权自动降级：**
1. 优先使用 `x-goog-api-key: YOUR_KEY`（Gemini 官方标准）
2. 若返回 401，自动降级为 `Authorization: Bearer YOUR_KEY`（中继适配）

### 2. 修改调用路由
位置：`render_core.py` 第 1066 行

在 `/api/generate` 路由中新增模型判断：

```python
if req.model == "nano-banana-2":
    api_response = call_gemini_native(req, effective_prompt, saved_inputs, api_key, base_url)
elif provider == "banana":
    api_response = call_banana_draw(req, effective_prompt, saved_inputs, api_key, base_url)
elif provider == "banana_fast":
    api_response = call_fast_banana_chat(req, effective_prompt, saved_inputs, api_key, base_url)
else:
    api_response = call_grsai(req, effective_prompt, saved_inputs, api_key, base_url)
```

**优先级：模型名精确匹配 > provider 渠道判断**

## 配置方法

### 环境变量
在 `deploy/.env` 或系统环境变量中配置：

```bash
NANO_BANANA_API_KEY=sk-your-real-key-here
NANO_BANANA_BASE_URL=https://pdhlzy.com
```

支持逗号分隔的 Key 池（自动轮换 + 限流冷却）：

```bash
NANO_BANANA_API_KEY=key1,key2,key3
```

### 前端调用
前端请求时指定模型：

```typescript
const response = await fetch('/api/generate', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    provider: 'banana',
    model: 'nano-banana-2',
    prompt: '生成一张现代客厅效果图',
    aspectRatio: '16:9',
    imageSize: '1K',
  }),
});
```

## 兼容性

- `nano-banana-2` 强制走 Gemini 原生协议
- 其他 `banana` 模型保持原有 `/v1/draw/nano-banana` 接口
- `banana_fast` 保持 OpenAI Chat Completions 多模态接口

## 测试

### 快速测试脚本
`test_nano_quick.py` - 硬编码参数直接测试接口可达性

### 完整测试脚本
`test_gemini_native.py` - 从环境变量读取配置完整测试

运行测试：

```bash
export NANO_BANANA_API_KEY="your-real-key"
export NANO_BANANA_BASE_URL="https://pdhlzy.com"
python test_gemini_native.py
```

成功输出示例：

```
✓ 调用成功
模型：nano-banana-2
状态：succeeded
返回图片数量：1
图片 1：Base64 data URL（长度 123456 字符）
```

## 注意事项

1. **API Key 验证**：截图示例 Key 不可用，需从 PDH 后台获取真实有效的 Key
2. **超时设置**：默认 `DEFAULT_BANANA_WAIT_SECONDS`（1200 秒），生成图片时间较长
3. **图片返回**：图片以 Base64 data URL 形式返回，自动保存到 `data/runs/{runId}/outputs/`
4. **错误处理**：401 自动重试 Bearer 鉴权，其他错误触发 Key 池冷却机制

## 状态

✅ 代码修改完成  
✅ 语法检查通过  
⚠️ 需要真实 API Key 才能完成端到端测试

修改时间：2026-08-15
