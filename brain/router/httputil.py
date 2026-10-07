"""Stdlib async HTTP plumbing shared by all providers.

No third-party HTTP client (repo constraint: stdlib + PyYAML only). Blocking
`urllib` work runs in `asyncio.to_thread` so the brain's event loop never
blocks (ARCHITECTURE §4).

Rules:
- HTTP error statuses are RETURNED (status/body/headers), never raised —
  providers map them to PROTOCOL §10 codes via `errors.code_for_status`;
- only genuine network failures raise `NetworkError` (→ E_OFFLINE);
- headers are lower-cased and rate-limit/retry-after metadata is parsed
  (Wave 2 task 3: honor rate-limit headers);
- request/response bodies are NEVER logged here (secrets/privacy).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, AsyncIterator, Mapping
from urllib import error as urlerror
from urllib import request as urlrequest


class NetworkError(Exception):
    """Connection/DNS/timeout failure — mapped to E_OFFLINE by providers."""


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8", errors="replace"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _norm_headers(raw: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for k, v in dict(raw or {}).items():
            out[str(k).lower()] = str(v)
    except Exception:  # noqa: BLE001 — header mapping is best-effort
        pass
    return out


# Cloudflare and several providers reject urllib's default Python UA
# (Error 1010 on api.groq.com — verified live 2026-10-06).
DEFAULT_USER_AGENT = "raphael-router/1.0 (OpenAI-compatible client; local)"


def _with_ua(headers: Mapping[str, str] | None) -> dict[str, str]:
    out = dict(headers or {})
    if not any(k.lower() == "user-agent" for k in out):
        out["User-Agent"] = DEFAULT_USER_AGENT
    return out


async def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 30.0,
) -> HttpResponse:
    """Perform one HTTP request; return status/body/headers (any status)."""
    def _do() -> HttpResponse:
        req = urlrequest.Request(url, data=body, headers=_with_ua(headers), method=method)
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, _norm_headers(resp.headers), resp.read())
        except urlerror.HTTPError as e:
            # HTTP-level error: still a response (429/5xx bodies matter)
            try:
                payload = e.read() or b""
            except Exception:  # noqa: BLE001
                payload = b""
            return HttpResponse(int(e.code), _norm_headers(e.headers), payload)
        except urlerror.URLError as e:
            raise NetworkError(str(getattr(e, "reason", e))) from e
        except (TimeoutError, ConnectionError, OSError) as e:
            raise NetworkError(str(e)) from e

    return await asyncio.to_thread(_do)


async def http_stream_lines(
    url: str,
    *,
    method: str = "POST",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 30.0,
) -> AsyncIterator[bytes]:
    """Open a streaming response and yield raw lines (SSE parsing is above).

    Raise NetworkError for connection failures; HTTP error statuses raise
    NetworkError-free `StreamHttpError` carrying status + body head so the
    caller can map codes exactly like the non-streaming path.
    """
    def _open():
        req = urlrequest.Request(url, data=body, headers=_with_ua(headers), method=method)
        try:
            return urlrequest.urlopen(req, timeout=timeout)
        except urlerror.HTTPError as e:
            try:
                payload = e.read() or b""
            except Exception:  # noqa: BLE001
                payload = b""
            raise StreamHttpError(int(e.code), _norm_headers(e.headers), payload) from e
        except urlerror.URLError as e:
            raise NetworkError(str(getattr(e, "reason", e))) from e
        except (TimeoutError, ConnectionError, OSError) as e:
            raise NetworkError(str(e)) from e

    resp = await asyncio.to_thread(_open)
    try:
        while True:
            line = await asyncio.to_thread(resp.readline)
            if not line:
                break
            yield line
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass


class StreamHttpError(Exception):
    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        super().__init__(f"stream HTTP {status}")
        self.status = status
        self.headers = headers
        self.body = body


# --------------------------------------------------------------------------- #
# Rate-limit / retry metadata
# --------------------------------------------------------------------------- #
_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")


def parse_duration(value: str | None) -> float | None:
    """`"6.667s"`, `"1h30m"`, `"120"`, `"45"` → seconds (None when unknown)."""
    if not value:
        return None
    val = str(value).strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        pass
    m = _DURATION_RE.fullmatch(val)
    if m and any(m.groups()):
        h = float(m.group(1) or 0)
        mi = float(m.group(2) or 0)
        s = float(m.group(3) or 0)
        return h * 3600 + mi * 60 + s
    return None


def parse_retry_after(headers: Mapping[str, str], now: float | None = None) -> float | None:
    """Retry-After: seconds or HTTP-date → seconds from now (≥0)."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        base = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
        return max(0.0, (when - base).total_seconds())
    except Exception:  # noqa: BLE001
        return None


def parse_rate_limit(headers: Mapping[str, str]) -> dict[str, float | None]:
    """Normalize provider rate-limit headers (OpenAI/Groq naming).

    Returns {remaining_requests, reset_requests_s, remaining_tokens,
             reset_tokens_s, retry_after_s} — unknown entries are None.
    """
    return {
        "remaining_requests": _num(headers.get("x-ratelimit-remaining-requests")),
        "reset_requests_s": parse_duration(headers.get("x-ratelimit-reset-requests")),
        "remaining_tokens": _num(headers.get("x-ratelimit-remaining-tokens")),
        "reset_tokens_s": parse_duration(headers.get("x-ratelimit-reset-tokens")),
        "retry_after_s": parse_retry_after(headers),
    }


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# multipart/form-data (Groq Whisper upload)
# --------------------------------------------------------------------------- #
def encode_multipart(
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Build a multipart body. Returns (body, content_type-with-boundary).

    files: field_name -> (filename, payload, content_type)
    """
    boundary = "----raphaelBoundary7d3f9a2c"
    crlf = b"\r\n"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        chunks.append(f"--{boundary}".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        chunks.append(b"")
        chunks.append(str(value).encode("utf-8"))
    for name, (filename, payload, ctype) in files.items():
        chunks.append(f"--{boundary}".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode()
        )
        chunks.append(f"Content-Type: {ctype}".encode())
        chunks.append(b"")
        chunks.append(payload)
    chunks.append(f"--{boundary}--".encode())
    chunks.append(b"")
    body = b"".join(c + crlf for c in chunks)
    return body, f"multipart/form-data; boundary={boundary}"


def guess_audio_format(payload: bytes, filename: str = "") -> str:
    """Content-type for an audio upload (Groq accepts webm/wav/mp3/…)."""
    if payload[:4] == b"RIFF" and payload[8:12] == b"WAVE":
        return "audio/wav"
    if payload[:4] == b"OggS":
        return "audio/ogg"
    if payload[:3] == b"ID3" or payload[:2] == b"\xff\xfb":
        return "audio/mpeg"
    if payload[:4] == b"\x1aE\xdf\xa3":
        return "audio/webm"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg",
        "webm": "audio/webm", "m4a": "audio/mp4", "flac": "audio/flac",
    }.get(ext, "application/octet-stream")


def guess_image_mime(payload: bytes, name: str = "") -> str:
    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if payload[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
