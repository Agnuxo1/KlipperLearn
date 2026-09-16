"""Authenticated, file-only optimizer endpoints; no route can print or apply G-code."""

import asyncio

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .printer_discovery import discover_printers
from .request_safety import read_json_object, require_token
from .slicer_optimizer import (
    MAX_BYTES,
    PARAMETERS,
    OptimizerError,
    advisor_request,
    build_profiles,
    review_session,
    validate_proposal,
)


def install_optimizer_api(app, token: str, allowed_networks=()):
    """Attach independent review tools without changing existing controller routes."""
    scan_lock = asyncio.Lock()

    def response(value):
        return JSONResponse(
            {"result": value},
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/mobile/api/optimizer/catalog")
    async def catalog(request: Request):
        require_token(request, token)
        return response(
            {
                "modes": ["Quality", "Standard", "Speed"],
                "profile_export": ["OrcaSlicer"],
                "other_slicers": "Use the assistant's settings report; native conversion is not claimed.",
                "supported_parameters": {k: {"unit": v[2]} for k, v in PARAMETERS.items()},
                "discovery_enabled": bool(allowed_networks),
                "cloud_model_connection": "Use your selected ChatGPT model or manually exchange files; no API calls are made.",
            }
        )

    @app.post("/mobile/api/optimizer/review")
    async def review(request: Request):
        require_token(request, token)
        session = await read_json_object(request, MAX_BYTES)
        try:
            return response(await asyncio.to_thread(review_session, session))
        except OptimizerError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/mobile/api/optimizer/advisor-request")
    async def prepare_advisor_request(request: Request):
        require_token(request, token)
        session = await read_json_object(request, MAX_BYTES)
        try:
            return response(await asyncio.to_thread(advisor_request, session))
        except OptimizerError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/mobile/api/optimizer/profiles")
    async def profiles(request: Request):
        require_token(request, token)
        session = await read_json_object(request, MAX_BYTES)
        try:
            return response(await asyncio.to_thread(build_profiles, session))
        except OptimizerError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/mobile/api/optimizer/check-proposal")
    async def check_proposal(request: Request):
        require_token(request, token)
        payload = await read_json_object(request, MAX_BYTES)
        if set(payload) != {"session", "proposal"}:
            raise HTTPException(422, "Provide session and proposal only")
        try:
            return response(
                await asyncio.to_thread(validate_proposal, payload["session"], payload["proposal"])
            )
        except OptimizerError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/mobile/api/optimizer/discover")
    async def discover(request: Request):
        require_token(request, token)
        payload = await read_json_object(request, 4096)
        if set(payload) != {"cidr", "confirmed"}:
            raise HTTPException(422, "Provide a network and explicit confirmation")
        if scan_lock.locked():
            raise HTTPException(409, "A discovery operation is already running")
        async with scan_lock:
            try:
                return response(
                    await discover_printers(
                        payload["cidr"], tuple(map(str, allowed_networks)), payload["confirmed"]
                    )
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
