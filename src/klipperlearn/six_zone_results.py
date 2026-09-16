"""Per-zone evidence and ratings, with measured geometry kept distinct from ML."""

import datetime as dt
import hashlib
import json
import statistics

from .multimodal_learning import canonical, digest, extract_features, safe_path, weighted_score
from .registered_vision import analyze_registered_photo, registered_crop


def update_batch_results(learning):
    with learning.db() as connection:
        rows = connection.execute(
            "SELECT payload FROM learning_runs WHERE phase='complete' ORDER BY rowid DESC LIMIT 50"
        ).fetchall()
    latest_saved = False
    for record in rows:
        run = json.loads(record["payload"])
        operation = learning.setting("automatic_print:" + run["filename"])
        if not operation or not operation.get("batch_manifest") or not run.get("trial_id"):
            continue
        manifest = operation["batch_manifest"]
        parent = learning.store.get_trial(run["trial_id"])
        cached = learning.setting("batch-results:" + parent["id"]) or {
            "parent_trial_id": parent["id"],
            "zones": {},
            "photos": {},
        }
        for photo in parent["photos"]:
            if photo["sha256"] in cached["photos"]:
                continue
            try:
                path = safe_path(learning.root, photo["relative_path"])
                if hashlib.sha256(path.read_bytes()).hexdigest() != photo["sha256"]:
                    raise ValueError("Photo hash mismatch")
                cached["photos"][photo["sha256"]] = analyze_registered_photo(path, manifest)
            except (ValueError, OSError):
                cached["photos"][photo["sha256"]] = {"zones": [], "error": "photo_unusable"}
        events_path = learning.root / "assets" / "learning-runs" / run["id"] / "events.jsonl"
        events = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["event"] == "printer_sample":
                events.append(item)
        for zone in manifest["zones"]:
            samples = []
            times = []
            for event in events:
                offset = event["status"].get("virtual_sdcard", {}).get(
                    "file_position", -1
                ) - operation.get("source_prefix_bytes", 0)
                if zone["start_byte"] <= offset < zone["end_byte"]:
                    samples.append(event["status"])
                    times.append(event["at"])
            start = min(times) if times else None
            end = max(times) if times else None
            if zone["id"] not in cached["zones"]:
                # Recover a record if the process stopped between record creation
                # and saving the index. Never create a second statistical sample.
                with learning.db() as connection:
                    existing = connection.execute(
                        "SELECT id FROM trials WHERE json_extract(evidence_json,'$.parent_trial_id')=? AND json_extract(evidence_json,'$.batch_zone')=? LIMIT 1",
                        (parent["id"], zone["id"]),
                    ).fetchone()
                if existing:
                    child = learning.store.get_trial(existing["id"])
                else:
                    geometry = {k: zone[k] for k in ("line_width_mm", "layer_height_mm")}
                    geometry["generator_revision"] = manifest.get("generator_revision", 1)
                    geometry["paths"] = [
                        {
                            "role": p["role"],
                            "points": [
                                [
                                    round(x - zone["bounds_mm"][0], 6),
                                    round(y - zone["bounds_mm"][1], 6),
                                ]
                                for x, y in p["points_mm"]
                            ],
                        }
                        for p in zone["paths"]
                    ]
                    child = learning.store.create_trial(
                        {**parent["context"], "model_sha256": digest(geometry)},
                        {
                            "volumetric_mm3_s": zone["volumetric_mm3_s"],
                            "speed_mm_s": zone["speed_mm_s"],
                            "accel_mm_s2": manifest["source_spec"]["acceleration_mm_s2"],
                        },
                        None,
                        {
                            "parent_trial_id": parent["id"],
                            "batch_zone": zone["id"],
                            "learning_run_id": run["id"],
                            "telemetry_parent_trial_id": parent["id"],
                            "capture_window_utc": [start, end],
                            "source": "registered_six_zone",
                            "same_batch_session": True,
                        },
                    )
                cached["zones"][zone["id"]] = {"trial_id": child["id"]}
                learning.setting("batch-results:" + parent["id"], cached)
            child = learning.store.get_trial(cached["zones"][zone["id"]]["trial_id"])
            views = [
                view
                for photo in cached["photos"].values()
                for view in photo["zones"]
                if view["zone_id"] == zone["id"]
            ]
            good = [view for view in views if view["usable"]]
            for view in good:
                source_photo = next(
                    p for p in parent["photos"] if p["sha256"] == view["image_sha256"]
                )
                source_name = source_photo.get("original_name", "manual")
                camera = (
                    source_name[7:].rsplit("-", 1)[0]
                    if source_name.startswith("camera-")
                    else ("phone-light" if "torch-on" in source_name else "phone-ambient")
                )
                name = f"camera-{camera}-registered-{view['image_sha256']}.jpg"
                if not any(photo["original_name"] == name for photo in child["photos"]):
                    child = learning.store.add_photo(
                        child["id"],
                        registered_crop(
                            safe_path(learning.root, source_photo["relative_path"]),
                            zone,
                            view["corners_px"],
                        ),
                        name,
                    )
            measured = (
                100 * statistics.median(view["analysis"]["metrics"]["iou"] for view in good)
                if good
                else None
            )
            # Full photos remain attached to the parent, not duplicated six times.
            features = extract_features(learning.root, child, samples)
            assessment = {
                "trial_id": child["id"],
                "rating_revision": child["rating_revision"],
                "features": features,
                "data_score": measured,
                "combined_score": weighted_score(measured, child["human_score"]),
                "measurement_validated": bool(good),
                "model_validated": False,
                "views": views,
                "score_kind": "registered_projected_line_geometry",
                "weights": {"data": 0.4, "human": 0.6},
                "automatic_changes": False,
                "reason": "screening_not_an_adopted_profile",
            }
            learning.setting("registered-assessment:" + child["id"], assessment)
            with learning.db() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO learning_assessments VALUES (?,?,?,?)",
                    (
                        child["id"],
                        digest(assessment),
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                        canonical(assessment),
                    ),
                )
            cached["zones"][zone["id"]].update(
                rate=zone["volumetric_mm3_s"],
                human_score=child["human_score"],
                data_score=measured,
                score=assessment["combined_score"],
                usable_views=len(good),
                sensor_coverage=features["coverage"],
                rated=child["rating_revision"] is not None,
            )
        learning.setting("batch-results:" + parent["id"], cached)
        if not latest_saved:
            learning.setting(
                "latest_batch",
                {
                    "parent_trial_id": parent["id"],
                    "zones": list(cached["zones"].values()),
                    "message": "Rate each zone; a global improvement requires repeating the comparison.",
                },
            )
            latest_saved = True
        pending = next((z for z in cached["zones"].values() if not z["rated"]), None)
        current = learning.current_run()
        if pending and current and current["id"] == run["id"]:
            learning.setting(
                "review_pending",
                {
                    "trial_id": pending["trial_id"],
                    "filename": run["filename"],
                    "batch": parent["id"],
                },
            )
