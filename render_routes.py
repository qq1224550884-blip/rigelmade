"""Validated image-route presets and isolated preview settlement rules."""
import math
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

FAST_MODEL = "gpt-image-2.5-fast"
FAST_RESERVE = 24
FAST_SIZES = {"1:1": (2048, 2048), "3:2": (2048, 1360), "2:3": (1360, 2048),
              "4:3": (2048, 1536), "3:4": (1536, 2048), "5:4": (2048, 1632),
              "4:5": (1632, 2048), "16:9": (2048, 1152), "9:16": (1152, 2048), "21:9": (2688, 1152)}


def validate_fast_request(req, prompt=None):
    if req.model != FAST_MODEL:
        return
    if req.image_size.lower() not in {"medium", "2k", "hd"}:
        raise HTTPException(400, "快速预览目前支持 2K；1K、4K 请选日常或 Sunburst 精修")
    if req.count != 1 or len(req.images) > 1 or any(image.role == "mask" for image in req.images):
        raise HTTPException(400, "快速预览每次支持一张输出及最多一张底图；多参考图或涂鸦请选 Sunburst 精修")
    if len((prompt if prompt is not None else req.prompt).encode("utf-8")) > 8000:
        raise HTTPException(400, "快速预览适合简短指令；当前指令过长，请选日常或 Sunburst 精修")


def fast_input(path: Path) -> Path:
    from PIL import Image
    with Image.open(path) as source:
        scale = min(1, 2048/max(source.size), math.sqrt(2_359_296/(source.width*source.height)))
        image = source.convert("RGB")
        if scale < 1:
            image = image.resize((max(1, round(source.width*scale)), max(1, round(source.height*scale))), Image.Resampling.LANCZOS)
        target = path.with_name(path.stem+"-fast-preview-"+uuid4().hex[:8]+".jpg")
        image.save(target, "JPEG", quality=88, optimize=True)
    return target


def settled_cost(response):
    billing = response.get("billing") or {}
    try:
        value = Decimal(str(billing["cost_usd"]))
        if billing.get("status") == "settled" and value.is_finite() and value > 0:
            return value
    except (KeyError, InvalidOperation, TypeError, ValueError):
        pass
    return None


def preview_credits(response, reserved):
    cost = settled_cost(response)
    if cost is None:
        raise ValueError("快速通道尚未返回已结算费用")
    # Existing pricing policy: 200 provider credits/USD, cost × 1.5, rounded up.
    return min(reserved, max(1, int((cost*300).to_integral_value(rounding=ROUND_CEILING))))
