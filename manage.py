#!/usr/bin/env python3
"""Local-only administration entrypoint for the commercial service."""
from __future__ import annotations

import argparse
import getpass
import sqlite3
import uuid

from commercial_app import db, init_db, now, password_hash


def create_admin() -> None:
    email = input("管理员邮箱: ").strip().lower()
    display_name = input("显示名称: ").strip()
    password = getpass.getpass("管理员密码（至少 10 位）: ")
    if "@" not in email or not display_name or len(password) < 10:
        raise SystemExit("邮箱、显示名称或密码不符合要求。")
    init_db()
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO users(id,email,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, email, display_name, password_hash(password), "admin", now()))
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise SystemExit("该邮箱已注册，不能重复创建管理员。") from exc
    finally:
        connection.close()
    print("管理员已创建。请登录商业版后配置积分套餐和模型积分价格。")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 效果图商业版本地管理命令")
    parser.add_argument("command", choices=["create-admin"])
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin()


if __name__ == "__main__":
    main()
