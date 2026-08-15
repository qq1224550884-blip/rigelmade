# 商业版服务器部署文档

部署对象：AI 效果图工作台商业版（FastAPI 后端 + Vite 前端 + nginx）
目标服务器：腾讯云轻量应用服务器（已购，IP 106.52.254.164，广州节点）

---

## 一、前置条件（未完成的先补上）

1. 服务器：已购，地域为大陆（已验证）——完成
2. 域名：还没买（不着急，备案提交前买即可）
3. ICP 备案：域名买好后提交（审批约 1~2 周）
4. 营业执照经营范围变更：加“软件开发 / 信息技术服务 / 互联网信息服务”（昆明个体户线上可办，1~7 天）
5. 微信支付商户号：营业执照变更通过后申请（必须，否则不能收款）

---

## 二、服务器初始化（只做一次）

用电脑的 PowerShell 登录服务器（或腾讯云控制台网页终端）：

    ssh root@106.52.254.164

登录后安装 Docker：

    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    docker --version

在腾讯云控制台“防火墙”里放行 80 和 443 端口（轻量服务器默认可能只开了 22）。

---

## 三、上传代码到服务器

在本地电脑（项目根目录 H:\desktop-workspace\ai-render-commercial）执行，用 tar 管道传输（自动排除 node_modules 等大目录，几秒传完）：

    ssh root@106.52.254.164 "mkdir -p /opt/ai-render"
    tar --exclude='*/node_modules' --exclude='*/dist' --exclude='*/__pycache__' --exclude='*/.git' --exclude='deploy/data' --exclude='deploy/certs' --exclude='deploy/.env' -czf - commercial_app.py render_core.py manage.py seed_pricing.py requirements.txt requirements-render-core.txt deploy web | ssh root@106.52.254.164 "tar -xzf - -C /opt/ai-render"

说明：web/web 下的 node_modules 不传，服务器构建时由 npm install 重新生成。

---

## 四、配置环境变量（密钥）

    cd /opt/ai-render/deploy
    cp .env.example .env
    vi .env

需要填的内容：

- GRSAI_API_KEY / NANO_BANANA_API_KEY / FAST_BANANA_API_KEY：三个生图渠道密钥（和你本地用的同一个）
- COMMERCIAL_AUTH_SECRET：生成一个 32 位以上随机串：
      openssl rand -hex 32
- SITE_ORIGIN：https://你的域名（备案通过后填真实域名）
- 微信支付七项：商户号审核通过后填

注意：这个文件包含密钥，不要提交到代码仓库、不要发给别人。服务器上改好后建议执行 chmod 600 .env。

---

## 五、构建并启动

    cd /opt/ai-render/deploy
    docker compose up -d --build

验证：

    docker compose ps          # 两个容器都应为 running
    curl http://127.0.0.1/api/health
    # 应返回 {"ok":true,"service":"commercial",...}

浏览器访问服务器 IP（http://106.52.254.164）应能看到登录/注册页。

---

## 六、初始化数据（管理员和定价）

    docker compose exec backend python seed_pricing.py
    docker compose exec backend python manage.py create_admin

按提示输入管理员邮箱、显示名、密码（至少 10 位）。记住这套账号，以后进管理后台用。

---

## 七、绑定域名 + HTTPS（微信支付强制要求）

1. 备案通过后，在腾讯云 DNS 控制台把域名加一条 A 记录，指向 106.52.254.164。
2. 腾讯云控制台搜索“SSL 证书”，申请免费证书（选域名验证），审核通过后下载 Nginx 版证书。
3. 把证书文件改名为 fullchain.crt 和 privkey.key，上传到服务器：

    scp fullchain.crt privkey.key root@106.52.254.164:/opt/ai-render/deploy/certs/

4. 用 HTTPS 版配置替换默认配置（已附好 nginx-ssl.conf，含 80 自动跳转 443）：

    cp deploy/nginx-ssl.conf deploy/nginx.conf
    vi deploy/nginx.conf
    # 把里面的 your-domain.com 改成你的真实域名

5. 重建前端容器：

    docker compose up -d --build frontend

6. 把微信支付 notify_url 和 SITE_ORIGIN 里的域名换成正式域名（.env 里改），然后：

    docker compose up -d

---

## 八、验收清单（按顺序确认）

1. http://你的域名 能打开登录页
2. https://你的域名 能打开（证书生效）
3. 注册一个测试账号，能登录
4. 生成一张图，积分正常扣减
5. 下单支付能出微信二维码，扫码支付后积分自动到账（商户号配置正确时）
6. 支付回调能收到（微信商户平台可查回调记录）

每一项都要实际验证，不能只看“看起来部署好了”。

---

## 九、日常维护

更新代码（本地改完重新上传后）：

    cd /opt/ai-render/deploy
    docker compose up -d --build

数据都在 deploy/data 目录（用户、积分、订单、生成图片）。备份时打包它：

    tar -czf backup-$(date +%Y%m%d).tar.gz data

恢复：解压回 deploy/data 后 docker compose up -d。

看日志：

    docker compose logs -f backend
    docker compose logs -f frontend

---

## 十、注意事项

- 密钥只在服务器 .env 里，代码仓库和本地项目里不放明文。
- 微信支付商户私钥（apiclient_key.pem）绝不能外传，它直接管钱。
- SQLite 单文件数据库，前期够用；等用户量大再考虑换 MySQL/PostgreSQL。
- 服务器到期前记得续费，否则网站直接下线。
- 原画板（本地 3000/8790）不受影响，两边独立运行。
