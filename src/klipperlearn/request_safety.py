"""Shared, bounded request parsing and constant-time token comparisons.

No networking or printer commands are performed by this module. Body limits
are enforced while streaming, before a chunk can enlarge the retained buffer.
"""

from __future__ import annotations

import hmac
import json
import math
import re

from fastapi import HTTPException

JSON_BODY_LIMIT = 256 * 1024


def token_matches(candidate: object, expected: object) -> bool:
    """Reject malformed values without leaking either token or raising on Unicode."""
    if not isinstance(candidate, str) or not isinstance(expected, str) or not candidate:
        return False
    if len(candidate) > 4096 or len(expected) > 4096:
        return False
    try:
        return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeError:
        return False


def require_token(request, expected: str, header: str = "x-klipperlearn-token") -> None:
    """Accept exactly one authentication header; ambiguous duplicates fail closed."""
    values = request.headers.getlist(header)
    if len(values) != 1 or not token_matches(values[0], expected):
        raise HTTPException(401, "Unauthorized")


async def read_limited_body(request, limit: int) -> bytes:
    """Read at most limit bytes, including chunked or misleading-length requests."""
    if type(limit) is not int or limit <= 0:
        raise ValueError("The body limit must be a positive integer")
    lengths = request.headers.getlist("content-length")
    if lengths:
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
            raise HTTPException(400, "Invalid Content-Length")
        if int(lengths[0]) > limit:
            raise HTTPException(413, "Request body exceeds the permitted size")
    content = bytearray()
    async for chunk in request.stream():
        if len(chunk) > limit - len(content):
            raise HTTPException(413, "Request body exceeds the permitted size")
        content.extend(chunk)
    return bytes(content)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON constant")


def _validate_value(value, depth=0):
    if depth > 64:
        raise ValueError("JSON is too deeply nested")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
    elif isinstance(value, list):
        for item in value:
            _validate_value(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_value(key, depth + 1)
            _validate_value(item, depth + 1)
    else:
        raise ValueError("Invalid JSON value")


def decode_json_object(content: bytes) -> dict:
    """Reject duplicates, excessive nesting, invalid Unicode and non-finite numbers."""
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        _validate_value(value)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise HTTPException(422, "A valid, finite JSON object is required") from None


async def read_json_object(request, limit: int = JSON_BODY_LIMIT) -> dict:
    """Read a strictly validated JSON object with a streaming memory limit."""
    return decode_json_object(await read_limited_body(request, limit))


class RequestSafetyMiddleware:
    """Prevent ambiguous auth headers and caching of private API responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        private = (
            path.startswith("/mobile/api/") or path == "/sessions" or path.startswith("/sessions/")
        )
        if private:
            headers = scope.get("headers", [])
            for name in (b"x-klipperlearn-token", b"x-klipperlearn-viewer"):
                if sum(key.lower() == name for key, _ in headers) > 1:
                    from starlette.responses import JSONResponse

                    response = JSONResponse(
                        {"detail": "Unauthorized"},
                        status_code=401,
                        headers={"Cache-Control": "no-store"},
                    )
                    return await response(scope, receive, send)

        async def safe_send(message):
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-content-type-options"
                    and (not private or key.lower() != b"cache-control")
                ]
                headers.append((b"x-content-type-options", b"nosniff"))
                if private:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, safe_send)


def install_request_safety(app) -> None:
    """Install once for both standalone and companion application construction."""
    if not getattr(app.state, "klipperlearn_request_safety", False):
        app.add_middleware(RequestSafetyMiddleware)
        app.state.klipperlearn_request_safety = True
