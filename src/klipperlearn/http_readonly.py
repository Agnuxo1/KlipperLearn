"""Bounded GET-only transport for the dependency-free observer.

Redirects and environment proxies are disabled. Every URL is validated before
opening it; camera URLs may include an ordinary query but never credentials.
"""

from __future__ import annotations

import math
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .config import _validate_http_url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise HTTPError(request.full_url, code, "Redirects are disabled", headers, response)


def read_http_bytes(url: str, *, limit: int, timeout: float = 10) -> bytes:
    """Read a validated HTTP(S) endpoint without changing device state."""
    _validate_http_url("observer URL", url)
    if type(limit) is not int or limit < 1:
        raise ValueError("The response limit must be a positive integer")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("The timeout must be finite and positive")
    try:
        valid_timeout = math.isfinite(timeout) and 0 < timeout <= 300
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValueError("The timeout must be finite, positive and at most 300 seconds")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(url, method="GET", headers={"Accept-Encoding": "identity"})
    with opener.open(request, timeout=timeout) as response:
        value = response.read(limit + 1)
        if len(value) > limit:
            raise ValueError("The HTTP response exceeds its permitted size")
        return value
