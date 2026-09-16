"""Authenticated multi-view snapshots of cameras already configured in Moonraker.

No camera permissions, heater commands, motion or arbitrary URL input here.
Unavailable/stale views are reported individually and never labelled as live.
"""

import asyncio
import datetime
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import httpx
from fastapi import HTTPException, Request
from .request_safety import require_token
from fastapi.responses import Response

from .experiment_store import ExperimentStore

NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
LIMIT = 8 * 1024 * 1024


def install_printer_cameras(app, token, moonraker, experiments_root, transport=None):
    host = urlsplit(moonraker)
    # Relative webcam URLs belong to the printer's web server, not its API port.
    authority = f"[{host.hostname}]" if ":" in host.hostname else host.hostname
    origin = f"{host.scheme}://{authority}"

    def authorize(request):
        require_token(request, token)

    async def cameras():
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False, transport=transport) as client:
                response = await client.get(moonraker + "/server/webcams/list")
                response.raise_for_status()
                values = response.json()["result"]["webcams"]
            result = []
            for item in values[:16]:
                if not item.get("enabled", True):
                    continue
                uid = str(item.get("uid", ""))
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", uid):
                    continue
                url = urljoin(origin, item.get("snapshot_url", ""))
                target = urlsplit(url)
                if (
                    target.hostname != host.hostname
                    or target.scheme not in ("http", "https")
                    or target.username
                    or target.password
                    or target.fragment
                    or target.port not in (None, 80, 443, 8080, 8081, 8082)
                ):
                    continue
                if not item.get("snapshot_url"):
                    continue
                result.append(
                    {
                        "id": uid,
                        "name": str(item.get("name", "Camera"))[:120],
                        "rotation": item.get("rotation", 0),
                        "url": url,
                    }
                )
            return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(503, "The printer cameras could not be queried") from None

    async def snapshot(camera):
        try:
            async with httpx.AsyncClient(
                timeout=8, trust_env=False, transport=transport, follow_redirects=False
            ) as client:
                async with client.stream(
                    "GET", camera["url"], headers={"Cache-Control": "no-cache"}
                ) as response:
                    response.raise_for_status()
                    if response.headers.get("x-klipperlearn-camera") == "last-frame":
                        raise HTTPException(503, "The camera is not producing new images")
                    if response.headers.get("content-type", "").split(";")[0] != "image/jpeg":
                        raise HTTPException(503, "The camera did not provide a JPEG photograph")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > LIMIT:
                            raise HTTPException(413, "Image too large")
                    if not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
                        raise HTTPException(503, "Incomplete photograph")
                    return bytes(body)
        except httpx.HTTPError:
            raise HTTPException(503, "Camera is offline") from None

    @app.get("/mobile/api/printer/cameras")
    async def list_cameras(request: Request):
        authorize(request)
        return Response(
            json.dumps(
                {
                    "result": [
                        {k: v for k, v in cam.items() if k != "url"} for cam in await cameras()
                    ]
                }
            ),
            media_type="application/json",
            headers=NO_STORE,
        )

    @app.get("/mobile/api/printer/cameras/{camera_id}/snapshot")
    async def get_snapshot(camera_id: str, request: Request):
        authorize(request)
        selected = next((cam for cam in await cameras() if cam["id"] == camera_id), None)
        if not selected:
            raise HTTPException(404, "Camera is not configured")
        return Response(await snapshot(selected), media_type="image/jpeg", headers=NO_STORE)

    @app.post("/mobile/api/experiments/{trial_id}/capture-views")
    async def capture_views(trial_id: str, request: Request):
        authorize(request)
        if not re.fullmatch("[0-9a-f]{32}", trial_id):
            raise HTTPException(422, "Invalid trial")
        store = ExperimentStore(experiments_root)
        try:
            await asyncio.to_thread(store.get_trial, trial_id)
        except KeyError:
            raise HTTPException(404, "Ensayo no encontrado") from None
        capture_id = uuid.uuid4().hex

        async def capture(cam):
            entry = {k: v for k, v in cam.items() if k != "url"}
            entry["timestamp_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                jpeg = await snapshot(cam)
                filename = f"camera-{cam['id']}-{capture_id}.jpg"
                record = await asyncio.to_thread(store.add_photo, trial_id, jpeg, filename)
                photo = next(p for p in record["photos"] if p["original_name"] == filename)
                entry.update(
                    status="saved", sha256=photo["sha256"], relative_path=photo["relative_path"]
                )
            except HTTPException as error:
                entry.update(status="unavailable", reason=error.detail)
            return entry

        views = await asyncio.gather(*(capture(cam) for cam in await cameras()))
        result = {
            "schema": "klipperlearn.multiview/v1",
            "trial_id": trial_id,
            "capture_id": capture_id,
            "views": views,
            "lighting": "as-is",
            "note": "Captured without moving printer; framing and illumination are not validated.",
        }

        def save_manifest():
            target = (
                Path(experiments_root) / "assets" / "multiview" / trial_id / (capture_id + ".json")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as output:
                json.dump(result, output, ensure_ascii=False, allow_nan=False)

        await asyncio.to_thread(save_manifest)
        return Response(
            json.dumps({"result": result}), media_type="application/json", headers=NO_STORE
        )
