#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import json
import math
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DATA_DIR = Path(os.getenv("AI_CANVAS_DATA_DIR", APP_DIR / "data")).resolve()
ASSET_DIR = DATA_DIR / "assets"
RUN_DIR = DATA_DIR / "runs"
# 渠道地址只从环境变量读取（GRSAI_BASE_URL / NANO_BANANA_BASE_URL / FAST_BANANA_BASE_URL），
# 代码默认值为空，不硬编码任何渠道域名。
DEFAULT_BASE_URL = os.getenv("GRSAI_BASE_URL", "")
DEFAULT_MODEL = os.getenv("GRSAI_MODEL", "gpt-image-2")
DEFAULT_BANANA_BASE_URL = os.getenv("NANO_BANANA_BASE_URL", os.getenv("BANANA_BASE_URL", ""))
DEFAULT_BANANA_MODEL = os.getenv("NANO_BANANA_MODEL", os.getenv("BANANA_MODEL", "nano-banana-2"))
DEFAULT_FAST_BANANA_BASE_URL = os.getenv("FAST_BANANA_BASE_URL", "")
DEFAULT_FAST_BANANA_MODEL = os.getenv("FAST_BANANA_MODEL", "nano-banana-2")
DEFAULT_TOAPIS_BASE_URL = os.getenv("TOAPIS_BASE_URL", "https://toapis.com")
DEFAULT_TOAPIS_MODEL = os.getenv("TOAPIS_MODEL", "gpt-image-2")
DEFAULT_TOAPIS_PROXY_URL = os.getenv("TOAPIS_PROXY_URL", "").strip()
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_POLL_INTERVAL_SECONDS = 4
DEFAULT_BANANA_WAIT_SECONDS = max(DEFAULT_TIMEOUT_SECONDS, int(os.getenv("NANO_BANANA_WAIT_SECONDS", "1200")))
TOAPIS_IMAGE_RETRY_ATTEMPTS = max(1, int(os.getenv("TOAPIS_IMAGE_RETRY_ATTEMPTS", "3")))
TOAPIS_IMAGE_RETRY_DELAY_SECONDS = max(1, int(os.getenv("TOAPIS_IMAGE_RETRY_DELAY_SECONDS", "5")))
TOAPIS_UPLOAD_MAX_BYTES = max(1, int(os.getenv("TOAPIS_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024))))

DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.+/]+);base64,(?P<data>.+)$", re.DOTALL)


def sanitize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return base


def sanitize_model(model: str) -> str:
    value = (model or "").strip()
    return value or "gpt-image-2"


DEFAULT_BASE_URL = sanitize_base_url(DEFAULT_BASE_URL)
DEFAULT_MODEL = sanitize_model(DEFAULT_MODEL)
DEFAULT_BANANA_BASE_URL = sanitize_base_url(DEFAULT_BANANA_BASE_URL)
DEFAULT_BANANA_MODEL = sanitize_model(DEFAULT_BANANA_MODEL)
DEFAULT_FAST_BANANA_BASE_URL = sanitize_base_url(DEFAULT_FAST_BANANA_BASE_URL)
DEFAULT_FAST_BANANA_MODEL = sanitize_model(DEFAULT_FAST_BANANA_MODEL)
DEFAULT_TOAPIS_BASE_URL = sanitize_base_url(DEFAULT_TOAPIS_BASE_URL)
DEFAULT_TOAPIS_MODEL = sanitize_model(DEFAULT_TOAPIS_MODEL)


PROVIDER_LABELS = {
    "gpt": "GPT Image 2",
    "banana": "Nano Banana",
    "banana_fast": "Nano Banana 快速渠道",
    "toapis": "ToAPIs 中转",
}

SUPPORTED_IMAGE_MODELS = (
    "gpt-image-2",
    "nano-banana-2",
    "nano-banana-fast",
    "nano-banana-pro",
    "grok-video-1.5",
    "seedance-2-fast",
    "seedance-2",
    "MiniMax-H3",
)

FAST_BANANA_ASPECT_RATIOS = (
    "1:1",
    "3:2",
    "2:3",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
    "1:8",
    "8:1",
    "1:4",
    "4:1",
)


def sanitize_provider(provider: str) -> str:
    value = (provider or "").strip().lower()
    if value in {"banana_fast", "banana-fast", "fast-banana", "fast_banana"}:
        return "banana_fast"
    if value in {"banana", "nano", "nano-banana", "nano_banana", "nanobanana"}:
        return "banana"
    if value in {"toapis", "to_api", "to-api"}:
        return "toapis"
    return "gpt"


def is_banana_provider(provider: str) -> bool:
    return sanitize_provider(provider) in {"banana", "banana_fast"}


def fast_banana_upstream_model(model: str) -> str:
    aliases = {
        "nano-banana-2": "gemini-3.1-flash-image-preview",
        "nano-banana-pro": "gemini-3-pro-image-preview",
    }
    return aliases.get(sanitize_model(model), sanitize_model(model))


def grsai_upstream_model(model: str) -> str:
    """Map logical model names to the pdh relay's actual model ids.

    pdh (new-api) exposes gpt-image-2-2k / gpt-image-2-4k, not bare gpt-image-2.
    Keep the product-facing name stable and translate at request time.
    """
    value = sanitize_model(model)
    mapping = {
        "gpt-image-2": "gpt-image-2-2k",
    }
    return mapping.get(value, value)


def toapis_http_client() -> requests.Session:
    """创建仅供 ToAPIs 使用的 HTTP 客户端，可选专用出站代理。"""
    client = requests.Session()
    if DEFAULT_TOAPIS_PROXY_URL:
        client.proxies.update({"http": DEFAULT_TOAPIS_PROXY_URL, "https": DEFAULT_TOAPIS_PROXY_URL})
    return client


def toapis_image_model(model: str) -> str:
    """Map product-facing model names to toapis model ids."""
    value = sanitize_model(model)
    mapping = {
        "gpt-image-2": "gpt-image-2",
        "nano-banana-2": "gemini-3.1-flash-image-preview",
        "nano-banana-pro": "gemini-3-pro-image-preview",
        "nano-banana-fast": "gemini-3.1-flash-image-preview",
    }
    return mapping.get(value, value)


class GenerateImage(BaseModel):
    id: str = ""
    name: str = ""
    role: str = "reference"
    url: str = ""
    data_url: str = Field(default="", alias="dataUrl")


class GenerateRequest(BaseModel):
    provider: str = "gpt"
    prompt: str = ""
    mode: str = "standard"
    model: str = DEFAULT_MODEL
    aspect_ratio: str = Field(default="auto", alias="aspectRatio")
    image_size: str = Field(default="1K", alias="imageSize")
    negative_prompt: str = Field(default="", alias="negativePrompt")
    count: int = 1
    images: list[GenerateImage] = Field(default_factory=list)
    requested_size: str = Field(default="", alias="requestedSize")
    duration: int = Field(default=5, alias="duration")
    video_quality: str = Field(default="720p", alias="videoQuality")


class OpenAIImageGenerationRequest(BaseModel):
    model: str = ""
    prompt: str = ""
    n: int = 1
    quality: str = "low"
    size: str = "1024x1024"
    response_format: str = "url"
    output_format: str = "png"


class ConfigureRequest(BaseModel):
    api_key: str = Field(default="", alias="apiKey")
    base_url: str = Field(default="", alias="baseUrl")
    model: str = ""
    provider: str = "gpt"


RUNTIME_CONFIG: dict[str, str] = {"apiKey": "", "baseUrl": "", "model": ""}


app = FastAPI(title="AI Render Canvas", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"^http://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})(?::\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
ASSET_DIR.mkdir(parents=True, exist_ok=True)
RUN_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")


def safe_name(value: str, fallback: str = "image") -> str:
    name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE).strip("-._")
    return name[:80] or fallback


def ext_for_mime(mime: str) -> str:
    if mime == "image/jpeg":
        return ".jpg"
    if mime == "image/webp":
        return ".webp"
    return mimetypes.guess_extension(mime) or ".png"


def data_url_to_bytes(data_url: str) -> tuple[bytes, str]:
    match = DATA_URL_RE.match(data_url)
    if not match:
        raise ValueError("Not a base64 image data URL.")
    mime = match.group("mime")
    if not mime.startswith("image/"):
        raise ValueError("Only image data URLs are supported.")
    return base64.b64decode(match.group("data")), mime


def local_url_to_path(url: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    if not path.startswith("/data/"):
        raise ValueError("Only local /data images can be reused by path.")
    target = (DATA_DIR.parent / path.lstrip("/")).resolve()
    target.relative_to(DATA_DIR)
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def file_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    raw = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"


def normalized_api_base(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith(("/v1", "/api/v3", "/api/plan/v3")):
        return base
    return f"{base}/v1"


def draw_api_base(base_url: str) -> str:
    return (base_url or DEFAULT_BANANA_BASE_URL).strip().rstrip("/")


def quality_for_size(image_size: str) -> str:
    value = (image_size or "1K").strip().lower()
    if value in {"4k", "high"}:
        return "high"
    if value in {"2k", "medium"}:
        return "medium"
    return "low"


def pricing_quality(image_size: str) -> str:
    """Map the frontend imageSize/imageQuality value to a price-table quality.

    The frontend sends Gemini-style sizes ("1K"/"2K"/"4K") in imageSize, but the
    price table keys on quality levels (auto/low/medium/high/standard/hd). Normalize
    so billing always finds a row instead of returning 503 for "1K".
    """
    value = (image_size or "standard").strip().lower()
    normalized = {
        "1k": "standard",
        "2k": "hd",
        "4k": "high",
    }
    if value in normalized:
        return normalized[value]
    return value if value in {"auto", "low", "medium", "high", "standard", "hd"} else "standard"


def size_for_aspect(aspect_ratio: str) -> str:
    options = {
        "1:1": "1024x1024",
        "16:9": "1536x864",
        "4:3": "1024x768",
        "3:4": "768x1024",
    }
    return options.get((aspect_ratio or "").strip(), "1024x1024")


def normalize_requested_size(size: str) -> str:
    value = (size or "").strip().lower()
    if value in {"", "auto"}:
        return ""
    if not re.fullmatch(r"\d{2,5}x\d{2,5}", value):
        raise ValueError("Image size must use WIDTHxHEIGHT, for example 1024x1024.")
    width, height = (int(part) for part in value.split("x", 1))
    if width <= 0 or height <= 0:
        raise ValueError("Image width and height must be positive.")
    return f"{width}x{height}"


def aspect_ratio_for_size(size: str) -> str:
    normalized = normalize_requested_size(size)
    if not normalized:
        return "auto"
    width, height = (int(part) for part in normalized.split("x", 1))
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def fast_banana_aspect_ratio_for_size(size: str) -> str:
    normalized = normalize_requested_size(size)
    if not normalized:
        return "auto"
    width, height = (int(part) for part in normalized.split("x", 1))
    target = width / height
    return min(
        FAST_BANANA_ASPECT_RATIOS,
        key=lambda value: abs((int(value.split(":", 1)[0]) / int(value.split(":", 1)[1])) - target),
    )


def provider_for_model(model: str) -> str:
    value = (model or "").lower()
    if "banana" in value:
        return "banana"
    return "gpt"


def is_video_model(model: str) -> bool:
    value = (model or "").lower()
    return any(key in value for key in ("grok-video", "seedance", "minimax", "veo", "kling", "vidu", "sora"))


def supported_model(model: str) -> str:
    value = sanitize_model(model)
    if value not in SUPPORTED_IMAGE_MODELS:
        raise ValueError(f"Unsupported image model: {value}")
    return value


def openai_generate_request(model: str, prompt: str, n: int, quality: str, size: str, images: list[GenerateImage] | None = None, provider: str | None = None) -> GenerateRequest:
    requested_size = normalize_requested_size(size)
    selected_provider = sanitize_provider(provider) if provider else provider_for_model(model)
    selected_model = supported_model(model or current_model(selected_provider))
    aspect_ratio = fast_banana_aspect_ratio_for_size(requested_size) if selected_provider == "banana_fast" else aspect_ratio_for_size(requested_size)
    return GenerateRequest(
        provider=selected_provider,
        prompt=prompt,
        model=selected_model,
        aspectRatio=aspect_ratio,
        imageSize=quality or "low",
        count=min(max(n, 1), 4),
        images=images or [],
        requestedSize=requested_size,
    )


def edit_model_name(model: str) -> str:
    if (model or "").startswith("grok-imagine-image"):
        return "grok-imagine-image-edit"
    return grsai_upstream_model(model) or DEFAULT_MODEL


def openai_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def response_error(response: requests.Response) -> RuntimeError:
    try:
        data: Any = response.json()
    except ValueError:
        data = response.text[:800]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return RuntimeError(f"HTTP {response.status_code}: {message}")
        message = data.get("message") or data.get("msg")
        if message:
            return RuntimeError(f"HTTP {response.status_code}: {message}")
    return RuntimeError(f"HTTP {response.status_code}: {data}")


def toapis_retryable_error(error: Any) -> bool:
    """判断 ToAPIs 是否返回可重试的临时上游拥堵错误。"""
    text = json.dumps(error, ensure_ascii=False).lower() if isinstance(error, (dict, list)) else str(error).lower()
    return any(marker in text for marker in ("system under load", "timeout_error", "rate limit", "rate_limit", "temporarily unavailable"))


def response_json_or_events(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        events: list[dict[str, Any]] = []
        for line in response.text.splitlines():
            text = line.strip()
            if not text.startswith("data:"):
                continue
            payload = text[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                value = json.loads(payload)
            except ValueError:
                continue
            if isinstance(value, dict):
                events.append(value)
        if events:
            latest = dict(events[-1])
            latest.setdefault("events", events)
            return latest
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:800]}")


def result_urls(response: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    if response.get("url"):
        urls.append(str(response["url"]))
    if response.get("b64_json"):
        urls.append(f"data:image/png;base64,{response['b64_json']}")
    for key in ("results", "data", "images", "output"):
        value = response.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                if isinstance(item, dict) and item.get("url"):
                    urls.append(str(item["url"]))
                if isinstance(item, dict) and item.get("image_url"):
                    urls.append(str(item["image_url"]))
                if isinstance(item, dict) and item.get("file_url"):
                    urls.append(str(item["file_url"]))
                if isinstance(item, dict) and item.get("uri"):
                    urls.append(str(item["uri"]))
                if isinstance(item, dict) and item.get("b64_json"):
                    urls.append(f"data:image/png;base64,{item['b64_json']}")
        if isinstance(value, dict):
            nested = result_urls(value)
            urls.extend(nested)
    return list(dict.fromkeys(urls))


def task_id_from_response(response: dict[str, Any]) -> str:
    for key in ("task_id", "taskId", "id", "request_id", "requestId", "job_id", "jobId"):
        value = response.get(key)
        if value:
            return str(value)
    for key in ("data", "result"):
        value = response.get(key)
        if isinstance(value, dict):
            nested = task_id_from_response(value)
            if nested:
                return nested
    return ""


def banana_image_data_url(input_file: dict[str, Any]) -> str:
    path = Path(input_file["file"])
    mime = input_file.get("mime") or mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def banana_image_size(image_size: str) -> str:
    value = (image_size or "1K").strip().lower()
    if value in {"4k", "high"}:
        return "4K"
    if value in {"2k", "medium"}:
        return "2K"
    return "1K"


def banana_payload(req: GenerateRequest, prompt: str, input_files: list[dict[str, Any]]) -> dict[str, Any]:
    image_urls = [banana_image_data_url(item) for item in input_files if item.get("role") != "mask"]
    payload: dict[str, Any] = {
        "model": req.model or DEFAULT_BANANA_MODEL,
        "prompt": prompt,
        "negative_prompt": req.negative_prompt.strip(),
        "imageSize": banana_image_size(req.image_size),
        "aspectRatio": req.aspect_ratio,
        "webHook": "-1",
        "urls": image_urls,
    }
    return payload


def call_banana_draw(
    req: GenerateRequest,
    prompt: str,
    input_files: list[dict[str, Any]],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    api_base = draw_api_base(base_url)
    headers = {**openai_headers(api_key), "Content-Type": "application/json"}
    response = requests.post(
        f"{api_base}/v1/draw/nano-banana",
        headers=headers,
        json=banana_payload(req, prompt, input_files),
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise response_error(response)
    data = response_json_or_events(response)

    if result_urls(data):
        return data

    task_id = task_id_from_response(data)
    if not task_id:
        return data

    deadline = time.time() + DEFAULT_BANANA_WAIT_SECONDS
    last_result: dict[str, Any] = data
    while time.time() < deadline:
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
        result_response = requests.post(
            f"{api_base}/v1/draw/result",
            headers=headers,
            json={"task_id": task_id, "taskId": task_id, "id": task_id},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if result_response.status_code >= 400:
            raise response_error(result_response)
        result_data = response_json_or_events(result_response)
        last_result = result_data
        if result_urls(result_data):
            return result_data
        status = str(result_data.get("status") or result_data.get("state") or result_data.get("message") or "")
        if terminal_status(status):
            return result_data
    return last_result


def chat_image_urls(response: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for choice in response.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else ""
        parts = content if isinstance(content, list) else [content]
        for part in parts:
            if isinstance(part, dict):
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if isinstance(image_url, str) and image_url.startswith(("data:image/", "http://", "https://")):
                    urls.append(image_url)
                part = part.get("text") or ""
            if not isinstance(part, str):
                continue
            urls.extend(match.group(0) for match in re.finditer(r"data:image/[-\w.+]+;base64,[A-Za-z0-9+/=\r\n]+", part))
            urls.extend(match.group(0).rstrip(".,") for match in re.finditer(r"https?://[^\s\)\]\"'<>]+", part))
    return list(dict.fromkeys(urls))


def call_gemini_native(
    req: GenerateRequest,
    prompt: str,
    input_files: list[dict[str, Any]],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Call Gemini native generateContent API for nano-banana-2.

    Tries x-goog-api-key first, falls back to Authorization Bearer if 401.
    """
    api_base = sanitize_base_url(base_url)
    model_id = req.model or "nano-banana-2"
    url = f"{api_base}/v1beta/models/{model_id}:generateContent"

    parts: list[dict[str, Any]] = [{"text": prompt}]
    for item in input_files:
        if item.get("role") == "mask":
            continue
        path = Path(item["file"])
        mime = item.get("mime") or mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        parts.append({
            "inlineData": {
                "mimeType": mime,
                "data": data,
            }
        })

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": parts,
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"]
        },
    }

    # Try x-goog-api-key first (standard Gemini auth)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_BANANA_WAIT_SECONDS)

    # If 401, retry with Bearer token (relay-specific auth)
    if response.status_code == 401:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_BANANA_WAIT_SECONDS)

    if response.status_code >= 400:
        raise response_error(response)

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:800]}") from exc

    urls: list[str] = []
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            # Check for inlineData (Base64)
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data:
                image_base64 = inline_data.get("data")
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type", "image/png")
                if image_base64:
                    urls.append(f"data:{mime_type};base64,{image_base64}")
                continue

            # Check for fileData (URL)
            file_data = part.get("fileData") or part.get("file_data")
            if file_data:
                file_uri = file_data.get("fileUri") or file_data.get("file_uri")
                if file_uri and file_uri.startswith(("http://", "https://")):
                    urls.append(file_uri)

    if not urls:
        raise RuntimeError("Gemini native API returned no image data.")

    return {
        "id": data.get("id", ""),
        "model": model_id,
        "status": "succeeded",
        "data": [{"url": url} for url in urls],
    }


def toapis_upload_image(api_base: str, api_key: str, path: Path, mime: str, client: requests.Session) -> str:
    """Upload a local image to toapis and return its public URL.

    ToAPIs 上传上限为 10MB，超限参考图在上传前自动压缩（重编码为 JPEG）。
    """
    compressed = compress_upload_image(path, mime)
    if compressed is None:
        with path.open("rb") as handle:
            response = client.post(
                f"{api_base}/v1/uploads/images",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (path.name, handle, mime or "image/png")},
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
    else:
        buffer, filename, new_mime = compressed
        buffer.seek(0)  # BytesIO 保存后游标在末尾，直接上传会读到空文件。
        response = client.post(
            f"{api_base}/v1/uploads/images",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (filename, buffer, new_mime)},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    if response.status_code >= 400:
        raise response_error(response)
    data = response.json()
    url = (data.get("data") or {}).get("url") or data.get("url")
    if not url:
        raise RuntimeError("toapis upload returned no image URL.")
    return str(url)


def compress_upload_image(path: Path, mime: str) -> tuple[io.BytesIO, str, str] | None:
    """Return (bytes, filename, mime) when the image must be compressed, else None.

    仅在文件超过 ToAPIs 上传上限时触发；用 Pillow 重编码为 JPEG，
    先缩放到最长边不超过 2048px，再按需降质量，确保体积落回上限内。
    """
    if path.stat().st_size <= TOAPIS_UPLOAD_MAX_BYTES:
        return None
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("参考图超过 10MB 且服务器缺少压缩组件，请先压缩图片再上传。")
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:
        raise RuntimeError(f"参考图无法读取：{exc}") from exc
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    max_side = 2048
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    for quality in (88, 78, 68, 55):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= TOAPIS_UPLOAD_MAX_BYTES:
            return buffer, "upload.jpg", "image/jpeg"
    raise RuntimeError("参考图压缩后仍超过 10MB，请先缩小图片再上传。")


def call_toapis(
    req: GenerateRequest,
    prompt: str,
    input_files: list[dict[str, Any]],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Call toapis async image generation (POST task + GET poll)."""
    api_base = sanitize_base_url(base_url)
    model = toapis_image_model(req.model or "gpt-image-2")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client = toapis_http_client()

    # Build payload. toapis accepts http(s) URLs only for image inputs; upload local files first.
    image_urls: list[str] = []
    for item in input_files:
        if item.get("role") == "mask":
            continue
        path = Path(item["file"])
        mime = item.get("mime") or mimetypes.guess_type(path.name)[0] or "image/png"
        image_urls.append(toapis_upload_image(api_base, api_key, path, mime, client))

    metadata: dict[str, Any] = {}
    size = (req.image_size or "1K").strip().upper()
    if size in {"1K", "2K", "4K"}:
        metadata["resolution"] = size
    ratio = req.aspect_ratio if req.aspect_ratio and req.aspect_ratio != "auto" else "1:1"
    orientation = "landscape" if ratio.split(":")[0] > ratio.split(":")[1] else ("portrait" if ratio.split(":")[0] < ratio.split(":")[1] else "")
    if orientation:
        metadata["orientation"] = orientation

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": ratio,
        "n": min(max(req.count, 1), 4),
        "metadata": metadata,
    }
    if image_urls:
        payload["image_urls"] = image_urls

    last_error = ""
    for attempt in range(1, TOAPIS_IMAGE_RETRY_ATTEMPTS + 1):
        create_response = client.post(
            f"{api_base}/v1/images/generations",
            headers=headers,
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if create_response.status_code >= 400:
            raise response_error(create_response)
        created = create_response.json()
        task_id = created.get("id") or task_id_from_response(created)
        if not task_id:
            raise RuntimeError("toapis returned no image task id.")

        deadline = time.time() + DEFAULT_BANANA_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
            poll_response = client.get(
                f"{api_base}/v1/images/generations/{task_id}",
                headers=headers,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            if poll_response.status_code >= 400:
                raise response_error(poll_response)
            result_data = poll_response.json()
            status = str(result_data.get("status") or "").lower()
            if status == "completed":
                urls: list[str] = []
                result = result_data.get("result") or {}
                for item in result.get("data") or []:
                    url = item.get("url") if isinstance(item, dict) else None
                    if url:
                        urls.append(str(url))
                if not urls:
                    urls = result_urls(result_data)
                if urls:
                    return {
                        "id": task_id,
                        "model": model,
                        "status": "succeeded",
                        "data": [{"url": url} for url in urls],
                    }
                last_error = "toapis image task completed without an image URL."
                break
            if status in {"failed", "error", "cancelled", "canceled"}:
                error = result_data.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                last_error = f"toapis image task failed: {message or status}"
                if not toapis_retryable_error(error):
                    raise RuntimeError(last_error)
                break
        else:
            last_error = "toapis image task timed out."

        if attempt < TOAPIS_IMAGE_RETRY_ATTEMPTS:
            time.sleep(TOAPIS_IMAGE_RETRY_DELAY_SECONDS * attempt)
    raise RuntimeError(f"{last_error} (retried {TOAPIS_IMAGE_RETRY_ATTEMPTS} times)")


def toapis_video_model(model: str) -> str:
    """Map product-facing video model names to toapis model ids."""
    value = sanitize_model(model)
    mapping = {
        "grok-video-1.5": "grok-video-1.5",
        "seedance-2-fast": "seedance-2-fast",
        "seedance-2": "seedance-2",
        "MiniMax-H3": "MiniMax-H3",
        "minimax-h3": "MiniMax-H3",
    }
    return mapping.get(value, value)


def toapis_video_aspect_ratio(ratio: str) -> str:
    value = (ratio or "").strip()
    if value in {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}:
        return value
    return "16:9"


def call_toapis_video(
    req: GenerateRequest,
    prompt: str,
    input_files: list[dict[str, Any]],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Call toapis async video generation (POST task + GET poll)."""
    api_base = sanitize_base_url(base_url)
    model = toapis_video_model(req.model or "grok-video-1.5")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client = toapis_http_client()

    duration = max(1, min(int(req.duration or 5), 15))
    quality = (req.video_quality or "720p").strip().lower()
    aspect_ratio = toapis_video_aspect_ratio(req.aspect_ratio)

    # Build payload per model family. grok-video requires exactly 1 image (image-to-video).
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
    }

    image_urls: list[str] = []
    for item in input_files:
        if item.get("role") == "mask":
            continue
        path = Path(item["file"])
        mime = item.get("mime") or mimetypes.guess_type(path.name)[0] or "image/png"
        image_urls.append(toapis_upload_image(api_base, api_key, path, mime, client))

    lower_model = model.lower()
    if "grok-video" in lower_model:
        # grok-video-1.5: exactly 1 first-frame image; resolution 480p/720p.
        if not image_urls:
            raise RuntimeError("grok-video-1.5 需要一张首帧图作为图生视频输入。")
        payload["image"] = image_urls[0]
        payload["resolution"] = quality if quality in {"480p", "720p"} else "720p"
    elif "seedance" in lower_model:
        # seedance-2 / seedance-2-fast: image_with_roles, generate_audio.
        payload["resolution"] = quality if quality in {"480p", "720p", "1080p"} else "720p"
        payload["generate_audio"] = True
        if image_urls:
            payload["image_with_roles"] = [
                {"url": url, "role": "first_frame" if index == 0 else "reference_image"}
                for index, url in enumerate(image_urls[:9])
            ]
    else:
        # MiniMax-H3: image_urls compat mode; resolution 2K/768p. 默认 2K（与价格表 2K 档一致）。
        payload["resolution"] = "2K" if quality in {"2k", "high", "1080p", "720", "720p"} else "768p"
        if image_urls:
            payload["image_urls"] = image_urls[:9]

    create_response = client.post(
        f"{api_base}/v1/videos/generations",
        headers=headers,
        json=payload,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if create_response.status_code >= 400:
        raise response_error(create_response)
    created = create_response.json()
    task_id = created.get("id") or task_id_from_response(created)
    if not task_id:
        raise RuntimeError("toapis returned no video task id.")

    deadline = time.time() + DEFAULT_BANANA_WAIT_SECONDS
    last_data: dict[str, Any] = created
    while time.time() < deadline:
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
        poll_response = client.get(
            f"{api_base}/v1/videos/generations/{task_id}",
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if poll_response.status_code >= 400:
            raise response_error(poll_response)
        last_data = poll_response.json()
        status = str(last_data.get("status") or "")
        if status == "completed":
            urls: list[str] = []
            result = last_data.get("result") or {}
            for item in result.get("data") or []:
                url = item.get("url") if isinstance(item, dict) else None
                if url:
                    urls.append(str(url))
            if not urls:
                urls = result_urls(last_data)
            if urls:
                return {
                    "id": task_id,
                    "model": model,
                    "status": "succeeded",
                    "data": [{"url": url} for url in urls],
                }
        if status in {"failed", "error", "cancelled", "canceled"}:
            error = last_data.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"toapis video task failed: {message or status}")
    raise RuntimeError("toapis video task timed out.")


def call_fast_banana_chat(
    req: GenerateRequest,
    prompt: str,
    input_files: list[dict[str, Any]],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for item in input_files:
        if item.get("role") == "mask":
            continue
        content.append({"type": "image_url", "image_url": {"url": banana_image_data_url(item)}})
    image_config: dict[str, str] = {"image_size": banana_image_size(req.image_size)}
    if req.aspect_ratio and req.aspect_ratio != "auto":
        image_config["aspect_ratio"] = req.aspect_ratio
    response = requests.post(
        f"{normalized_api_base(base_url)}/chat/completions",
        headers={**openai_headers(api_key), "Content-Type": "application/json"},
        json={
            "model": fast_banana_upstream_model(req.model),
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "extra_body": {"google": {"image_config": image_config}},
        },
        timeout=DEFAULT_BANANA_WAIT_SECONDS,
    )
    if response.status_code >= 400:
        raise response_error(response)
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:800]}") from exc
    urls = chat_image_urls(data)
    if not urls:
        raise RuntimeError("Fast Banana returned no image data.")
    return {
        "id": data.get("id", ""),
        "model": data.get("model") or fast_banana_upstream_model(req.model),
        "status": "succeeded",
        "data": [{"url": url} for url in urls],
    }


def terminal_status(status: str) -> bool:
    return status.lower() in {"succeeded", "success", "failed", "error", "cancelled", "canceled"}


def mode_instruction(mode: str) -> str:
    options = {
        "standard": "Follow the user prompt directly. If images are provided, edit or generate from the main image while preserving unmentioned content and identity.",
        "structure": "Structure lock: preserve camera angle, object positions, proportions, layout, and depth relationships unless the user explicitly requests a change.",
        "reference": "Reference fusion: use selected images as references by role; do not randomly merge unrelated details or replace the main subject.",
        "polish": "Polish mode: do not redesign the image; improve realism, material fidelity, lighting, shadows, reflections, and photographic finish.",
        "mask": "Local edit: treat visible marks or selected image context as the edit target; keep unmentioned areas stable.",
    }
    return options.get(mode, options["standard"])


def image_role_instruction(index: int, role: str) -> str:
    role_options = {
        "main": "MAIN IMAGE. Treat this as the base image and primary subject to edit. Preserve identity, pose/composition, camera, and unmentioned details unless the user explicitly requests a change.",
        "structure": "STRUCTURE REFERENCE. Use only its spatial organization, geometry, proportions, camera logic, and construction relationships. Do not copy its materials or style unless requested.",
        "material": "MATERIAL REFERENCE. Use its material palette, texture scale, surface finish, reflections, and physical realism. Do not replace the main image layout.",
        "lighting": "LIGHTING REFERENCE. Use its light direction, softness, contrast, exposure, shadow character, and atmosphere. Do not copy unrelated objects.",
        "style": "STYLE REFERENCE. Use its visual language, color treatment, rendering finish, and design mood. Keep the main image composition recognizable.",
        "content": "CONTENT/SUBJECT REFERENCE. Use relevant objects, people, products, decor, or subject details only where they fit the main image. Do not import the reference background or camera unless requested.",
        "reference": "GENERAL REFERENCE. Use only details relevant to the user prompt while keeping the main image dominant.",
    }
    instruction = role_options.get(role, role_options["reference"])
    return f"Image {index}: {instruction}"


def build_prompt(req: GenerateRequest, provider: str = "gpt") -> str:
    prompt = req.prompt.strip() or "Generate a clean professional image."
    if is_banana_provider(provider):
        lines = [
            "The user prompt is the source of truth. Follow it literally and directly.",
            "If the user asks for a new scene, subject, background, composition, or style, make that change even when reference images are present.",
            "If images are provided, Image 1 is the primary reference. Preserve its identity, composition, camera, background, or details only when the user explicitly asks to preserve them.",
            "User prompt:",
            prompt,
        ]
        if req.images:
            lines.append("Image inputs:")
            for index, image in enumerate(req.images, start=1):
                role = "main" if index == 1 else image.role
                label = "base/main image" if role == "main" else f"reference image ({reference_role_plain(role)})"
                lines.append(f"Image {index}: {label}.")
        if req.negative_prompt.strip():
            lines.extend(["Avoid:", req.negative_prompt.strip()])
        lines.append("Return only the final edited/generated image. No labels, watermarks, UI, or annotation marks unless requested.")
        return "\n\n".join(lines)

    lines = [mode_instruction(req.mode), "User prompt:", prompt]
    if req.images:
        lines.extend(["Image order and responsibilities:"])
        prompt_images = [image for image in req.images if image.role != "mask"]
        for index, image in enumerate(prompt_images, start=1):
            role = "main" if index == 1 else image.role
            lines.append(image_role_instruction(index, role))
        if any(image.role == "mask" for image in req.images):
            lines.append("A mask image is supplied separately. Edit only the masked area and preserve everything outside it.")
        lines.append("Priority rule: Image 1 is always the main image. Later images are supporting references only, in the exact order listed above. Resolve conflicts in favor of Image 1 and the user prompt.")
    if req.negative_prompt.strip():
        lines.extend(["Avoid:", req.negative_prompt.strip()])
    lines.append("Return only final usable images, with no UI, labels, watermarks, or annotation marks unless requested.")
    return "\n\n".join(lines)


def reference_role_plain(role: str) -> str:
    labels = {
        "structure": "structure",
        "material": "material",
        "lighting": "lighting",
        "style": "style",
        "content": "content/subject",
        "reference": "general reference",
    }
    return labels.get(role or "reference", "general reference")


# ---- Key pool with auto-rotation -------------------------------------------
_COOLDOWN_SECONDS = int(os.getenv("KEY_COOLDOWN_SECONDS", "300"))
_KEY_POOLS: dict[str, _KeyPool] = {}
_KEY_POOL_LOCK = threading.Lock()


class _KeyPool:
    __slots__ = ("name", "keys", "cursor", "cooldowns", "stats")

    def __init__(self, name: str, csv: str) -> None:
        self.name = name
        self.keys = [k.strip() for k in csv.split(",") if k.strip()]
        self.cursor = 0
        self.cooldowns: dict[int, float] = {}  # idx → cooldown_until (monotonic)
        self.stats: list[dict[str, Any]] = [{"calls": 0, "errors": 0, "last_error": ""} for _ in self.keys]

    def pick(self) -> str:
        """Return the next available key (or best-effort if all cooling)."""
        if not self.keys:
            return ""
        now = time.monotonic()
        for _ in range(len(self.keys)):
            self.cursor = (self.cursor + 1) % len(self.keys)
            if now >= self.cooldowns.get(self.cursor, 0.0):
                self.stats[self.cursor]["calls"] += 1
                return self.keys[self.cursor]
        # All keys cooling – pick the one that recovers soonest
        idx = min(range(len(self.keys)), key=lambda i: self.cooldowns.get(i, 0.0))
        self.stats[idx]["calls"] += 1
        return self.keys[idx]

    def mark_error(self, key_str: str, is_rate_limit: bool) -> None:
        """If rate-limit, put the key in cooldown. Otherwise just count."""
        if not self.keys:
            return
        for i, k in enumerate(self.keys):
            if k == key_str:
                self.stats[i]["errors"] += 1
                self.stats[i]["last_error"] = "rate_limit" if is_rate_limit else "other"
                if is_rate_limit:
                    self.cooldowns[i] = time.monotonic() + _COOLDOWN_SECONDS
                return

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "name": self.name,
            "total_keys": len(self.keys),
            "active_keys": sum(1 for i in range(len(self.keys)) if now >= self.cooldowns.get(i, 0.0)),
            "keys": [
                {
                    "index": i,
                    "prefix": k[:12] + "…" if len(k) > 12 else k,
                    "calls": self.stats[i]["calls"],
                    "errors": self.stats[i]["errors"],
                    "cooldown_remaining": max(0, int(self.cooldowns.get(i, 0.0) - now)),
                    "last_error": self.stats[i]["last_error"],
                }
                for i, k in enumerate(self.keys)
            ],
        }


def _env_key(provider: str, *env_names: str) -> str:
    """Read a channel's key string from env (may be comma-separated for pools)."""
    for name in env_names:
        v = os.getenv(name, "")
        if v.strip():
            return v.strip()
    return ""


def _get_pool(provider: str) -> _KeyPool:
    with _KEY_POOL_LOCK:
        if provider not in _KEY_POOLS:
            if provider == "banana_fast":
                raw = _env_key(provider, "FAST_BANANA_API_KEY") or RUNTIME_CONFIG.get("fastBananaApiKey", "")
            elif provider == "banana":
                raw = _env_key(provider, "NANO_BANANA_API_KEY", "BANANA_API_KEY", "GRSAI_BANANA_API_KEY") or RUNTIME_CONFIG.get("bananaApiKey", "")
            elif provider == "toapis":
                raw = _env_key(provider, "TOAPIS_API_KEY") or RUNTIME_CONFIG.get("toapisApiKey", "")
            else:
                raw = _env_key(provider, "GRSAI_API_KEY", "GRSAI_KEY") or RUNTIME_CONFIG.get("apiKey", "")
            _KEY_POOLS[provider] = _KeyPool(provider, raw)
        return _KEY_POOLS[provider]


def current_api_key(provider: str = "gpt") -> str:
    selected = sanitize_provider(provider)
    return _get_pool(selected).pick()


def report_key_error(provider: str, key_str: str, is_rate_limit: bool) -> None:
    """Call after an API error to mark the key (rate-limit keys enter cooldown)."""
    selected = sanitize_provider(provider)
    _get_pool(selected).mark_error(key_str, is_rate_limit)


def key_pool_status() -> dict[str, Any]:
    return {p: _get_pool(p).snapshot() for p in ("gpt", "banana", "banana_fast", "toapis")}


def current_base_url(provider: str = "gpt") -> str:
    selected = sanitize_provider(provider)
    if selected == "banana_fast":
        return sanitize_base_url(RUNTIME_CONFIG.get("fastBananaBaseUrl") or DEFAULT_FAST_BANANA_BASE_URL)
    if selected == "banana":
        return sanitize_base_url(RUNTIME_CONFIG.get("bananaBaseUrl") or DEFAULT_BANANA_BASE_URL)
    if selected == "toapis":
        return sanitize_base_url(RUNTIME_CONFIG.get("toapisBaseUrl") or DEFAULT_TOAPIS_BASE_URL)
    return sanitize_base_url(RUNTIME_CONFIG.get("baseUrl") or DEFAULT_BASE_URL)


def current_model(provider: str = "gpt") -> str:
    selected = sanitize_provider(provider)
    if selected == "banana_fast":
        return sanitize_model(RUNTIME_CONFIG.get("fastBananaModel") or DEFAULT_FAST_BANANA_MODEL)
    if selected == "banana":
        return sanitize_model(RUNTIME_CONFIG.get("bananaModel") or DEFAULT_BANANA_MODEL)
    if selected == "toapis":
        return sanitize_model(RUNTIME_CONFIG.get("toapisModel") or DEFAULT_TOAPIS_MODEL)
    return sanitize_model(RUNTIME_CONFIG.get("model") or DEFAULT_MODEL)


def call_grsai(
    req: GenerateRequest,
    prompt: str,
    input_files: list[dict[str, Any]],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    api_base = normalized_api_base(base_url)
    common = {
        "model": grsai_upstream_model(req.model or DEFAULT_MODEL),
        "prompt": prompt,
        "n": min(max(req.count, 1), 4),
        "quality": quality_for_size(req.image_size),
        "size": req.requested_size or size_for_aspect(req.aspect_ratio),
        "response_format": "url",
        "output_format": "png",
    }

    if not input_files:
        response = requests.post(
            f"{api_base}/images/generations",
            headers={**openai_headers(api_key), "Content-Type": "application/json"},
            json=common,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    else:
        field_name = "image[]" if (req.model or "").startswith("grok-imagine-image") else "image"
        edit_payload = {**common, "model": edit_model_name(req.model)}
        files = []
        handles = []
        try:
            for item in input_files:
                handle = Path(item["file"]).open("rb")
                handles.append(handle)
                upload_field = "mask" if item.get("role") == "mask" else field_name
                files.append((upload_field, (Path(item["file"]).name, handle, item.get("mime") or "image/png")))
            response = requests.post(
                f"{api_base}/images/edits",
                headers=openai_headers(api_key),
                data={key: str(value) for key, value in edit_payload.items()},
                files=files,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        finally:
            for handle in handles:
                handle.close()

    if response.status_code >= 400:
        raise response_error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:800]}") from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    providers = {
        "gpt": {
            "label": PROVIDER_LABELS["gpt"],
            "hasKey": bool(current_api_key("gpt")),
            "baseUrl": current_base_url("gpt"),
            "model": current_model("gpt"),
        },
        "banana": {
            "label": PROVIDER_LABELS["banana"],
            "hasKey": bool(current_api_key("banana")),
            "baseUrl": current_base_url("banana"),
            "model": current_model("banana"),
        },
        "banana_fast": {
            "label": PROVIDER_LABELS["banana_fast"],
            "hasKey": bool(current_api_key("banana_fast")),
            "baseUrl": current_base_url("banana_fast"),
            "model": current_model("banana_fast"),
        },
        "toapis": {
            "label": PROVIDER_LABELS["toapis"],
            "hasKey": bool(current_api_key("toapis")),
            "baseUrl": current_base_url("toapis"),
            "model": current_model("toapis"),
        },
    }
    return {
        "ok": True,
        "hasKey": any(provider["hasKey"] for provider in providers.values()),
        "baseUrl": providers["gpt"]["baseUrl"],
        "model": providers["gpt"]["model"],
        "providers": providers,
        "dataDir": str(DATA_DIR),
    }


@app.get("/v1/models")
def openai_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": model, "object": "model", "owned_by": "local-8790"} for model in SUPPORTED_IMAGE_MODELS],
    }


@app.get("/fast/v1/models")
def fast_openai_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": model, "object": "model", "owned_by": "local-8790-fast"} for model in ("nano-banana-2", "nano-banana-pro")],
    }


@app.post("/api/configure")
def configure(req: ConfigureRequest) -> dict[str, Any]:
    if os.getenv("ALLOW_RUNTIME_API_CONFIG", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=403, detail="Runtime API configuration is disabled. Use the local fixed API startup flow.")
    api_key = req.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required.")
    provider = sanitize_provider(req.provider)
    if provider == "banana_fast":
        RUNTIME_CONFIG["fastBananaApiKey"] = api_key
        if req.base_url.strip():
            RUNTIME_CONFIG["fastBananaBaseUrl"] = sanitize_base_url(req.base_url)
        if req.model.strip():
            RUNTIME_CONFIG["fastBananaModel"] = sanitize_model(req.model)
    elif provider == "banana":
        RUNTIME_CONFIG["bananaApiKey"] = api_key
        if req.base_url.strip():
            RUNTIME_CONFIG["bananaBaseUrl"] = sanitize_base_url(req.base_url)
        if req.model.strip():
            RUNTIME_CONFIG["bananaModel"] = sanitize_model(req.model)
    else:
        RUNTIME_CONFIG["apiKey"] = api_key
        if req.base_url.strip():
            RUNTIME_CONFIG["baseUrl"] = sanitize_base_url(req.base_url)
        if req.model.strip():
            RUNTIME_CONFIG["model"] = sanitize_model(req.model)
    return {
        "ok": True,
        "hasKey": True,
        "provider": provider,
        "baseUrl": current_base_url(provider),
        "model": current_model(provider),
    }


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    items = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for file in files:
        mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "image/png"
        if not mime.startswith("image/"):
            continue
        raw = await file.read()
        original_stem = Path(file.filename or "image").stem
        filename = f"{stamp}-{uuid4().hex[:8]}-{safe_name(original_stem)}{ext_for_mime(mime)}"
        target = ASSET_DIR / filename
        target.write_bytes(raw)
        items.append({"name": file.filename or filename, "url": f"/data/assets/{filename}", "mime": mime})
    return {"ok": True, "items": items}


@app.post("/api/upload-data-url")
def upload_data_url(data_url: str = Form(...), name: str = Form("clipboard.png")) -> dict[str, Any]:
    try:
        raw, mime = data_url_to_bytes(data_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}-{safe_name(Path(name).stem)}{ext_for_mime(mime)}"
    target = ASSET_DIR / filename
    target.write_bytes(raw)
    return {"ok": True, "item": {"name": name, "url": f"/data/assets/{filename}", "mime": mime}}


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    # Provider resolution. When TOAPIS_API_KEY is configured it is the active relay:
    # route every image model through toapis (unless the caller explicitly pinned a
    # non-default provider). Otherwise infer banana vs gpt by model name.
    if _env_key("toapis", "TOAPIS_API_KEY") or RUNTIME_CONFIG.get("toapisApiKey", ""):
        req.provider = "toapis"
    else:
        if not (req.provider or "").strip() or sanitize_provider(req.provider) == "gpt":
            inferred = provider_for_model(req.model or "")
            if inferred != "gpt":
                req.provider = inferred
    provider = sanitize_provider(req.provider)
    api_key = current_api_key(provider)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{PROVIDER_LABELS[provider]} API key is not configured on the server.")
    if not req.model:
        req.model = current_model(provider)

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    run_path = RUN_DIR / run_id
    input_path = run_path / "inputs"
    output_path = run_path / "outputs"
    input_path.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_inputs: list[dict[str, Any]] = []
    for index, image in enumerate(req.images, start=1):
        if image.data_url:
            raw, mime = data_url_to_bytes(image.data_url)
            suffix = ext_for_mime(mime)
            file_path = input_path / f"{index:02d}-{safe_name(image.name, 'image')}{suffix}"
            file_path.write_bytes(raw)
        elif image.url:
            file_path = local_url_to_path(image.url)
            mime = mimetypes.guess_type(file_path.name)[0] or "image/png"
        else:
            continue
        saved_inputs.append({"id": image.id, "name": image.name, "role": image.role, "file": str(file_path), "mime": mime})

    effective_prompt = build_prompt(req, provider)
    base_url = current_base_url(provider)
    api_base = draw_api_base(base_url) if provider == "banana" else normalized_api_base(base_url)
    endpoint = f"{api_base}/v1/draw/nano-banana" if provider == "banana" else f"{api_base}/images/{'edits' if saved_inputs else 'generations'}"

    request_log = {
        "runId": run_id,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "providerLabel": PROVIDER_LABELS[provider],
        "mode": req.mode,
        "model": req.model,
        "aspectRatio": req.aspect_ratio,
        "imageSize": req.image_size,
        "quality": quality_for_size(req.image_size),
        "size": req.requested_size or size_for_aspect(req.aspect_ratio),
        "count": min(max(req.count, 1), 4),
        "prompt": req.prompt,
        "negativePrompt": req.negative_prompt,
        "effectivePrompt": effective_prompt,
        "images": saved_inputs,
        "baseUrl": base_url,
        "apiBase": api_base,
        "endpoint": endpoint,
    }
    if provider == "banana":
        request_log["providerRequest"] = {
            "imageField": "urls",
            "imageCount": len([item for item in saved_inputs if item.get("role") != "mask"]),
            "imageSize": banana_image_size(req.image_size),
            "aspectRatio": req.aspect_ratio,
            "maxWaitSeconds": DEFAULT_BANANA_WAIT_SECONDS,
        }
    elif provider == "banana_fast":
        request_log["providerRequest"] = {
            "protocol": "openai-chat-multimodal",
            "upstreamModel": fast_banana_upstream_model(req.model),
            "imageSize": banana_image_size(req.image_size),
            "aspectRatio": req.aspect_ratio,
        }
    (run_path / "request.json").write_text(json.dumps(request_log, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        if provider == "toapis":
            if is_video_model(req.model or ""):
                api_response = call_toapis_video(req, effective_prompt, saved_inputs, api_key, base_url)
            else:
                api_response = call_toapis(req, effective_prompt, saved_inputs, api_key, base_url)
        elif req.model == "nano-banana-2":
            api_response = call_gemini_native(req, effective_prompt, saved_inputs, api_key, base_url)
        elif provider == "banana":
            api_response = call_banana_draw(req, effective_prompt, saved_inputs, api_key, base_url)
        elif provider == "banana_fast":
            api_response = call_fast_banana_chat(req, effective_prompt, saved_inputs, api_key, base_url)
        else:
            api_response = call_grsai(req, effective_prompt, saved_inputs, api_key, base_url)
    except Exception as exc:  # noqa: BLE001
        err_text = str(exc)
        report_key_error(provider, api_key, "429" in err_text or "rate" in err_text.lower())
        (run_path / "error.json").write_text(json.dumps({"error": err_text}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise HTTPException(status_code=502, detail=err_text) from exc
    (run_path / "response.json").write_text(json.dumps(api_response, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        remote_urls = result_urls(api_response)
        outputs = []
        errors = []
        for index, url in enumerate(remote_urls, start=1):
            if url.startswith("data:image/"):
                try:
                    raw, mime = data_url_to_bytes(url)
                    suffix = ext_for_mime(mime)
                    target = output_path / f"{run_id}-{index:02d}{suffix}"
                    target.write_bytes(raw)
                    outputs.append({"name": target.name, "url": f"/data/runs/{run_id}/outputs/{target.name}"})
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"inline image {index}: {exc}")
                continue
            parsed_suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
            if is_video_model(req.model or ""):
                suffix = parsed_suffix if parsed_suffix in {".mp4", ".webm", ".mov"} else ".mp4"
            elif parsed_suffix in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = parsed_suffix
            else:
                suffix = ".png"
            target = output_path / f"{run_id}-{index:02d}{suffix}"
            try:
                image_response = (toapis_http_client() if provider == "toapis" else requests).get(url, timeout=300)
                image_response.raise_for_status()
                target.write_bytes(image_response.content)
                outputs.append({"name": target.name, "url": f"/data/runs/{run_id}/outputs/{target.name}"})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")

        if not outputs and remote_urls:
            outputs = [{"name": f"remote-{idx + 1}", "url": url} for idx, url in enumerate(remote_urls)]

        return {
            "ok": True,
            "runId": run_id,
            "status": api_response.get("status") or ("succeeded" if outputs else "unknown"),
            "outputs": outputs,
            "remoteUrls": remote_urls,
            "errors": errors,
            "message": "generated" if outputs else "no image urls found in api response",
        }
    except Exception as exc:  # noqa: BLE001
        (run_path / "error.json").write_text(json.dumps({"error": str(exc), "stage": "save_outputs"}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def openai_image_response(result: dict[str, Any], request: Request) -> dict[str, Any]:
    public_base_url = str(request.base_url).rstrip("/")
    data = []
    for output in result.get("outputs") or []:
        url = str(output.get("url") or "")
        if not url:
            continue
        absolute_url = url if url.startswith(("http://", "https://", "data:")) else f"{public_base_url}/{url.lstrip('/')}"
        data.append({"url": absolute_url})
    if not data:
        raise HTTPException(status_code=502, detail=result.get("message") or "No image was returned by the provider.")
    return {
        "created": int(time.time()),
        "data": data,
        "runId": result.get("runId", ""),
        "status": result.get("status", "succeeded"),
    }


@app.post("/fast/v1/images/generations")
@app.post("/v1/images/generations")
def openai_image_generations(payload: OpenAIImageGenerationRequest, request: Request) -> dict[str, Any]:
    try:
        provider = "banana_fast" if request.url.path.startswith("/fast/") else None
        req = openai_generate_request(payload.model, payload.prompt, payload.n, payload.quality, payload.size, provider=provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return openai_image_response(generate(req), request)


@app.post("/fast/v1/images/edits")
@app.post("/v1/images/edits")
async def openai_image_edits(
    request: Request,
    image: list[UploadFile] = File(...),
    prompt: str = Form(""),
    model: str = Form(""),
    n: int = Form(1),
    quality: str = Form("low"),
    size: str = Form("1024x1024"),
    response_format: str = Form("url"),
    output_format: str = Form("png"),
    mask: UploadFile | None = File(None),
) -> dict[str, Any]:
    del response_format, output_format
    images: list[GenerateImage] = []
    for index, upload_file in enumerate(image, start=1):
        mime = upload_file.content_type or mimetypes.guess_type(upload_file.filename or "")[0] or "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image uploads are supported.")
        raw = await upload_file.read()
        images.append(
            GenerateImage(
                name=upload_file.filename or f"image-{index}{ext_for_mime(mime)}",
                role="main" if index == 1 else "reference",
                dataUrl=f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
            )
        )
    if mask is not None:
        mask_mime = mask.content_type or mimetypes.guess_type(mask.filename or "")[0] or "image/png"
        if not mask_mime.startswith("image/"):
            raise HTTPException(status_code=400, detail="Mask must be an image.")
        mask_raw = await mask.read()
        images.append(
            GenerateImage(
                name=mask.filename or "mask.png",
                role="mask",
                dataUrl=f"data:{mask_mime};base64,{base64.b64encode(mask_raw).decode('ascii')}",
            )
        )
    try:
        provider = "banana_fast" if request.url.path.startswith("/fast/") else None
        req = openai_generate_request(model, prompt, n, quality, size, images, provider=provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return openai_image_response(generate(req), request)


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the local AI render canvas.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8790")))
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
