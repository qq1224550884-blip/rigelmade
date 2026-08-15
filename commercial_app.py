#!/usr/bin/env python3
"""Independent commercial gateway for AI Render Canvas.

It owns identities, credits and payments. Provider keys remain server-only and
are supplied by the launcher as process environment variables.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import rate_limit
import render_core


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("COMMERCIAL_DATA_DIR", APP_DIR / "data")).resolve()
DB_PATH = Path(os.getenv("COMMERCIAL_DB_PATH", DATA_DIR / "commercial.sqlite3")).resolve()
AUTH_SECRET = os.getenv("COMMERCIAL_AUTH_SECRET", "")
ENVIRONMENT = os.getenv("COMMERCIAL_ENV", "development").lower()
TOKEN_TTL_SECONDS = int(os.getenv("COMMERCIAL_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 14)))
PAYMENT_ENABLED = os.getenv("COMMERCIAL_PAYMENT_ENABLED", "").lower() in {"1", "true", "yes"}
WELCOME_CREDITS = int(os.getenv("COMMERCIAL_WELCOME_CREDITS", "0"))
WELCOME_CREDITS_PER_IP = int(os.getenv("COMMERCIAL_WELCOME_CREDITS_PER_IP", str(WELCOME_CREDITS)))
WECHAT_API = "https://api.mch.weixin.qq.com"

if ENVIRONMENT == "production" and len(AUTH_SECRET) < 32:
    raise RuntimeError("COMMERCIAL_AUTH_SECRET must be at least 32 characters in production.")
if not AUTH_SECRET:
    AUTH_SECRET = secrets.token_urlsafe(48)

DATA_DIR.mkdir(parents=True, exist_ok=True)
render_core.DATA_DIR = DATA_DIR / "render-data"
render_core.ASSET_DIR = render_core.DATA_DIR / "assets"
render_core.RUN_DIR = render_core.DATA_DIR / "runs"
render_core.ASSET_DIR.mkdir(parents=True, exist_ok=True)
render_core.RUN_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Render Commercial", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in os.getenv("COMMERCIAL_CORS_ORIGINS", "http://127.0.0.1:3002,http://localhost:3002").split(",") if item.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> int:
    return int(time.time())


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with transaction() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                token_hash TEXT NOT NULL UNIQUE,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                revoked_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS credit_ledger (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                reference_id TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_created ON credit_ledger(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                credits INTEGER NOT NULL CHECK(credits > 0),
                amount_fen INTEGER NOT NULL CHECK(amount_fen > 0),
                active INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payment_orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                product_id TEXT NOT NULL REFERENCES products(id),
                amount_fen INTEGER NOT NULL,
                credits INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('created','paying','paid','closed','refunded')),
                wechat_transaction_id TEXT UNIQUE,
                code_url TEXT,
                created_at INTEGER NOT NULL,
                paid_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_payment_orders_user_created ON payment_orders(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS model_prices (
                model TEXT NOT NULL,
                quality TEXT NOT NULL,
                credits INTEGER NOT NULL CHECK(credits > 0),
                active INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(model, quality)
            );
            CREATE TABLE IF NOT EXISTS render_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                run_id TEXT UNIQUE,
                idempotency_key TEXT NOT NULL,
                model TEXT NOT NULL,
                credits INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed')),
                result_json TEXT,
                created_at INTEGER NOT NULL,
                completed_at INTEGER,
                UNIQUE(user_id, idempotency_key)
            );
            """
        )


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f"scrypt${b64(salt)}${b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_text, digest_text = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=b64_decode(salt_text), n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(actual, b64_decode(digest_text))
    except (ValueError, TypeError):
        return False


def issue_token(user_id: str, session_id: str, expires_at: int) -> str:
    payload = b64(json.dumps({"sub": user_id, "sid": session_id, "exp": expires_at}, separators=(",", ":")).encode("utf-8"))
    signature = b64(hmac.new(AUTH_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def parse_token(token: str) -> dict[str, Any]:
    try:
        payload, signature = token.split(".", 1)
        expected = b64(hmac.new(AUTH_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        value = json.loads(b64_decode(payload))
        if not isinstance(value, dict) or int(value.get("exp", 0)) <= now():
            raise ValueError("expired")
        return value
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。") from exc


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_user(authorization: str | None = Header(default=None)) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录。")
    token = authorization[7:].strip()
    claims = parse_token(token)
    connection = db()
    try:
        row = connection.execute(
            """SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.id = ? AND sessions.token_hash = ? AND sessions.revoked_at IS NULL
               AND sessions.expires_at > ? AND users.status = 'active'""",
            (str(claims.get("sid", "")), token_hash(token), now()),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。")
    return row


def require_admin(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作。")
    return user


def user_balance(connection: sqlite3.Connection, user_id: str) -> int:
    return int(connection.execute("SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE user_id = ?", (user_id,)).fetchone()[0])


def user_view(connection: sqlite3.Connection, user: sqlite3.Row) -> dict[str, Any]:
    return {"id": user["id"], "email": user["email"], "displayName": user["display_name"], "role": user["role"], "credits": user_balance(connection, user["id"])}


def openai_image_result(result: dict[str, Any]) -> dict[str, Any]:
    run_id = str(result.get("runId") or "")
    items: list[dict[str, str]] = []
    for output in result.get("outputs") or []:
        name = Path(str(output.get("name") or "")).name
        path = render_core.RUN_DIR / run_id / "outputs" / name
        if path.is_file():
            items.append({"b64_json": base64.b64encode(path.read_bytes()).decode("ascii")})
        elif str(output.get("url") or "").startswith(("https://", "http://")):
            items.append({"url": str(output["url"])})
    if not items:
        raise HTTPException(status_code=502, detail=result.get("message") or "生图服务没有返回图片。")
    return {"created": now(), "data": items, "runId": run_id, "status": result.get("status", "succeeded")}


class RegisterPayload(BaseModel):
    email: str
    display_name: str = Field(alias="displayName")
    password: str


class LoginPayload(BaseModel):
    email: str
    password: str


class ProductPayload(BaseModel):
    name: str
    credits: int
    amount_fen: int = Field(alias="amountFen")
    active: bool = False


class ModelPricePayload(BaseModel):
    model: str
    quality: str
    credits: int
    active: bool = True


class AdminUserStatusPayload(BaseModel):
    status: str


class AdminCreditAdjustmentPayload(BaseModel):
    delta: int
    note: str = "管理员调整"


class CreatePaymentPayload(BaseModel):
    product_id: str = Field(alias="productId")


class CommercialGeneratePayload(BaseModel):
    request: dict[str, Any]
    idempotency_key: str = Field(alias="idempotencyKey")


def require_wechat_config() -> dict[str, str]:
    keys = ("WECHATPAY_MCHID", "WECHATPAY_APPID", "WECHATPAY_SERIAL_NO", "WECHATPAY_PRIVATE_KEY_PATH", "WECHATPAY_NOTIFY_URL")
    values = {key: os.getenv(key, "").strip() for key in keys}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise HTTPException(status_code=503, detail=f"微信支付尚未配置：{', '.join(missing)}")
    key_path = Path(values["WECHATPAY_PRIVATE_KEY_PATH"])
    if not key_path.is_file():
        raise HTTPException(status_code=503, detail="微信支付商户私钥文件不可用。")
    return values


def wechat_authorization(method: str, path: str, body: str, config: dict[str, str]) -> str:
    timestamp = str(now())
    nonce = secrets.token_urlsafe(24)
    message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode("utf-8")
    private_key = serialization.load_pem_private_key(Path(config["WECHATPAY_PRIVATE_KEY_PATH"]).read_bytes(), password=None)
    signature = base64.b64encode(private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    return f'WECHATPAY2-SHA256-RSA2048 mchid="{config["WECHATPAY_MCHID"]}",nonce_str="{nonce}",timestamp="{timestamp}",serial_no="{config["WECHATPAY_SERIAL_NO"]}",signature="{signature}"'


def create_wechat_native_order(order: sqlite3.Row) -> str:
    config = require_wechat_config()
    path = "/v3/pay/transactions/native"
    body = json.dumps({
        "appid": config["WECHATPAY_APPID"], "mchid": config["WECHATPAY_MCHID"], "description": f"AI效果图积分 {order['credits']}",
        "out_trade_no": order["id"], "notify_url": config["WECHATPAY_NOTIFY_URL"], "amount": {"total": order["amount_fen"], "currency": "CNY"},
    }, separators=(",", ":"), ensure_ascii=False)
    response = requests.post(f"{WECHAT_API}{path}", data=body.encode("utf-8"), headers={"Authorization": wechat_authorization("POST", path, body, config), "Content-Type": "application/json", "Accept": "application/json"}, timeout=20)
    if response.status_code >= 400:
        try:
            message = response.json().get("message", "微信支付下单失败")
        except ValueError:
            message = "微信支付下单失败"
        raise HTTPException(status_code=502, detail=f"微信支付下单失败：{message}")
    value = response.json()
    code_url = str(value.get("code_url", ""))
    if not code_url.startswith("weixin://"):
        raise HTTPException(status_code=502, detail="微信支付没有返回有效收款码。")
    return code_url


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/config")
def public_config() -> dict[str, Any]:
    return {"paymentEnabled": PAYMENT_ENABLED, "welcomeCredits": WELCOME_CREDITS, "environment": ENVIRONMENT}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "commercial", "environment": ENVIRONMENT, "wechatConfigured": all(os.getenv(key, "").strip() for key in ("WECHATPAY_MCHID", "WECHATPAY_APPID", "WECHATPAY_SERIAL_NO", "WECHATPAY_PRIVATE_KEY_PATH", "WECHATPAY_NOTIFY_URL"))}


@app.post("/api/auth/register")
def register(request: Request, payload: RegisterPayload) -> dict[str, Any]:
    enforce_register_rate_limit(request)
    email = payload.email.strip().lower()
    name = payload.display_name.strip()
    if "@" not in email or len(email) > 160 or not name or len(name) > 80 or len(payload.password) < 10:
        raise HTTPException(status_code=400, detail="请填写有效邮箱、昵称，并使用至少 10 位密码。")
    user_id = uuid.uuid4().hex
    try:
        with transaction() as connection:
            connection.execute("INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES(?,?,?,?,?)", (user_id, email, name, password_hash(payload.password), now()))
            granted = rate_limit.grant_welcome_credits(client_ip(request), WELCOME_CREDITS, WELCOME_CREDITS_PER_IP) if WELCOME_CREDITS > 0 else 0
            if granted > 0:
                connection.execute("INSERT INTO credit_ledger(id,user_id,delta,reason,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, user_id, granted, "welcome", user_id, "新用户注册赠送积分", now()))
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return {"user": user_view(connection, row), "welcomeCredits": granted}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="该邮箱已经注册。") from exc


@app.post("/api/auth/login")
def login(request: Request, payload: LoginPayload) -> dict[str, Any]:
    enforce_login_rate_limit(request, payload.email.strip().lower())
    connection = db()
    try:
        user = connection.execute("SELECT * FROM users WHERE email = ?", (payload.email.strip().lower(),)).fetchone()
    finally:
        connection.close()
    if user is None or user["status"] != "active" or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确。")
    session_id, expires_at = uuid.uuid4().hex, now() + TOKEN_TTL_SECONDS
    token = issue_token(user["id"], session_id, expires_at)
    with transaction() as connection:
        connection.execute("INSERT INTO sessions(id,user_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?)", (session_id, user["id"], token_hash(token), expires_at, now()))
        return {"token": token, "expiresAt": expires_at, "user": user_view(connection, user)}


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None), user: sqlite3.Row = Depends(current_user)) -> dict[str, bool]:
    del user
    token = (authorization or "")[7:].strip()
    claims = parse_token(token)
    with transaction() as connection:
        connection.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (now(), claims["sid"]))
    return {"ok": True}


@app.get("/api/me")
def me(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    connection = db()
    try:
        return {"user": user_view(connection, user)}
    finally:
        connection.close()


@app.get("/api/catalog/products")
def catalog() -> dict[str, Any]:
    if not PAYMENT_ENABLED:
        return {"products": []}
    connection = db()
    try:
        products = connection.execute("SELECT id,name,credits,amount_fen FROM products WHERE active = 1 ORDER BY amount_fen ASC").fetchall()
        return {"products": [{"id": row["id"], "name": row["name"], "credits": row["credits"], "amountFen": row["amount_fen"]} for row in products]}
    finally:
        connection.close()


@app.get("/api/catalog/pricing")
def catalog_pricing(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    del user
    connection = db()
    try:
        rows = connection.execute("SELECT model,quality,credits FROM model_prices WHERE active = 1 ORDER BY model,quality").fetchall()
        return {"prices": [{"model": row["model"], "quality": row["quality"], "credits": row["credits"]} for row in rows]}
    finally:
        connection.close()


@app.get("/api/billing/ledger")
def ledger(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    connection = db()
    try:
        rows = connection.execute("SELECT id,delta,reason,reference_id,note,created_at FROM credit_ledger WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user["id"],)).fetchall()
        return {"balance": user_balance(connection, user["id"]), "items": [{"id": row["id"], "delta": row["delta"], "reason": row["reason"], "referenceId": row["reference_id"], "note": row["note"], "createdAt": row["created_at"]} for row in rows]}
    finally:
        connection.close()


@app.post("/api/payments/wechat/native")
def create_payment(payload: CreatePaymentPayload, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    if not PAYMENT_ENABLED:
        raise HTTPException(status_code=503, detail="支付功能暂未开放。")
    with transaction() as connection:
        product = connection.execute("SELECT * FROM products WHERE id = ? AND active = 1", (payload.product_id,)).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="积分套餐不存在或尚未上架。")
        order_id = f"AR{time.strftime('%Y%m%d')}{uuid.uuid4().hex[:18].upper()}"
        connection.execute("INSERT INTO payment_orders(id,user_id,product_id,amount_fen,credits,status,created_at) VALUES(?,?,?,?,?,?,?)", (order_id, user["id"], product["id"], product["amount_fen"], product["credits"], "created", now()))
        order = connection.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
    try:
        code_url = create_wechat_native_order(order)
    except Exception:
        with transaction() as connection:
            connection.execute("UPDATE payment_orders SET status = 'closed' WHERE id = ? AND status = 'created'", (order_id,))
        raise
    with transaction() as connection:
        connection.execute("UPDATE payment_orders SET status = 'paying', code_url = ? WHERE id = ?", (code_url, order_id))
    return {"orderId": order_id, "codeUrl": code_url, "amountFen": order["amount_fen"], "credits": order["credits"]}


@app.get("/api/payments/wechat/status")
def payment_status(payload_order_id: str = Header(default="", alias="X-Order-Id"), user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    if not payload_order_id:
        raise HTTPException(status_code=400, detail="缺少订单号。")
    connection = db()
    try:
        order = connection.execute("SELECT status,credits FROM payment_orders WHERE id = ? AND user_id = ?", (payload_order_id, user["id"])).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在。")
        return {"orderId": payload_order_id, "status": order["status"], "credits": order["credits"], "paid": order["status"] == "paid"}
    finally:
        connection.close()


@app.post("/api/payments/wechat/notify")
async def wechat_notify(request: Request) -> dict[str, str]:
    config = require_wechat_config()
    api_v3_key = os.getenv("WECHATPAY_API_V3_KEY", "")
    certificate_path = Path(os.getenv("WECHATPAY_PLATFORM_CERT_PATH", ""))
    if len(api_v3_key.encode("utf-8")) != 32 or not certificate_path.is_file():
        raise HTTPException(status_code=503, detail="微信支付回调验签配置不完整。")
    body = (await request.body()).decode("utf-8")
    timestamp = request.headers.get("Wechatpay-Timestamp", "")
    nonce = request.headers.get("Wechatpay-Nonce", "")
    signature = request.headers.get("Wechatpay-Signature", "")
    try:
        stale = abs(now() - int(timestamp)) > 300
    except ValueError:
        stale = True
    if not timestamp or not nonce or not signature or stale:
        raise HTTPException(status_code=400, detail="微信支付回调请求无效。")
    message = f"{timestamp}\n{nonce}\n{body}\n".encode("utf-8")
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    try:
        certificate.public_key().verify(base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256())
        notification = json.loads(body)
        resource = notification["resource"]
        plaintext = AESGCM(api_v3_key.encode("utf-8")).decrypt(resource["nonce"].encode("utf-8"), base64.b64decode(resource["ciphertext"]), resource.get("associated_data", "").encode("utf-8"))
        payment = json.loads(plaintext)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="微信支付回调验签或解密失败。") from exc
    if payment.get("trade_state") != "SUCCESS" or payment.get("mchid") != config["WECHATPAY_MCHID"] or payment.get("appid") != config["WECHATPAY_APPID"]:
        raise HTTPException(status_code=400, detail="微信支付回调数据不匹配。")
    order_id, transaction_id = str(payment.get("out_trade_no", "")), str(payment.get("transaction_id", ""))
    amount = int((payment.get("amount") or {}).get("total", -1))
    with transaction() as connection:
        dup = connection.execute("SELECT id FROM payment_orders WHERE wechat_transaction_id = ?", (transaction_id,)).fetchone()
        if dup is not None:
            if dup["id"] == order_id:
                return {"code": "SUCCESS", "message": "成功"}  # 已处理，幂等返回
            raise HTTPException(status_code=400, detail="交易ID已关联其他订单。")
        order = connection.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
        if order is None or order["amount_fen"] != amount:
            raise HTTPException(status_code=400, detail="订单金额不匹配。")
        if order["status"] != "paid":
            connection.execute("UPDATE payment_orders SET status = 'paid', wechat_transaction_id = ?, paid_at = ? WHERE id = ?", (transaction_id, now(), order_id))
            connection.execute("INSERT INTO credit_ledger(id,user_id,delta,reason,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, order["user_id"], order["credits"], "payment", order_id, "微信支付充值", now()))
    return {"code": "SUCCESS", "message": "成功"}


@app.get("/api/admin/products")
def admin_products(admin: sqlite3.Row = Depends(require_admin)) -> dict[str, Any]:
    del admin
    connection = db()
    try:
        rows = connection.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
        return {"products": [{"id": row["id"], "name": row["name"], "credits": row["credits"], "amountFen": row["amount_fen"], "active": bool(row["active"])} for row in rows]}
    finally:
        connection.close()


@app.post("/api/admin/products")
def create_product(payload: ProductPayload, admin: sqlite3.Row = Depends(require_admin)) -> dict[str, Any]:
    del admin
    if not payload.name.strip() or payload.credits <= 0 or payload.amount_fen <= 0:
        raise HTTPException(status_code=400, detail="套餐名称、积分和价格必须有效。")
    product_id = uuid.uuid4().hex
    with transaction() as connection:
        connection.execute("INSERT INTO products(id,name,credits,amount_fen,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (product_id, payload.name.strip(), payload.credits, payload.amount_fen, int(payload.active), now(), now()))
    return {"id": product_id}


@app.get("/api/admin/model-prices")
def admin_model_prices(admin: sqlite3.Row = Depends(require_admin)) -> dict[str, Any]:
    del admin
    connection = db()
    try:
        rows = connection.execute("SELECT model,quality,credits,active,updated_at FROM model_prices ORDER BY model,quality").fetchall()
        return {"items": [{"model": row["model"], "quality": row["quality"], "credits": row["credits"], "active": bool(row["active"]), "updatedAt": row["updated_at"]} for row in rows]}
    finally:
        connection.close()


@app.put("/api/admin/model-prices")
def set_model_price(payload: ModelPricePayload, admin: sqlite3.Row = Depends(require_admin)) -> dict[str, bool]:
    del admin
    if not payload.model.strip() or not payload.quality.strip() or payload.credits <= 0:
        raise HTTPException(status_code=400, detail="模型、质量档和积分必须有效。")
    with transaction() as connection:
        connection.execute("INSERT INTO model_prices(model,quality,credits,active,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(model,quality) DO UPDATE SET credits=excluded.credits,active=excluded.active,updated_at=excluded.updated_at", (payload.model.strip(), payload.quality.strip(), payload.credits, int(payload.active), now()))
    return {"ok": True}


@app.get("/api/admin/keys")
def admin_keys(admin: sqlite3.Row = Depends(require_admin)) -> dict[str, Any]:
    return {"pools": render_core.key_pool_status()}


@app.get("/api/admin/users")
def admin_users(admin: sqlite3.Row = Depends(require_admin)) -> dict[str, Any]:
    del admin
    connection = db()
    try:
        rows = connection.execute(
            """
            SELECT
                u.id,
                u.email,
                u.display_name,
                u.role,
                u.status,
                u.created_at,
                COALESCE((SELECT SUM(delta) FROM credit_ledger WHERE user_id = u.id), 0) AS credits,
                COALESCE((SELECT SUM(-delta) FROM credit_ledger WHERE user_id = u.id AND reason = 'render_reserve' AND delta < 0), 0) AS spent_credits,
                COALESCE((SELECT COUNT(*) FROM render_jobs WHERE user_id = u.id AND status = 'succeeded'), 0) AS generation_count
            FROM users u
            ORDER BY u.created_at DESC
            """
        ).fetchall()
        return {
            "users": [
                {
                    "id": row["id"],
                    "email": row["email"],
                    "displayName": row["display_name"],
                    "role": row["role"],
                    "status": row["status"],
                    "createdAt": row["created_at"],
                    "credits": int(row["credits"] or 0),
                    "spentCredits": int(row["spent_credits"] or 0),
                    "generationCount": int(row["generation_count"] or 0),
                }
                for row in rows
            ]
        }
    finally:
        connection.close()


@app.patch("/api/admin/users/{user_id}/status")
def set_user_status(user_id: str, payload: AdminUserStatusPayload, admin: sqlite3.Row = Depends(require_admin)) -> dict[str, bool]:
    status = payload.status.strip().lower()
    if status not in {"active", "disabled"}:
        raise HTTPException(status_code=400, detail="用户状态只能是 active 或 disabled。")
    with transaction() as connection:
        target = connection.execute("SELECT id, role, status FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="用户不存在。")
        if target["id"] == admin["id"] and status == "disabled":
            raise HTTPException(status_code=400, detail="不能停用当前管理员账号。")
        if target["role"] == "admin" and status == "disabled":
            active_admins = connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'").fetchone()[0]
            if int(active_admins) <= 1:
                raise HTTPException(status_code=400, detail="至少保留一个可用管理员账号。")
        connection.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        if status == "disabled":
            connection.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now(), user_id))
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/credits")
def adjust_user_credits(user_id: str, payload: AdminCreditAdjustmentPayload, admin: sqlite3.Row = Depends(require_admin)) -> dict[str, Any]:
    del admin
    note = payload.note.strip()[:200] or "管理员调整"
    if payload.delta == 0 or abs(payload.delta) > 1_000_000:
        raise HTTPException(status_code=400, detail="积分调整数量必须在 -1,000,000 到 1,000,000 之间且不能为 0。")
    with transaction() as connection:
        target = connection.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="用户不存在。")
        connection.execute(
            "INSERT INTO credit_ledger(id,user_id,delta,reason,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, user_id, payload.delta, "admin_adjustment", None, note, now()),
        )
        balance = user_balance(connection, user_id)
    return {"ok": True, "balance": balance}


@app.post("/api/generate")
def commercial_generate(request: Request, payload: CommercialGeneratePayload, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    enforce_generation_rate_limit(request, user["id"])
    try:
        request_model = render_core.GenerateRequest.model_validate(payload.request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="生成请求格式无效。") from exc
    key = payload.idempotency_key.strip()
    if not key or len(key) > 120:
        raise HTTPException(status_code=400, detail="缺少有效的幂等请求编号。")
    with transaction() as connection:
        existing = connection.execute("SELECT * FROM render_jobs WHERE user_id = ? AND idempotency_key = ?", (user["id"], key)).fetchone()
        if existing is not None:
            if existing["status"] == "succeeded" and existing["result_json"]:
                return json.loads(existing["result_json"])
            raise HTTPException(status_code=409, detail="该生成任务正在处理或刚刚失败，请勿重复提交。")
        price = connection.execute("SELECT credits FROM model_prices WHERE model = ? AND quality = ? AND active = 1", (request_model.model, request_model.image_size)).fetchone()
        if price is None:
            raise HTTPException(status_code=503, detail="该模型和画质尚未配置积分价格。")
        output_count = min(max(request_model.count, 1), 4)
        credits = int(price["credits"]) * output_count
        if user_balance(connection, user["id"]) < credits:
            raise HTTPException(status_code=402, detail="积分不足，请先充值。")
        job_id = uuid.uuid4().hex
        connection.execute("INSERT INTO render_jobs(id,user_id,idempotency_key,model,credits,status,created_at) VALUES(?,?,?,?,?,?,?)", (job_id, user["id"], key, request_model.model, credits, "reserved", now()))
        connection.execute("INSERT INTO credit_ledger(id,user_id,delta,reason,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, user["id"], -credits, "render_reserve", job_id, "生成预扣", now()))
    try:
        result = render_core.generate(request_model)
    except Exception:
        with transaction() as connection:
            connection.execute("UPDATE render_jobs SET status = 'failed', completed_at = ? WHERE id = ?", (now(), job_id))
            connection.execute("INSERT INTO credit_ledger(id,user_id,delta,reason,reference_id,note,created_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, user["id"], credits, "render_refund", job_id, "生成失败自动退款", now()))
        raise
    with transaction() as connection:
        connection.execute("UPDATE render_jobs SET status = 'succeeded', run_id = ?, result_json = ?, completed_at = ? WHERE id = ?", (result.get("runId"), json.dumps(result, ensure_ascii=False), now(), job_id))
    return result


@app.get("/v1/models")
def commercial_models(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    del user
    return {"object": "list", "data": [{"id": model, "object": "model", "owned_by": "ai-render-commercial"} for model in render_core.SUPPORTED_IMAGE_MODELS]}


@app.post("/v1/images/generations")
def commercial_image_generations(
    req: Request,
    payload: render_core.OpenAIImageGenerationRequest,
    x_idempotency_key: str | None = Header(default=None),
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    try:
        request_model = render_core.openai_generate_request(payload.model, payload.prompt, payload.n, payload.quality, payload.size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = commercial_generate(req, CommercialGeneratePayload(request=request_model.model_dump(by_alias=True), idempotencyKey=x_idempotency_key or uuid.uuid4().hex), user)
    return openai_image_result(result)


@app.post("/v1/images/edits")
async def commercial_image_edits(
    req: Request,
    image: list[UploadFile] = File(...),
    prompt: str = Form(""),
    model: str = Form(""),
    n: int = Form(1),
    quality: str = Form("low"),
    size: str = Form("1024x1024"),
    mask: UploadFile | None = File(None),
    x_idempotency_key: str | None = Header(default=None),
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    images: list[render_core.GenerateImage] = []
    for index, upload in enumerate(image, start=1):
        mime = upload.content_type or "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(status_code=400, detail="只支持图片参考图。")
        raw = await upload.read()
        images.append(render_core.GenerateImage(name=upload.filename or f"image-{index}.png", role="main" if index == 1 else "reference", dataUrl=f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"))
    if mask is not None:
        mime = mask.content_type or "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(status_code=400, detail="蒙版必须是图片。")
        images.append(render_core.GenerateImage(name=mask.filename or "mask.png", role="mask", dataUrl=f"data:{mime};base64,{base64.b64encode(await mask.read()).decode('ascii')}"))
    try:
        request_model = render_core.openai_generate_request(model, prompt, n, quality, size, images)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = commercial_generate(req, CommercialGeneratePayload(request=request_model.model_dump(by_alias=True), idempotencyKey=x_idempotency_key or uuid.uuid4().hex), user)
    return openai_image_result(result)


def client_ip(request: Request) -> str:
    """取客户端 IP：优先代理透传的 X-Forwarded-For，生产环境由 nginx 覆写，不可伪造。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def enforce_login_rate_limit(request: Request, email: str) -> None:
    """登录防爆破：每 IP 30 次/10 分钟，每邮箱 20 次/15 分钟。"""
    ip = client_ip(request)
    wait_ip = rate_limit.check_rate_limit("login_ip", ip, 30, 600)
    if wait_ip:
        raise HTTPException(status_code=429, detail=f"尝试过于频繁，请约 {wait_ip} 秒后再试。")
    wait_email = rate_limit.check_rate_limit("login_email", email, 20, 900)
    if wait_email:
        raise HTTPException(status_code=429, detail=f"该账号尝试过于频繁，请约 {wait_email} 秒后再试。")


def enforce_register_rate_limit(request: Request) -> None:
    """注册防滥用：每 IP 5 次/小时。"""
    ip = client_ip(request)
    wait = rate_limit.check_rate_limit("register_ip", ip, 5, 3600)
    if wait:
        raise HTTPException(status_code=429, detail=f"注册过于频繁，请约 {wait} 秒后再试。")


def enforce_generation_rate_limit(request: Request, user_id: str) -> None:
    """生成防盗刷：每用户 60 次/小时，每 IP 120 次/小时（令牌泄露时兜底）。"""
    wait_user = rate_limit.check_rate_limit("gen_user", user_id, 60, 3600)
    if wait_user:
        raise HTTPException(status_code=429, detail=f"生成频率过高，请约 {wait_user} 秒后再试。")
    wait_ip = rate_limit.check_rate_limit("gen_ip", client_ip(request), 120, 3600)
    if wait_ip:
        raise HTTPException(status_code=429, detail=f"生成频率过高，请约 {wait_ip} 秒后再试。")


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8792")))
