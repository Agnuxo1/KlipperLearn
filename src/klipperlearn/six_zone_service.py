"""Prepare, identify and assess six-zone screens through the existing web app."""

import asyncio
import hashlib
import re
import uuid

import httpx
from fastapi import HTTPException, Request
from .request_safety import read_json_object, require_token

from .print_context import fetch_print_context
from .six_zone_batch import build_six_zone_batch


def install_six_zone_service(app, learning):
    @app.post("/mobile/api/learning/six-zone/prepare")
    async def prepare(request: Request):
        require_token(request, learning.token)
        payload = await read_json_object(request)
        if not isinstance(payload, dict) or set(payload) - {"filename"}:
            raise HTTPException(422, "Only the reference filename is accepted")
        if learning.automatic.lock.locked():
            raise HTTPException(409, "Preparation is already in progress")
        async with learning.automatic.lock:
            try:
                async with httpx.AsyncClient(
                    base_url=learning.moonraker,
                    timeout=20,
                    trust_env=False,
                    transport=learning.transport,
                ) as printer:
                    response = await printer.get(
                        "/printer/objects/query?webhooks&print_stats&toolhead&extruder&gcode_move&configfile"
                    )
                    response.raise_for_status()
                    state = response.json()["result"]["status"]
                    if state["webhooks"]["state"] != "ready" or state["print_stats"][
                        "state"
                    ] not in ("standby", "complete", "cancelled"):
                        raise HTTPException(409, "Wait for the current print to finish")
                    filename = payload.get("filename") or state["print_stats"]["filename"]
                    operation = (
                        learning.setting("automatic_print:" + filename) if filename else None
                    )
                    if operation:
                        filename = (operation.get("batch_manifest") or {}).get(
                            "reference_filename"
                        ) or operation["source_filename"]
                    if (
                        not filename
                        or ".." in filename
                        or "\\" in filename
                        or filename.startswith("/")
                    ):
                        raise HTTPException(
                            422,
                            "Select an Orca G-code file to obtain material and temperature settings",
                        )
                    source = (await learning.automatic.download(printer, filename)).decode(
                        "utf-8-sig"
                    )
                    context = await fetch_print_context(
                        learning.moonraker, filename=filename, transport=learning.transport
                    )
                    metadata = context["provenance"]["metadata"].get("fields", {})
                    settings = state["configfile"]["settings"]
                    machine = settings["printer"]
                    if machine.get("kinematics") not in (
                        "cartesian",
                        "corexy",
                        "hybrid_corexy",
                        "corexz",
                    ):
                        raise HTTPException(
                            422, "This version requires a rectangular bed and compatible kinematics"
                        )
                    if context["conflicts"] or context.get("nozzle_mm") != 0.4:
                        raise HTTPException(
                            422, "The file must declare a 0.4 mm nozzle and match Klipper"
                        )

                    def slicer_number(key):
                        match = re.search(
                            r"^;\s*" + re.escape(key) + r"\s*=\s*([0-9.]+)\s*$", source, re.M
                        )
                        if not match:
                            raise ValueError(
                                "A material parameter is missing from the reference G-code: " + key
                            )
                        return float(match[1])

                    rate = slicer_number("filament_max_volumetric_speed")
                    flow = slicer_number("filament_flow_ratio")
                    maximum = state["toolhead"]["axis_maximum"]
                    spec = {
                        "bed_width_mm": maximum[0],
                        "bed_depth_mm": maximum[1],
                        "origin_x_mm": 10,
                        "origin_y_mm": 10,
                        "size_mm": 80,
                        "nozzle_mm": 0.4,
                        "layer_height_mm": 0.2,
                        "line_width_mm": 0.42,
                        "filament_diameter_mm": 1.75,
                        "print_speed_mm_s": 25,
                        "travel_speed_mm_s": min(100, machine["max_velocity"]),
                        "hotend_temp_c": metadata["first_layer_extr_temp"],
                        "bed_temp_c": metadata["first_layer_bed_temp"],
                        "max_hotend_temp_c": settings["extruder"]["max_temp"] - 5,
                        "max_bed_temp_c": settings["heater_bed"]["max_temp"] - 5,
                        "max_velocity_mm_s": machine["max_velocity"],
                        "max_volumetric_mm3_s": rate * 1.5,
                        "max_accel_mm_s2": machine["max_accel"],
                        "acceleration_mm_s2": min(750, machine["max_accel"]),
                        "material": metadata["filament_type"],
                        "flow_ratio": flow,
                    }
                    restore = {
                        "extrusion_factor": state["gcode_move"]["extrude_factor"],
                        "accel_mm_s2": state["toolhead"]["max_accel"],
                    }
                    batch = await asyncio.to_thread(
                        build_six_zone_batch,
                        spec,
                        [round(rate * (1 + 0.1 * i), 4) for i in range(6)],
                        restore,
                    )
                    batch["manifest"]["reference_filename"] = filename
                    filename = "KlipperLearn-six-zones-" + uuid.uuid4().hex + ".gcode"
                    raw = batch["gcode"].encode()
                    response = await printer.post(
                        "/server/files/upload",
                        data={"root": "gcodes"},
                        files={"file": (filename, raw, "application/octet-stream")},
                    )
                    response.raise_for_status()
                    if (
                        hashlib.sha256(
                            await learning.automatic.download(printer, filename)
                        ).hexdigest()
                        != batch["manifest"]["gcode_sha256"]
                    ):
                        raise ValueError("The uploaded copy does not match")
                    learning.setting(
                        "six-zone-source:" + batch["manifest"]["gcode_sha256"], batch["manifest"]
                    )
                    learning.setting(
                        "prepared_six_zone", {"filename": filename, "manifest": batch["manifest"]}
                    )
                    return {
                        "result": {
                            "filename": filename,
                            "zones": [
                                {"id": z["id"], "rate": z["volumetric_mm3_s"]}
                                for z in batch["manifest"]["zones"]
                            ],
                            "audit": batch["manifest"]["audit"],
                            "started": False,
                        }
                    }
            except HTTPException:
                raise
            except (ValueError, KeyError, TypeError, httpx.HTTPError) as error:
                raise HTTPException(
                    422,
                    "A verifiable batch could not be prepared: "
                    + (str(error) if isinstance(error, ValueError) else type(error).__name__),
                ) from None
