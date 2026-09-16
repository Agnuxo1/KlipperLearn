"""Discovery calls only mocked, known read-only endpoints."""

import asyncio

import httpx
import pytest

from klipperlearn.printer_discovery import approved_subnet, discover_printers


@pytest.mark.parametrize(
    "cidr,allowed,consent",
    [
        ("192.168.1.0/24", (), True),
        ("192.168.1.0/24", ("192.168.1.0/24",), False),
        ("8.8.8.8/32", ("192.168.1.0/24",), True),
        ("127.0.0.1/32", ("127.0.0.0/8",), True),
        ("192.168.1.0/23", ("192.168.0.0/16",), True),
        ("192.168.2.0/24", ("192.168.1.0/24",), True),
        ("192.168.1.2/24", ("192.168.1.0/24",), True),
        ("::1/128", ("192.168.1.0/24",), True),
        ("example.com", ("192.168.1.0/24",), True),
    ],
)
def test_discovery_scope_requires_explicit_private_consent(cidr, allowed, consent):
    with pytest.raises(ValueError):
        approved_subnet(cidr, allowed, consent)


def test_moonraker_and_octoprint_detection_without_guessed_brand_or_commands():
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host in ("192.168.1.1", "192.168.1.2")
        if request.url.host.endswith(".1"):
            return httpx.Response(
                200, json={"result": {"klippy_connected": True, "klippy_state": "error"}}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"text": "OctoPrint 1.x", "api": "0.1"})
        return httpx.Response(404)

    result = asyncio.run(
        discover_printers(
            "192.168.1.0/30", ("192.168.1.0/24",), True, transport=httpx.MockTransport(respond)
        )
    )
    assert [d["adapter"] for d in result["devices"]] == ["moonraker", "octoprint"]
    assert result["devices"][0]["printer_ready"] is False
    assert all(d["model"] is None for d in result["devices"])
    assert result["complete"] and len(requests) == 4


def test_redirects_and_html_are_not_followed_or_mistaken_for_printers():
    def respond(request):
        return httpx.Response(302, headers={"Location": "https://outside.example"})

    result = asyncio.run(
        discover_printers(
            "192.168.1.1/32", ("192.168.1.0/24",), True, transport=httpx.MockTransport(respond)
        )
    )
    assert result["devices"] == [] and result["endpoint_requests"] == 3


def test_protected_service_is_not_falsely_identified_as_a_printer():
    result = asyncio.run(
        discover_printers(
            "192.168.1.1/32",
            ("192.168.1.0/24",),
            True,
            transport=httpx.MockTransport(lambda r: httpx.Response(401)),
        )
    )
    assert result["devices"][0]["adapter"] == "unconfirmed_protected_service"


def test_timeout_reports_incomplete_scan():
    async def respond(request):
        await asyncio.sleep(1)
        return httpx.Response(404)

    result = asyncio.run(
        discover_printers(
            "192.168.1.0/30",
            ("192.168.1.0/24",),
            True,
            transport=httpx.MockTransport(respond),
            timeout_seconds=0.005,
        )
    )
    assert result["complete"] is False and result["hosts_completed"] < result["hosts_requested"]
