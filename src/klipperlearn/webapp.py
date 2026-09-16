"""Local evidence dashboard with an optional authenticated companion.

Private session summaries require the configured receiver token. The default
loopback-only dashboard remains usable without enabling any printer controls.
"""

from pathlib import Path

from .mobile import MAX_MOBILE_EXPORT_BYTES, MAX_MOBILE_FRAME_BYTES, MobileInbox
from .storage import session_summary


def create_app(session_root, mobile_inbox=None, mobile_token=None):
    """Create an evidence app; installing the companion is an explicit extra step."""
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import RedirectResponse
        from fastapi.staticfiles import StaticFiles
        from .request_safety import (
            install_request_safety,
            read_limited_body,
            decode_json_object,
            require_token,
        )
    except ImportError as exc:
        raise RuntimeError("Dashboard requires: pip install -e '.[dashboard]'") from exc

    root = Path(session_root).resolve()
    if mobile_token is not None and (
        not isinstance(mobile_token, str)
        or not 16 <= len(mobile_token) <= 4096
        or not mobile_token.isascii()
        or any(c.isspace() for c in mobile_token)
    ):
        raise ValueError(
            "The local receiver token must be 16-4096 non-whitespace ASCII characters."
        )

    app = FastAPI(title="KlipperLearn", version="0.5.1")
    app.state.klipperlearn_companion_installed = False
    install_request_safety(app)

    def authorize_private(request):
        if mobile_token is not None:
            require_token(request, mobile_token)

    def session_path(identifier):
        candidate = root / identifier
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise HTTPException(404, "Session not found")
        candidate = candidate.resolve()
        if candidate.parent != root or not candidate.is_dir():
            raise HTTPException(404, "Session not found")
        return candidate

    @app.get("/health")
    def health():
        enabled = bool(app.state.klipperlearn_companion_installed)
        return {
            "status": "ok",
            "mode": "local_companion" if enabled else "local_evidence_only",
            "printer_control": enabled,
            "camera_live_enabled": enabled,
            "mobile_upload_enabled": mobile_token is not None,
        }

    @app.get("/sessions")
    def sessions(request: Request):
        authorize_private(request)
        if not root.exists():
            return []
        result = []
        for child in sorted(root.iterdir(), reverse=True):
            try:
                candidate = session_path(child.name)
            except HTTPException:
                continue
            database = candidate / "telemetry.sqlite3"
            if database.is_file() and not database.is_symlink():
                result.append({"id": child.name, "summary": session_summary(candidate)})
        return result

    @app.get("/sessions/{session_id}")
    def session(session_id: str, request: Request):
        authorize_private(request)
        candidate = session_path(session_id)
        database = candidate / "telemetry.sqlite3"
        if not database.is_file() or database.is_symlink():
            raise HTTPException(404, "Session not found")
        return session_summary(candidate)

    if mobile_token is not None:
        inbox = MobileInbox(mobile_inbox or "data/mobile-inbox")

        @app.post("/mobile/api/sessions", status_code=201)
        async def receive_mobile_session(request: Request):
            require_token(request, mobile_token)
            content = await read_limited_body(request, MAX_MOBILE_EXPORT_BYTES)
            payload = decode_json_object(content)
            try:
                return inbox.store_export(payload)
            except FileExistsError:
                raise HTTPException(409, "This mobile session already exists") from None
            except ValueError:
                raise HTTPException(422, "Invalid mobile session") from None

        @app.put("/mobile/api/sessions/{session_id}/frames/{filename}", status_code=201)
        async def receive_mobile_frame(session_id: str, filename: str, request: Request):
            require_token(request, mobile_token)
            if (
                request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "image/jpeg"
            ):
                raise HTTPException(415, "A JPEG camera frame is required")
            content = await read_limited_body(request, MAX_MOBILE_FRAME_BYTES)
            try:
                return inbox.store_frame(session_id, filename, content)
            except FileNotFoundError:
                raise HTTPException(404, "Mobile session or frame not found") from None
            except FileExistsError:
                raise HTTPException(409, "This mobile frame already exists") from None
            except ValueError:
                raise HTTPException(422, "Invalid mobile camera frame") from None

    mobile_root = Path(__file__).with_name("mobile_app")

    @app.get("/mobile", include_in_schema=False)
    def mobile_redirect():
        return RedirectResponse(url="/mobile/")

    app.mount("/mobile", StaticFiles(directory=mobile_root, html=True), name="mobile")
    return app
