# AI 效果图商业版（infinite-canvas 二次开发）

基于 [basketikun/infinite-canvas](https://github.com/basketikun/infinite-canvas) 二次开发的商业部署版：在无限画布、AI 生图/生视频工作台之上，增加了**账号体系、积分计费、套餐与微信支付**，并把 AI 渠道调用从前端直连改为**服务端代理**（API Key 只存在服务器，不暴露给浏览器）。

> **许可证说明**：本项目继承原上游的 **AGPL-3.0** 协议，修改与使用须遵守 AGPL v3.0 全部条款，包括"网络服务须向用户提供对应源代码"。前端授权文本见 [`web/LICENSE`](web/LICENSE)，原作者版权信息保留。二次开发与原作无任何关联、不代表原作者立场。

## 技术栈

- 前端：React 19 + Vite 7 + Ant Design（原 infinite-canvas）
- 后端：Python + FastAPI，SQLite（账号 / 积分 / 订单）
- 生图渠道：OpenAI 兼容接口（gpt-image-2 / nano-banana 系列），Key 只读服务端环境变量

## 功能

- 无限画布：多画布项目、节点编排、参考图编辑、提示词库、素材沉淀
- AI 创作：文生图 / 图生图 / 参考图编辑 / 文本问答 / 音频与视频生成
- 商业底座：邮箱注册、密码哈希、会话令牌、管理员角色
- 计费：可审计积分流水；生成前预扣、失败自动退款、重复请求不重复扣费；**按生成张数倍增扣费**
- 支付：微信支付 API V3 Native 下单 + 回调验签/解密；未配置商户资料时拒绝创建订单，绝不模拟付款成功

## 快速开始

### 本地开发

```bash
# 后端（端口 8792）
pip install -r requirements.txt
python manage.py create-admin        # 首次初始化管理员
python seed_pricing.py               # 写入套餐与积分价格
python commercial_app.py

# 前端（端口 3002）
cd web/web
bun install
bun run dev
```

日常启动 Windows 版：双击 `start-commercial-workbench.ps1`。

### Docker 部署

见 [`deploy/README-deploy.md`](deploy/README-deploy.md)。

## 上线前必配（只在服务器环境变量/证书目录配置）

`COMMERCIAL_ENV=production`、`COMMERCIAL_AUTH_SECRET`、三个渠道 API Key、`WECHATPAY_MCHID` / `WECHATPAY_APPID` / `WECHATPAY_SERIAL_NO` / `WECHATPAY_PRIVATE_KEY_PATH` / `WECHATPAY_PLATFORM_CERT_PATH` / `WECHATPAY_API_V3_KEY` / `WECHATPAY_NOTIFY_URL`。

环境变量模板见 [`deploy/.env.example`](deploy/.env.example)。**商户私钥、平台证书和 API V3 Key 不得放进仓库或聊天记录。**

## 安全提示

- API Key 只存在服务端环境变量，前端永远不接触。
- 生产环境务必使用 HTTPS（部署包内置 nginx SSL 配置）。
- 数据目录 `data/`、日志 `logs/`、部署密钥 `deploy/.env` 与 `deploy/certs/` 已被 `.gitignore` 排除，不得提交。

## 授权

本项目基于 [basketikun/infinite-canvas](https://github.com/basketikun/infinite-canvas)（AGPL-3.0）二次开发，保持原上游许可与版权声明，见 [`web/LICENSE`](web/LICENSE)。任何使用须遵守 AGPL v3.0。
