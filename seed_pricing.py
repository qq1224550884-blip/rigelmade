#!/usr/bin/env python3
"""Seed the approved commercial catalog and per-image credit prices.

Pricing basis (2026-08-16): 1 credit = ¥0.035 (toapis 充值成本).
每张/每秒按 toapis 成本 × 1.5 定价（成本 0.2 卖 0.3），保证覆盖成本并留合理毛利。
图片按分辨率分档；视频按"每秒积分 × 时长"计费（视频功能实现后启用）。
"""
from __future__ import annotations

from commercial_app import db, init_db, now


# 定价方案：1 积分 = ¥0.035（toapis 充值成本），扣费 = 成本 × 1.5。
# 原则：绝不亏本；单张图收 1.5 倍成本，视频每秒收 1.5 倍成本。
# ------------------------------------------------------------------
# 图片模型成本（toapis, 积分/张）与定价（积分/张，×1.5 向上取整）：
#   gpt-image-2     1K 成本 3 → 定价 5；2K 成本 4 → 6；4K 成本 5 → 8
#   gpt-image-2.5   官方 $0.015/0.020/0.025 每张，与 gpt-image-2 同档 → 5 / 6 / 8
#   nano-banana-2   1K 成本 6 → 定价 9；2K 成本 8 → 12；4K 成本 12 → 18
#   nano-banana-pro 成本 12 → 定价 18（全档）
# ------------------------------------------------------------------
# 视频模型成本（toapis, 积分/秒）与定价（积分/秒，×1.5 向上取整）：
#   grok-video-1.5    ¥0.07/s ≈ 2 积分/s → 定价 3
#   seedance-2-fast   480p ¥0.4 → 11.4 → 17；720p ¥0.8 → 22.9 → 34
#   seedance-2        480p ¥0.5 → 14.3 → 21；720p ¥1 → 28.6 → 43；1080p ¥2.5 → 71.4 → 107
#   MiniMax-H3        22.86 积分/s → 定价 34
# 注：视频价格行在视频生成功能上线时通过 VIDEO_UNIT_PRICES 写入并计费。
# ------------------------------------------------------------------
PRODUCTS = (
    # 套餐（1 积分 = ¥0.035 成本，按 ×1.4 左右定价，量越大单价越低）
    ("starter-1000", "体验包", 1000, 4900),     # 成本 ¥35 → 卖 ¥49
    ("studio-5000", "工作室包", 5000, 23900),   # 成本 ¥175 → 卖 ¥239
    ("pro-12000", "专业包", 12000, 54900),      # 成本 ¥420 → 卖 ¥549
)
# 历史废弃套餐 ID：新定价上线后自动停用，避免用户看到两套价格。
OBSOLETE_PRODUCT_IDS = (
    "starter-100", "studio-600", "pro-2500",
    "starter-650", "studio-2400", "pro-9000",
    "starter-700", "studio-2200", "pro-5500",
)
# 图片模型定价（积分/张，×1.5 向上取整），键为 model，值为 {resolution: credits}
IMAGE_PRICES = {
    "gpt-image-2": {"1K": 5, "2K": 6, "4K": 8},
    "gpt-image-2.5": {"1K": 5, "2K": 6, "4K": 8},
    "nano-banana-2": {"1K": 9, "2K": 12, "4K": 18},
    "nano-banana-fast": {"1K": 9, "2K": 12, "4K": 18},
    "nano-banana-pro": {"1K": 18, "2K": 18, "4K": 18},
}
# quality 档位 → 对应分辨率（与 render_core.pricing_quality 映射一致）
# auto/low/standard 按 1K 计；medium/hd 按 2K 计；high 按 4K 计
QUALITY_TO_RESOLUTION = {
    "auto": "1K", "low": "1K", "standard": "1K",
    "medium": "2K", "hd": "2K",
    "high": "4K",
}
QUALITY_LEVELS = ("auto", "low", "medium", "high", "standard", "hd")
# 视频模型定价（积分/秒，×1.5 向上取整），键为 model，值为 {quality: credits_per_second}
VIDEO_UNIT_PRICES = {
    "grok-video-1.5": {"480p": 3, "720p": 3},
    "seedance-2-fast": {"480p": 17, "720p": 34},
    "seedance-2": {"480p": 21, "720p": 43, "1080p": 107},
    "MiniMax-H3": {"2K": 34},
}


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
        # 图片模型：按分辨率档写入 model_prices（quality 列存 1K/2K/4K 直接可查）
        for model, by_resolution in IMAGE_PRICES.items():
            for quality, resolution in QUALITY_TO_RESOLUTION.items():
                credits = by_resolution[resolution]
                connection.execute(
                    """INSERT INTO model_prices(model,quality,credits,active,updated_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(model,quality) DO UPDATE SET credits=excluded.credits,active=excluded.active,updated_at=excluded.updated_at""",
                    (model, quality, credits, 1, timestamp),
                )
        # 视频模型：每秒积分单价，计费时 × 时长。
        for model, by_quality in VIDEO_UNIT_PRICES.items():
            for quality, credits in by_quality.items():
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
    image_rows = sum(len(v) for v in QUALITY_TO_RESOLUTION.values())
    video_rows = sum(len(v) for v in VIDEO_UNIT_PRICES.values())
    print(f"Commercial pricing seeded: {len(PRODUCTS)} products, {len(IMAGE_PRICES) * len(QUALITY_LEVELS)} image prices, {video_rows} video prices.")


if __name__ == "__main__":
    main()
