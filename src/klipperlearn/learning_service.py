"""Persistent automatic collection and multimodal learning for actual print jobs.

The observer never starts, heats, homes or cancels a printer. Actuation is a
separate bounded experiment operation, not a side effect of collecting evidence.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress, contextmanager
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote, urlsplit
import uuid

import httpx
from fastapi import HTTPException, Request
from .request_safety import read_json_object, require_token
from fastapi.responses import Response

from .experiment_store import ExperimentStore
from .multimodal_learning import (
    canonical,
    context_key,
    digest,
    extract_features,
    fit_model,
    predict_score,
    weighted_score,
)
from .print_context import fetch_print_context

QUERY = "/printer/objects/query?webhooks&print_stats&extruder&heater_bed&toolhead&gcode_move&virtual_sdcard"


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class LearningService:
    def __init__(self, app, token, moonraker, root, telemetry_store, transport=None):
        self.app, self.token, self.moonraker = app, token, moonraker
        self.root = Path(root).resolve()
        self.store = ExperimentStore(self.root)
        self.telemetry = telemetry_store
        self.transport = transport
        self.task = None
        self.status = {
            "phase": "starting",
            "message": "Preparing continuous evidence collection",
            "automatic_changes": False,
        }
        self.last_learning = 0
        self.reconciled = False
        self.automatic_configured = False
        from .automatic_print import AutomaticPrint

        self.automatic = AutomaticPrint(self)
        with self.db() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS learning_state (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_runs (
                    id TEXT PRIMARY KEY, job_key TEXT UNIQUE NOT NULL, trial_id TEXT,
                    filename TEXT NOT NULL, phase TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_assessments (
                    trial_id TEXT NOT NULL, input_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(trial_id, input_sha256)
                );
                CREATE TABLE IF NOT EXISTS learning_models (
                    context_key TEXT NOT NULL, model_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(context_key, model_sha256)
                );
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.store.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def setting(self, key, value=None):
        with self.db() as connection:
            if value is not None:
                connection.execute(
                    "INSERT INTO learning_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",
                    (key, canonical(value)),
                )
            row = connection.execute(
                "SELECT payload FROM learning_state WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row["payload"]) if row else None

    async def internal(self, method, path, **kwargs):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://klipperlearn.internal",
            headers={"X-KlipperLearn-Token": self.token},
            timeout=15,
        ) as client:
            response = await client.request(method, "/mobile/api/" + path, **kwargs)
            response.raise_for_status()
            payload = response.json()
            return payload.get("result", payload)

    def save_run(self, run):
        with self.db() as connection:
            connection.execute(
                """INSERT INTO learning_runs VALUES (?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET phase=excluded.phase,payload=excluded.payload,trial_id=excluded.trial_id""",
                (
                    run["id"],
                    run["job_key"],
                    run.get("trial_id"),
                    run["filename"],
                    run["phase"],
                    canonical(run),
                ),
            )
        self.setting("current_run", {"id": run["id"]})

    def current_run(self):
        current = self.setting("current_run")
        if not current:
            return None
        with self.db() as connection:
            row = connection.execute(
                "SELECT payload FROM learning_runs WHERE id=?", (current["id"],)
            ).fetchone()
            return json.loads(row["payload"]) if row else None

    def pending_public(self):
        operation = self.automatic.pending()
        if not operation:
            return None
        return {
            "phase": operation["phase"],
            "source_filename": operation["source_filename"],
            "decision": operation["decision"],
            "changed": operation["audit"]["changed"],
        }

    def event(self, run, event, **data):
        path = self.root / "assets" / "learning-runs" / run["id"] / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(canonical({"at": utc(), "event": event, **data}) + "\n")

    async def new_run(self, state, printer):
        filename = state["print_stats"]["filename"]
        context = await fetch_print_context(
            self.moonraker, filename=filename, transport=self.transport
        )
        metadata = context["provenance"]["metadata"].get("fields", {})
        start_time = metadata.get("print_start_time")
        # Moonraker start time identifies repeated prints of the same filename.
        # If unavailable, only an observed transition gets a new identity.
        job_key = digest([filename, start_time]) if start_time else uuid.uuid4().hex
        if start_time:
            with self.db() as connection:
                found = connection.execute(
                    "SELECT payload FROM learning_runs WHERE job_key=?", (job_key,)
                ).fetchone()
                if found:
                    previous = json.loads(found["payload"])
                    if previous["phase"] not in ("printing", "paused"):
                        raise ValueError("Waiting for a fresh print identity from Moonraker")
                    if state["print_stats"].get("print_duration", 0) + 5 < previous.get(
                        "last_duration", 0
                    ):
                        raise ValueError("Print duration reset before Moonraker identity updated")
                    return previous
        else:
            previous = self.current_run()
            if (
                previous
                and previous["filename"] == filename
                and previous["phase"] in ("printing", "paused")
            ):
                if state["print_stats"].get("print_duration", 0) + 5 >= previous.get(
                    "last_duration", 0
                ):
                    return previous
        run = {
            "id": uuid.uuid4().hex,
            "job_key": job_key,
            "filename": filename,
            "phase": "printing",
            "started_at": utc(),
            "context": context,
            "last_duration": 0,
            "owned_telemetry": False,
            "partial_start": state["print_stats"].get("print_duration", 0) > 15,
        }
        operation = self.setting("automatic_print:" + filename)
        if operation and operation.get("batch_manifest"):
            spec = operation["batch_manifest"]["source_spec"]
            context["material"] = {"type": spec["material"], "name": spec["material"]}
            context["nozzle_mm"] = spec["nozzle_mm"]
            context["provenance"]["batch_reference"] = "verified_source_slicer_profile"
            context["conflicts"] = (
                [] if context.get("configured_nozzle_mm") == spec["nozzle_mm"] else ["nozzle_mm"]
            )
            context["provenance"]["metadata"].setdefault("fields", {})["object_height"] = 0.6
            run["context"] = context
        self.event(run, "started", context=context)
        material = context.get("material") or {}
        material_name = material.get("name") or material.get("type")
        nozzle = context.get("nozzle_mm") or context.get("configured_nozzle_mm")
        if material_name and nozzle and not context["conflicts"]:
            hasher = hashlib.sha256()
            length = 0
            async with printer.stream(
                "GET", "/server/files/gcodes/" + quote(filename, safe="/")
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > 128 * 1024 * 1024:
                        raise ValueError("G-code exceeds learning identification limit")
                    hasher.update(chunk)
            active = await asyncio.to_thread(self.telemetry.get_active)
            if active.get("trial_id"):
                try:
                    existing = await asyncio.to_thread(self.store.get_trial, active["trial_id"])
                    if (existing.get("evidence") or {}).get("filename") == filename:
                        run["trial_id"] = existing["id"]
                except (KeyError, ValueError):
                    pass
            if not run.get("trial_id"):
                automatic_evidence = {}
                model_sha = hasher.hexdigest()
                if operation:
                    if model_sha != operation["variant_sha256"]:
                        raise ValueError("Automatic variant changed after verification")
                    model_sha = operation["source_sha256"]
                    automatic_evidence = {
                        "automatic_profile": operation["decision"]["profile"],
                        "source_filename": operation["source_filename"],
                        "automatic_operation_id": operation["id"],
                        "decision": operation["decision"],
                    }
                trial = await asyncio.to_thread(
                    self.store.create_trial,
                    {
                        "printer_id": urlsplit(self.moonraker).hostname,
                        "session_id": run["id"],
                        "model_sha256": model_sha,
                        "material": material_name,
                        "nozzle_mm": nozzle,
                    },
                    {
                        "pressure_advance": context["parameters"]["pressure_advance"],
                        "accel_mm_s2": context["parameters"]["accel_mm_s2"],
                        "extrusion_factor": context["parameters"]["extrude_factor"],
                        "parameter_source": "observed_at_print_start",
                    },
                    None,
                    {
                        "filename": filename,
                        "learning_run_id": run["id"],
                        "model_identity_kind": "gcode_sha256",
                        "partial_start": run["partial_start"],
                        "source": "automatic_print_observer",
                        **automatic_evidence,
                    },
                )
                run["trial_id"] = trial["id"]
                if not active.get("trial_id"):
                    run["owned_telemetry"] = await asyncio.to_thread(
                        self.telemetry.claim_if_empty, trial["id"]
                    )
        else:
            run["context_issue"] = (
                "Material or nozzle details are missing or inconsistent; telemetry is preserved without inventing context."
            )
        self.save_run(run)
        return run

    async def finish_run(self, run, state):
        final_mode = state["print_stats"]["state"]
        if run["phase"] != "finishing":
            run["finished_at"] = utc()
            self.event(run, "finished", status=state)
        run["phase"] = "finishing"
        self.save_run(run)
        if final_mode == "complete" and run.get("trial_id"):
            # A final G-code park can be verified without adding any movement.
            toolhead = state.get("toolhead", {})
            position = toolhead.get("position") or []
            maximum = toolhead.get("axis_maximum") or []
            height = (
                run.get("context", {})
                .get("provenance", {})
                .get("metadata", {})
                .get("fields", {})
                .get("object_height")
            )
            operation = self.setting("automatic_print:" + run["filename"])
            if operation and operation.get("declared_object_height") is not None:
                # Moonraker may include the final Z parking move in object_height.
                height = operation["declared_object_height"]
            parked = (
                isinstance(height, (int, float))
                and len(position) >= 3
                and len(maximum) >= 3
                and position[2] >= height + 2
                and position[0] >= maximum[0] - 15
                and position[1] >= maximum[1] - 15
            )
            if parked and not run.get("photo_pair_job"):
                try:
                    run["photo_pair_job"] = await self.internal(
                        "POST", "photo-pairs", json={"trial_id": run["trial_id"]}
                    )
                    self.save_run(run)
                except (httpx.HTTPError, ValueError):
                    run["photo_pair_issue"] = (
                        "Paired photographs are unavailable; general captures and manual review remain available."
                    )
            elif not parked:
                run["photo_pair_issue"] = (
                    "Final parking has not been verified; no speculative movement commands are sent."
                )
                # Read-only snapshots: no unexpected homing/Z moves on a finished model.
            try:
                if not run.get("captured_views"):
                    result = await self.internal(
                        "POST", f"experiments/{run['trial_id']}/capture-views"
                    )
                    self.event(run, "result_views", capture=result)
                    run["captured_views"] = result
                    self.save_run(run)
            except (httpx.HTTPError, ValueError):
                run["photo_issue"] = (
                    "Not all camera views could be captured; a photograph can be added manually."
                )
            job = run.get("photo_pair_job") or {}
            if job.get("id"):
                try:
                    job = await self.internal("GET", "photo-pairs/" + job["id"])
                    run["photo_pair_job"] = job
                except (httpx.HTTPError, ValueError):
                    run["photo_pair_issue"] = (
                        "Paired photographs could not be verified; other views are preserved."
                    )
                elapsed = (
                    dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(run["finished_at"])
                ).total_seconds()
                if job.get("status") in ("pending", "running") and elapsed < 150:
                    self.save_run(run)
                    return  # Keep phone ownership alive; retry on the next observer tick.
            run["awaiting_rating"] = True
            self.setting(
                "review_pending", {"trial_id": run["trial_id"], "filename": run["filename"]}
            )
        if run.get("owned_telemetry"):
            active = await asyncio.to_thread(self.telemetry.get_active)
            if active.get("trial_id") == run.get("trial_id"):
                # Give the phone its final upload window before closing ownership.
                await asyncio.sleep(6)
                await asyncio.to_thread(self.telemetry.release_if_owner, run["trial_id"])
        run["phase"] = final_mode
        self.save_run(run)

    def learn(self):
        from .six_zone_results import update_batch_results

        update_batch_results(self)
        trials = []
        for offset in range(0, 100000, 200):
            page = self.store.recent_trials(200, offset)
            trials.extend(page)
            if len(page) < 200:
                break
        rows = []
        for trial in trials:
            measured = (
                self.setting("registered-assessment:" + trial["id"])
                if (trial.get("evidence") or {}).get("batch_zone")
                else None
            )
            samples = []
            run_id = (trial.get("evidence") or {}).get("learning_run_id")
            if (
                isinstance(run_id, str)
                and len(run_id) == 32
                and all(c in "0123456789abcdef" for c in run_id)
            ):
                path = self.root / "assets" / "learning-runs" / run_id / "events.jsonl"
                if path.is_file():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        event = json.loads(line)
                        if event["event"] == "printer_sample":
                            samples.append(event["status"])
            features = (
                measured["features"] if measured else extract_features(self.root, trial, samples)
            )
            row = {
                "trial_id": trial["id"],
                "session_id": trial["context"]["session_id"],
                "context_key": context_key(trial, features),
                "human_score": trial["human_score"],
                "rating_revision": trial["rating_revision"],
                "features": features,
                "measured_geometry": measured,
            }
            rows.append(row)
        groups = {}
        for row in rows:
            groups.setdefault(row["context_key"], []).append(row)
        models = {}
        for key, group in groups.items():
            model = fit_model(group)
            models[key] = model
            sha = model.get("model_sha256") or digest(model)
            with self.db() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO learning_models VALUES (?,?,?,?)",
                    (key, sha, utc(), canonical(model)),
                )
        for row in rows:
            model = models[row["context_key"]]
            # Historical rows get held-out predictions, not a fit to their own label.
            score = (
                model.get("cross_validated_scores", {}).get(row["trial_id"])
                if model.get("validated")
                else None
            )
            if score is None and row["trial_id"] not in model.get("trials", []):
                score = predict_score(model, row["features"])
            assessment = {
                **row,
                "data_score": score,
                "combined_score": weighted_score(score, row["human_score"]),
                "weights": {"data": 0.4, "human": 0.6},
                "model_validated": model.get("validated", False),
                "model_sha256": model.get("model_sha256"),
                "model_reason": model["reason"],
                "prediction_error": model.get("mae", 100),
                "score_kind": "learned_quality_estimate_not_dimensional_measurement",
                "automatic_changes": False,
            }
            if row["measured_geometry"]:
                # Preserve direct registered measurements as the score source;
                # train the estimator too, without relabelling a prediction as a measurement.
                assessment = {
                    **assessment,
                    **row["measured_geometry"],
                    "estimator_validated": model.get("validated", False),
                    "estimator_prediction": score,
                }
            sha = digest(assessment)
            with self.db() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO learning_assessments VALUES (?,?,?,?)",
                    (row["trial_id"], sha, utc(), canonical(assessment)),
                )
        summary = {
            "phase": "learning",
            "trials": len(trials),
            "rated": sum(row["human_score"] is not None for row in rows),
            "with_usable_images": sum(row["features"]["eligible"] for row in rows),
            "model_groups": len(models),
            "validated_models": sum(model["validated"] for model in models.values()),
            "minimum_independent_sessions": 8,
            "updated_at": utc(),
            "automatic_changes": False,
            "message": "History analyzed. Bounded trials do not establish a validated optimal profile.",
        }
        self.setting("summary", summary)
        return summary

    async def tick(self, printer):
        response = await printer.get(QUERY)
        response.raise_for_status()
        state = response.json()["result"]["status"]
        mode = state["print_stats"]["state"]
        await self.automatic.restore(printer, state)
        run = self.current_run()
        if mode in ("printing", "paused"):
            filename = state["print_stats"]["filename"]
            duration = state["print_stats"].get("print_duration", 0)
            if (
                not self.reconciled
                or not run
                or run["phase"] not in ("printing", "paused")
                or run["filename"] != filename
                or duration + 5 < run.get("last_duration", 0)
            ):
                run = await self.new_run(state, printer)
            self.event(run, "printer_sample", status=state)
            run["phase"] = mode
            run["last_duration"] = duration
            self.save_run(run)
            self.status = {
                "phase": mode,
                "trial_id": run.get("trial_id"),
                "message": "Collecting evidence from this print",
                "automatic_changes": False,
            }
        elif (
            run
            and run["phase"] in ("printing", "paused", "finishing")
            and mode in ("complete", "cancelled", "error")
        ):
            if state["print_stats"].get("filename") == run["filename"]:
                await self.finish_run(run, state)
            else:
                run["phase"] = "interrupted"
                self.event(run, "interrupted")
                self.save_run(run)
        self.reconciled = True
        if mode not in ("printing", "paused") and time.monotonic() - self.last_learning > 30:
            self.status = await asyncio.to_thread(self.learn)
            self.last_learning = time.monotonic()

    async def run(self):
        async with httpx.AsyncClient(
            base_url=self.moonraker, timeout=12, trust_env=False, transport=self.transport
        ) as printer:
            while True:
                try:
                    await self.tick(printer)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # Do not expose URLs, credentials, stack traces or raw data through the UI.
                    self.status = {
                        "phase": "waiting",
                        "message": "Learning is waiting for evidence or a connection; printer access remains available.",
                        "error_kind": type(error).__name__,
                        "automatic_changes": False,
                    }
                await asyncio.sleep(3)

    async def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task


def install_learning_service(app, token, moonraker, root, telemetry_store, transport=None):
    service = LearningService(app, token, moonraker, root, telemetry_store, transport)
    app.state.klipperlearn_learning = service
    from .six_zone_service import install_six_zone_service

    install_six_zone_service(app, service)
    app.router.add_event_handler("startup", service.start)
    app.router.add_event_handler("shutdown", service.stop)

    def authorize(request):
        require_token(request, token)

    @app.get("/mobile/api/learning/status")
    async def status(request: Request):
        authorize(request)
        return Response(
            canonical(
                {
                    "result": {
                        **service.status,
                        "summary": service.setting("summary"),
                        "review_pending": service.setting("review_pending"),
                        "latest_batch": service.setting("latest_batch"),
                        "automatic_enabled": service.automatic_configured
                        and (service.setting("automatic_preferences") or {}).get("enabled", True),
                        "automatic_print": service.pending_public(),
                    }
                }
            ),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/mobile/api/learning/settings")
    async def preferences(request: Request):
        authorize(request)
        payload = await read_json_object(request)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"enabled"}
            or type(payload["enabled"]) is not bool
        ):
            raise HTTPException(422, "enabled must be a boolean")
        if payload["enabled"] and not service.automatic_configured:
            raise HTTPException(409, "Automatic trials are not enabled on this server")
        service.setting("automatic_preferences", payload)
        return {"result": payload}

    @app.get("/mobile/api/learning/export")
    async def export(request: Request):
        authorize(request)
        from .evidence_backup import export_evidence
        from fastapi.responses import FileResponse
        from starlette.background import BackgroundTask

        destination = service.root.parent / "exports" / ("evidence-" + uuid.uuid4().hex + ".zip")
        await asyncio.to_thread(export_evidence, service.root, destination)
        return FileResponse(
            destination,
            filename="klipperlearn-private-evidence.zip",
            media_type="application/zip",
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(destination.unlink),
        )

    @app.get("/mobile/api/learning/assessment/{trial_id}")
    async def assessment(trial_id: str, request: Request):
        authorize(request)
        with service.db() as connection:
            row = connection.execute(
                "SELECT payload FROM learning_assessments WHERE trial_id=? ORDER BY rowid DESC LIMIT 1",
                (trial_id,),
            ).fetchone()
        return Response(
            canonical({"result": json.loads(row["payload"]) if row else None}),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    return service
