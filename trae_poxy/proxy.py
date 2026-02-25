"""
@Project: AI Poxy Tools
@File: proxy.py
@Description: MITM proxy core — request interception, upstream forwarding, stream relay, and model normalization.
@Author: 颖馨瑶 (Ying Xinyao)
@Contact: admin@loserrc.com | QQ: 1129414920
@Date: 2026-02-25
@Version: v1.2.2
@Copyright: (c) 2026 Ying Xinyao. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit
from typing import Dict

import certifi

from aiohttp import ClientSession, TCPConnector, web
from aiohttp.client_exceptions import ClientPayloadError, ClientConnectionResetError

from .config import Config


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


LOGGER = logging.getLogger("trae_poxy.proxy")
PREVIEW_LIMIT = 4096
STREAM_DUMP_PATH = Path("logs") / "stream_dump.log"


def _append_stream_dump(line: str) -> None:
    STREAM_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STREAM_DUMP_PATH.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(line)


def _update_stream_meta(state: dict, text: str) -> None:
    buffer = state.get("_buffer", "") + text
    lines = buffer.splitlines(keepends=False)
    if not buffer.endswith("\n"):
        state["_buffer"] = lines.pop() if lines else buffer
    else:
        state["_buffer"] = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or not stripped.startswith("data:"):
            continue
        payload = stripped[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            if not state.get("id") and data.get("id"):
                state["id"] = data.get("id")
            if not state.get("model") and data.get("model"):
                state["model"] = data.get("model")
            if not state.get("object") and data.get("object"):
                state["object"] = data.get("object")
            usage = data.get("usage")
            if isinstance(usage, dict):
                state["usage"] = usage


def _filter_request_headers(
    headers: Dict[str, str], host_override: str, preserve_host: bool
) -> Dict[str, str]:
    filtered = {}
    auth_headers = []
    for key, value in headers.items():
        if key.lower() in HOP_BY_HOP:
            continue
        if key.lower() == "host":
            continue
        filtered[key] = value
        # Track authentication headers for logging
        if key.lower() in ("authorization", "x-api-key", "api-key", "x-auth-token"):
            auth_headers.append(key)
    if preserve_host:
        original_host = headers.get("Host")
        if original_host:
            filtered["Host"] = original_host
    elif host_override:
        filtered["Host"] = host_override
    # Log forwarded auth headers (without values for security)
    if auth_headers:
        LOGGER.debug("forwarding auth headers: %s", ", ".join(auth_headers))
    return filtered


def _filter_response_headers(
    headers: Dict[str, str], drop_content_length: bool
) -> Dict[str, str]:
    filtered = {}
    for key, value in headers.items():
        if key.lower() in HOP_BY_HOP:
            continue
        if drop_content_length and key.lower() == "content-length":
            continue
        filtered[key] = value
    return filtered


def _normalize_models_payload(payload: bytes) -> bytes:
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return payload
    if not isinstance(data, dict) or "data" not in data:
        return payload
    items = data.get("data")
    if not isinstance(items, list):
        return payload
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "id": item.get("id"),
                "object": item.get("object", "model"),
                "created": item.get("created"),
                "owned_by": item.get("owned_by", "unknown"),
            }
        )
    result = {"object": "list", "data": normalized}
    return json.dumps(result, ensure_ascii=True).encode("utf-8")


def _should_normalize_models(config: Config, host_header: str | None) -> bool:
    if not config.normalize_models:
        return False
    host = _extract_host(host_header)
    return host == "api.openai.com"


def _extract_host(host_header: str | None) -> str | None:
    if not host_header:
        return None
    return host_header.split(":", 1)[0].strip().lower() or None


def _pick_upstream(config: Config, host_header: str | None) -> str:
    host = _extract_host(host_header)
    if host and host in config.upstream_map:
        return config.upstream_map[host]
    return config.default_upstream


def _upstream_host(upstream_base: str) -> str:
    parts = urlsplit(upstream_base)
    return parts.hostname or ""


def _rewrite_path(config: Config, host_header: str | None, path: str) -> str:
    host = _extract_host(host_header)
    if not host:
        return path
    rules = config.path_rewrite_map.get(host) if config.path_rewrite_map else None
    if not rules:
        return path
    for src, dst in rules:
        if path.startswith(src):
            return f"{dst}{path[len(src):]}"
    return path


def _build_upstream_ssl(config: Config) -> ssl.SSLContext | bool:
    if not config.verify_upstream_ssl:
        LOGGER.info("upstream SSL verification disabled")
        return False

    cafile = (
        config.upstream_ca_bundle
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
    )
    cafile_path: Path | None = None

    # Try user-specified CA bundle first
    if cafile:
        cafile_path = Path(cafile).expanduser()
        if not cafile_path.is_absolute():
            cafile_path = (Path.cwd() / cafile_path).resolve()
        if not cafile_path.exists():
            LOGGER.warning(
                "upstream CA bundle not found: %s, falling back to certifi bundle",
                cafile_path,
            )
            cafile_path = None

    # Try certifi bundle
    if cafile_path is None:
        try:
            certifi_path = Path(certifi.where())
            if certifi_path.exists():
                cafile_path = certifi_path
                LOGGER.debug("using certifi CA bundle: %s", cafile_path)
            else:
                LOGGER.warning("certifi CA bundle missing: %s", certifi_path)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("failed to locate certifi CA bundle: %s", exc)

    # Try creating SSL context with specified CA bundle
    if cafile_path:
        try:
            ctx = ssl.create_default_context(cafile=str(cafile_path))
            LOGGER.info("SSL context created with CA bundle: %s", cafile_path)
            return ctx
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("failed to create SSL context with %s: %s", cafile_path, exc)

    # Fallback: try system default CA bundle
    try:
        ctx = ssl.create_default_context()
        LOGGER.info("SSL context created with system default CA bundle")
        return ctx
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("failed to create default SSL context: %s", exc)
        # Last resort: disable verification (log warning)
        LOGGER.warning("falling back to unverified SSL connection - this is insecure!")
        return False


def _extract_prompt_preview(payload: bytes, limit: int = 256) -> tuple[str | None, str | None]:
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(data, dict):
        return None, None
    model = data.get("model")
    messages = data.get("messages")
    prompt = None
    if isinstance(messages, list):
        for item in reversed(messages):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                prompt = content
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                prompt = "".join(parts)
            break
    if prompt is None and isinstance(data.get("prompt"), str):
        prompt = data.get("prompt")
    if not prompt:
        return model, None
    prompt = prompt.replace("\r", " ").replace("\n", " ").strip()
    if len(prompt) > limit:
        prompt = f"{prompt[:limit]}…"
    return model, prompt


async def _handle(request: web.Request) -> web.StreamResponse:
    config: Config = request.app["config"]
    session: ClientSession = request.app["session"]

    host_header = request.headers.get("Host")
    upstream_base = _pick_upstream(config, host_header)
    rewritten_path = _rewrite_path(config, host_header, request.rel_url.path)
    upstream_url = f"{upstream_base}{rewritten_path}"
    if request.rel_url.query_string:
        upstream_url = f"{upstream_url}?{request.rel_url.query_string}"
    data = await request.read() if request.can_read_body else None
    headers = _filter_request_headers(
        request.headers, _upstream_host(upstream_base), config.preserve_host
    )
    start = time.perf_counter()
    body_size = len(data) if data is not None else 0
    LOGGER.info(
        "incoming method=%s host=%s path=%s size=%s upstream=%s",
        request.method,
        host_header,
        request.rel_url,
        body_size,
        upstream_url,
    )
    if rewritten_path != request.rel_url.path:
        LOGGER.info(
            "rewrite path=%s -> %s",
            request.rel_url.path,
            rewritten_path,
        )
    if config.log_request_body and data:
        req_model, prompt_preview = _extract_prompt_preview(data)
        if prompt_preview:
            LOGGER.info(
                "request summary type=request time=%s host=%s path=%s model=%s prompt=%s",
                time.strftime("%Y-%m-%d %H:%M:%S"),
                host_header,
                request.rel_url,
                req_model,
                prompt_preview,
            )

    try:
        async with session.request(
            request.method,
            upstream_url,
            headers=headers,
            data=data,
            allow_redirects=False,
        ) as resp:
            should_normalize = _should_normalize_models(config, host_header)
            if should_normalize and request.rel_url.path == "/v1/models":
                resp_body = await resp.read()
                resp_body = _normalize_models_payload(resp_body)
                stream = web.StreamResponse(
                    status=resp.status,
                    headers=_filter_response_headers(
                        resp.headers, drop_content_length=True
                    ),
                )
                await stream.prepare(request)
                await stream.write(resp_body)
                await stream.write_eof()
                duration_ms = (time.perf_counter() - start) * 1000
                LOGGER.info(
                    "forwarded status=%s bytes=%s duration_ms=%.1f",
                    resp.status,
                    len(resp_body),
                    duration_ms,
                )
                preview = resp_body[:1024]
                if config.log_response_body:
                    _append_stream_dump(
                        f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"{request.method} {request.rel_url} {resp.status} ===\n"
                    )
                    try:
                        _append_stream_dump(resp_body.decode("utf-8", errors="replace"))
                    except Exception:  # noqa: BLE001
                        _append_stream_dump(repr(resp_body))
                    _append_stream_dump("\n=== END ===\n")
                    try:
                        data = json.loads(resp_body.decode("utf-8", errors="replace"))
                    except Exception:  # noqa: BLE001
                        data = {}
                    if isinstance(data, dict):
                        usage = data.get("usage") or {}
                        LOGGER.info(
                            "stream summary type=full time=%s id=%s model=%s object=%s "
                            "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                            time.strftime("%Y-%m-%d %H:%M:%S"),
                            data.get("id"),
                            data.get("model"),
                            data.get("object"),
                            usage.get("prompt_tokens"),
                            usage.get("completion_tokens"),
                            usage.get("total_tokens"),
                        )
                try:
                    preview_text = preview.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    preview_text = repr(preview)
                LOGGER.info("upstream body preview=%s", preview_text)
                return stream

            stream = web.StreamResponse(
                status=resp.status,
                headers=_filter_response_headers(resp.headers, drop_content_length=False),
            )
            await stream.prepare(request)
            preview = bytearray()
            total_bytes = 0
            dump_started = False
            meta: dict = {"id": None, "model": None, "object": None, "usage": None, "_buffer": ""}
            try:
                async for chunk in resp.content.iter_chunked(8192):
                    total_bytes += len(chunk)
                    if config.log_response_body and len(preview) < PREVIEW_LIMIT:
                        remaining = PREVIEW_LIMIT - len(preview)
                        preview += chunk[:remaining]
                    if config.log_response_body:
                        if not dump_started:
                            _append_stream_dump(
                                f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"{request.method} {request.rel_url} {resp.status} ===\n"
                            )
                            dump_started = True
                        try:
                            text_chunk = chunk.decode("utf-8", errors="replace")
                            _append_stream_dump(text_chunk)
                            _update_stream_meta(meta, text_chunk)
                        except Exception:  # noqa: BLE001
                            _append_stream_dump(repr(chunk))
                    try:
                        await stream.write(chunk)
                    except (ClientConnectionResetError, ConnectionResetError) as exc:
                        if total_bytes == 0:
                            LOGGER.warning("client connection closed early: %s", exc)
                        else:
                            LOGGER.info("client connection closed early: %s", exc)
                        break
            except ClientPayloadError as exc:
                # Upstream closed early; return what we already streamed.
                LOGGER.warning("upstream payload incomplete: %s", exc)
            try:
                await stream.write_eof()
            except (ClientConnectionResetError, ConnectionResetError) as exc:
                if total_bytes == 0:
                    LOGGER.warning("client connection closed before eof: %s", exc)
                else:
                    LOGGER.info("client connection closed before eof: %s", exc)
            if config.log_response_body and dump_started:
                _append_stream_dump("\n=== END ===\n")
            duration_ms = (time.perf_counter() - start) * 1000
            LOGGER.info(
                "forwarded status=%s bytes=%s duration_ms=%.1f",
                resp.status,
                total_bytes,
                duration_ms,
            )
            if config.log_response_body:
                usage = meta.get("usage") or {}
                LOGGER.info(
                    "stream summary type=chunked time=%s id=%s model=%s object=%s "
                    "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    meta.get("id"),
                    meta.get("model"),
                    meta.get("object"),
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    usage.get("total_tokens"),
                )
            if config.log_response_body and preview:
                try:
                    preview_text = preview.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    preview_text = repr(preview)
                LOGGER.info("upstream body preview=%s", preview_text)
            return stream
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        duration_ms = (time.perf_counter() - start) * 1000
        LOGGER.exception("upstream error duration_ms=%.1f", duration_ms)
        return web.Response(status=502, text=f"Upstream error: {exc}")


def create_app(config: Config) -> web.Application:
    app = web.Application()
    app["config"] = config
    app.router.add_route("*", "/{tail:.*}", _handle)

    async def _startup(app: web.Application) -> None:
        connector = TCPConnector(ssl=_build_upstream_ssl(config))
        app["session"] = ClientSession(connector=connector)

    async def _cleanup(app: web.Application) -> None:
        session = app.get("session")
        if session:
            await session.close()

    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    return app
