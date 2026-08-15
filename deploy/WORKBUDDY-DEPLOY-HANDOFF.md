# Workbuddy 部署交接（Codex 主笔，2026-08-14）

> 目标：把「AI 效果图工作台商业版」部署到腾讯云轻量服务器，并交还维护通道。
> 服务器：106.52.254.164（广州），root 登录；本机无密钥，需 Workbuddy 建立访问并回授 SSH 方式。

## 一、交付物与角色

- 部署对象：H:\desktop-workspace\ai-render-commercial（商业版，FastAPI 后端 + Vite 前端 + nginx）
- 部署文档：deploy/README-deploy.md（含全部命令）
- 我的角色：完成本地代码/配置核对，编写本交接；部署执行与服务器操作由 Workbuddy 负责
- 上线后：把 SSH 访问（root 密码或 authorized_keys）回授给我，由我长期维护

## 二、服务器初始化（Workbuddy 执行）

    ssh root@106.52.254.164
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    docker --version

防火墙（腾讯云控制台 → 轻量服务器 → 防火墙）：放行 80 / 443 / 22。

## 三、上传代码

在本地（H:\desktop-workspace\ai-render-commercial）执行：

    ssh root@106.52.254.164 "mkdir -p /opt/ai-render"
    tar --exclude='*/node_modules' --exclude='*/dist' --exclude='*/__pycache__' --exclude='*/.git' --exclude='deploy/data' --exclude='deploy/certs' --exclude='deploy/.env' -czf - commercial_app.py render_core.py manage.py seed_pricing.py requirements.txt requirements-render-core.txt deploy web | ssh root@106.52.254.164 "tar -xzf - -C /opt/ai-render"

注意：web/web 下的 node_modules 不传，服务器构建时 npm install 重新生成。

## 四、配置环境变量

    cd /opt/ai-render/deploy
    cp .env.example .env
    vi .env

需要填写的键：

- GRSAI_API_KEY / NANO_BANANA_API_KEY / FAST_BANANA_API_KEY：三个生图渠道密钥（本地 pdhlzy 密钥可复用，也支持逗号分隔多密钥自动轮换）
- GRSAI_BASE_URL / NANO_BANANA_BASE_URL / FAST_BANANA_BASE_URL：渠道地址（如 https://pdhlzy.com）
- COMMERCIAL_AUTH_SECRET：至少 32 位随机串（openssl rand -hex 32）
- SITE_ORIGIN：正式域名（当前模板 rigelmade.com，备案通过后替换）
- 微信支付七项：商户号审核通过后填；未填则保持 COMMERCIAL_PAYMENT_ENABLED=false，系统自动进入免费体验模式（新用户送 500 积分）

改完：chmod 600 .env

## 五、构建启动

    cd /opt/ai-render/deploy
    docker compose up -d --build

验证：

    docker compose ps
    curl http://127.0.0.1/api/health

## 六、初始化数据

    docker compose exec backend python seed_pricing.py
    docker compose exec backend python manage.py create_admin

## 七、域名 + HTTPS（备案后）

1. 腾讯云 DNS 加 A 记录指向 106.52.254.164
2. 申请免费 SSL 证书，Nginx 版改名为 fullchain.crt / privkey.key 上传到 /opt/ai-render/deploy/certs/
3. cp nginx-ssl.conf nginx.conf，替换域名，docker compose up -d --build frontend
4. .env 里改 SITE_ORIGIN 与 WECHATPAY_NOTIFY_URL，docker compose up -d

## 八、关键事实（已核对，2026-08-14）

- 后端端口 8792；nginx 把 /v1/、/api/、/data/、/fast/ 反代到 backend:8792，80 端口对外
- 前端构建：web/web（npm install + npm run build），静态目录 /usr/share/nginx/html
- 数据目录：deploy/data（用户/积分/订单/生成图片），备份时打包它
- 模型清单：gpt-image-2、nano-banana-2、nano-banana-fast、nano-banana-pro（render_core.py SUPPORTED_IMAGE_MODELS）
- 渠道地址只从环境变量读取（GRSAI_BASE_URL 等），代码无硬编码渠道域名

## 九、验收清单（每项都要真实验证）

1. http://106.52.254.164 打开登录/注册页
2. 注册测试账号能登录
3. 生成一张图，积分正常扣减
4. 下单支付出微信二维码（商户号配置后）
5. 支付回调收到（商户平台可查）

## 十、回授给我（维护前提）

部署完成后请提供：

1. SSH 登录方式（root 密码，或把我的公钥加入服务器 authorized_keys）
2. 服务器上实际部署目录（默认 /opt/ai-render）
3. 容器名（默认 ai-render-commercial-backend / frontend）
4. 域名与备案状态
5. .env 里已填写的渠道（若与我本地不同，说明差异）

拿到这些后，我就能直接 docker compose up -d --build 做更新、看日志、改配置、处理故障。