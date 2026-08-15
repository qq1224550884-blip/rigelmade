#!/usr/bin/env python3
"""Seed the approved commercial catalog and per-image credit prices."""
from __future__ import annotations

from commercial_app import db, init_db, now


# 定价方案：1 积分 = ¥0.01 面值，按生成张数倍增扣费。
# 原则：每张只赚一点点（贴近成本），绝不亏本；nano-banana-pro 成本与普通版相同、可略贵。
PRODUCTS = (
    # 体验包 ¥9.9 / 700 积分（拉新引流，约 41 张 gpt 或 31 张 banana）
    ("starter-700", "体验包", 700, 990),
    # 工作室包 ¥29.9 / 2200 积分（主推，约 129 张 gpt 或 100 张 banana）
    ("studio-2200", "工作室包", 2200, 2990),
    # 专业包 ¥69 / 5500 积分（高频用户，约 323 张 gpt 或 250 张 banana）
    ("pro-5500", "专业包", 5500, 6900),
)
# 历史废弃套餐 ID：新定价上线后自动停用，避免用户看到两套价格。
OBSOLETE_PRODUCT_IDS = ("starter-100", "studio-600", "pro-2500", "starter-650", "studio-2400", "pro-9000")
# 单张图片积分价（1 积分 = ¥0.01）：
#   gpt-image-2     成本 ¥0.15/张 → 收 17 积分（¥0.17），毛利约 +13%
#   nano-banana-2   成本 ¥0.201/张 → 收 22 积分（¥0.22），毛利约 +9%
#   nano-banana-fast 成本 ¥0.201/张 → 收 22 积分（¥0.22），毛利约 +9%
#   nano-banana-pro 成本 ¥0.201/张 → 收 25 积分（¥0.25），毛利约 +24%
UNIT_PRICES = {
    "gpt-image-2": 17,
    "nano-banana-2": 22,
    "nano-banana-fast": 22,
    "nano-banana-pro": 25,
}
QUALITY_LEVELS = ("auto", "low", "medium", "high", "standard", "hd")


def main() -> None:
    init_db()
    timestamp = now()
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        for product_id, name, credits, amount_fen in PRODUCTS:
            connection.execute(
                """INSERT INTO products(id,name,credits,amount_fen,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,credits=excluded.credits,amount_fen=excluded.amount_fen,active=excluded.active,updated_at=excluded.updated_at""",
                (product_id, name, credits, amount_fen, 1, timestamp, timestamp),
            )
        for product_id in OBSOLETE_PRODUCT_IDS:
            connection.execute(
                "UPDATE products SET active=0, updated_at=? WHERE id=?",
                (timestamp, product_id),
            )
        for model, credits in UNIT_PRICES.items():
            for quality in QUALITY_LEVELS:
                connection.execute(
                    """INSERT INTO model_prices(model,quality,credits,active,updated_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(model,quality) DO UPDATE SET credits=excluded.credits,active=excluded.active,updated_at=excluded.updated_at""",
                    (model, quality, credits, 1, timestamp),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("Commercial pricing seeded: 3 products, 18 model-quality prices.")


if __name__ == "__main__":
    main()
