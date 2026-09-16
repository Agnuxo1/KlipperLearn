"""Opt-in, read-only discovery on an explicitly approved private IPv4 subnet.

No Wi-Fi credential access, network reconfiguration, multicast, port-range scans,
redirects, environment proxies or printer commands. Wi-Fi and Ethernet printers
can be found only when reachable from this host on the approved IP network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json

RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
MAX_RESPONSE = 128 * 1024


def approved_subnet(cidr: str, allowed_networks: tuple[str, ...], confirmed: bool):
    """Resolve no names: require explicit consent and a /24-or-smaller allowlist subset."""
    if confirmed is not True or not allowed_networks:
        raise ValueError(
            "Discovery is disabled without explicit consent and a server-side LAN allowlist"
        )
    try:
        network = ipaddress.ip_network(cidr, strict=True)
        allowed = tuple(ipaddress.ip_network(value, strict=True) for value in allowed_networks)
    except (TypeError, ValueError):
        raise ValueError("Use canonical private IPv4 CIDR notation") from None
    if network.version != 4 or network.prefixlen < 24:
        raise ValueError("Discovery is limited to one private IPv4 /24 or smaller subnet")
    if not any(network.subnet_of(private) for private in RFC1918):
        raise ValueError("Only RFC1918 private addresses can be discovered")
    if any(n.version != 4 or not any(n.subnet_of(p) for p in RFC1918) for n in allowed):
        raise ValueError("The server discovery allowlist must contain RFC1918 subnets")
    if not any(network.subnet_of(n) for n in allowed):
        raise ValueError("Requested network is not inside the server-side allowlist")
    return network


async def discover_printers(
    cidr: str,
    allowed_networks: tuple[str, ...],
    confirmed: bool,
    *,
    transport=None,
    timeout_seconds: float = 75.0,
) -> dict:
    """Probe known read-only API endpoints, reporting partial scans honestly."""
    import httpx

    network = approved_subnet(cidr, allowed_networks, confirmed)
    addresses = [str(host) for host in network.hosts()]
    found, scanned = [], []
    slots = asyncio.Semaphore(8)
    attempts = 0
    async with httpx.AsyncClient(
        timeout=1.5, trust_env=False, follow_redirects=False, transport=transport
    ) as client:

        async def read(url):
            nonlocal attempts
            attempts += 1
            async with client.stream(
                "GET", url, headers={"Accept": "application/json"}
            ) as response:
                if response.status_code in (401, 403):
                    return "authentication_required", None
                if response.status_code != 200:
                    return "unavailable", None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_RESPONSE:
                        raise ValueError("Discovery response exceeds limit")
                    content.extend(chunk)
                try:
                    payload = json.loads(content)
                except (ValueError, UnicodeError, RecursionError):
                    return "not_json", None
                return "ok", payload

        async def probe(address):
            async with slots:
                auth_required = False
                for port, path, adapter in (
                    (7125, "/server/info", "moonraker"),
                    (80, "/server/info", "moonraker"),
                    (80, "/api/version", "octoprint"),
                ):
                    try:
                        status, data = await read(f"http://{address}:{port}{path}")
                        auth_required |= status == "authentication_required"
                        result = data.get("result") if isinstance(data, dict) else None
                        identified = (
                            adapter == "moonraker"
                            and isinstance(result, dict)
                            and type(result.get("klippy_connected")) is bool
                        )
                        identified |= (
                            adapter == "octoprint"
                            and isinstance(data, dict)
                            and str(data.get("text", "")).startswith("OctoPrint")
                        )
                        if identified:
                            found.append(
                                {
                                    "address": address,
                                    "port": port,
                                    "adapter": adapter,
                                    "brand": None,
                                    "model": None,
                                    "printer_ready": result.get("klippy_state") == "ready"
                                    if adapter == "moonraker"
                                    else None,
                                }
                            )
                            break
                    except (httpx.HTTPError, ValueError, TypeError, UnicodeError):
                        continue
                else:
                    if auth_required:
                        found.append(
                            {
                                "address": address,
                                "adapter": "unconfirmed_protected_service",
                                "authentication_required": True,
                                "brand": None,
                                "model": None,
                            }
                        )
                scanned.append(address)

        tasks = [asyncio.create_task(probe(host)) for host in addresses]
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "devices": sorted(found, key=lambda x: ipaddress.ip_address(x["address"])),
        "network": str(network),
        "hosts_requested": len(addresses),
        "hosts_completed": len(scanned),
        "endpoint_requests": attempts,
        "complete": not timed_out and len(scanned) == len(addresses),
        "printer_commands": False,
        "note": "Read-only API discovery, not a Wi-Fi SSID scan. Unknown/serial/proprietary printers use file mode. Brand and model must be confirmed by the operator.",
    }
