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
    wait, _ = check_rate_limits([(scope, key, max_events, window_seconds)])
    return wait


def check_rate_limits(limits: list[tuple[str, str, int, int]]) -> tuple[int, list[tuple[int, int]]]:
    """原子检查所有窗口，通过后才计数；返回等待秒数和可撤销的计数凭据。"""
    now = int(time.time())
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        wait = 0
        for scope, key, max_events, window_seconds in limits:
            cutoff = now - window_seconds
            conn.execute("DELETE FROM rate_events WHERE scope = ? AND key = ? AND event_at <= ?", (scope, key, cutoff))
            count = conn.execute(
                "SELECT COUNT(*) FROM rate_events WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()[0]
            if count >= max_events:
                # 兼容旧版本累积的超限事件，等到有足够事件过期才能接收下一次。
                expires_at = conn.execute(
                    "SELECT event_at FROM rate_events WHERE scope = ? AND key = ? ORDER BY event_at LIMIT 1 OFFSET ?",
                    (scope, key, count - max_events),
                ).fetchone()[0] + window_seconds
                wait = max(wait, expires_at - now)
        events = []
        if not wait:
            for scope, key, _, _ in limits:
                cursor = conn.execute("INSERT INTO rate_events(scope, key, event_at) VALUES(?, ?, ?)", (scope, key, now))
                events.append((cursor.lastrowid, now))
        conn.commit()
        return wait, events
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_rate_limits(events: list[tuple[int, int]]) -> None:
    """生成失败时退回本次计数；时间戳防止误删被 SQLite 重用的行号。"""
    conn = _connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("DELETE FROM rate_events WHERE rowid = ? AND event_at = ?", events)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
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
