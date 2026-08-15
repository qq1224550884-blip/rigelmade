"""持久化限流：滑动窗口计数，存 SQLite，进程重启不失效。

用于防暴力破解（登录）、防注册滥用、防配额盗刷（生成）。
与商业主库分开存储，避免业务查询互相阻塞。
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

_DATA_DIR = Path(os.getenv("COMMERCIAL_DATA_DIR", Path(__file__).resolve().parent / "data")).resolve()
_DB_PATH = Path(os.getenv("COMMERCIAL_RATE_LIMIT_DB", _DATA_DIR / "rate_limit.sqlite3"))

_SCHEMA_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS rate_events (scope TEXT NOT NULL, key TEXT NOT NULL, event_at INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_rate_scope_key ON rate_events(scope, key, event_at)",
    "CREATE TABLE IF NOT EXISTS welcome_grants (ip TEXT NOT NULL PRIMARY KEY, total_credits INTEGER NOT NULL DEFAULT 0)",
)


def _connection() -> sqlite3.Connection:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10, isolation_level=None)
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    return conn


def check_rate_limit(scope: str, key: str, max_events: int, window_seconds: int) -> int:
    """滑动窗口内允许 max_events 次；超限返回应等待的秒数，未超限返回 0。"""
    now = int(time.time())
    cutoff = now - window_seconds
    conn = _connection()
    try:
        conn.execute("DELETE FROM rate_events WHERE event_at < ?", (cutoff,))
        conn.execute("INSERT INTO rate_events(scope, key, event_at) VALUES(?, ?, ?)", (scope, key, now))
        count = conn.execute(
            "SELECT COUNT(*) FROM rate_events WHERE scope = ? AND key = ? AND event_at > ?",
            (scope, key, cutoff),
        ).fetchone()[0]
        if count <= max_events:
            return 0
        # 计算最早一次事件还要多久移出窗口，作为重试等待时间
        oldest = conn.execute(
            "SELECT MIN(event_at) FROM rate_events WHERE scope = ? AND key = ? AND event_at > ?",
            (scope, key, cutoff),
        ).fetchone()[0] or now
        return max(1, int(cutoff + window_seconds - oldest))
    finally:
        conn.close()


def prune_old_events(scope: str, key: str, window_seconds: int) -> None:
    """清理当前 scope/key 的过期事件（例如登录成功后清除失败计数）。"""
    conn = _connection()
    try:
        conn.execute("DELETE FROM rate_events WHERE scope = ? AND key = ? AND event_at < ?", (scope, key, int(time.time()) - window_seconds))
    finally:
        conn.close()


def grant_welcome_credits(ip: str, amount: int, cap: int) -> int:
    """按 IP 累计欢迎积分，返回本次实际可授予的积分数。

    同一 IP 所有注册账号的欢迎积分总和不超过 cap。
    返回值为 0 表示该 IP 已达上限，不应再送积分。
    """
    if amount <= 0 or cap <= 0:
        return 0
    conn = _connection()
    try:
        row = conn.execute("SELECT total_credits FROM welcome_grants WHERE ip = ?", (ip,)).fetchone()
        already = row[0] if row else 0
        if already >= cap:
            return 0
        grant = min(amount, cap - already)
        conn.execute(
            "INSERT INTO welcome_grants(ip, total_credits) VALUES(?, ?) ON CONFLICT(ip) DO UPDATE SET total_credits = total_credits + ?",
            (ip, grant, grant),
        )
        return grant
    finally:
        conn.close()
