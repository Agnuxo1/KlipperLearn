"""Durable preparation of bounded variants. Never edits the user's source file.

Only an explicit print request may prepare a variant. Preparation does not start
or move the machine. Ambiguous starts/restorations must not be retried blindly.
"""

import asyncio
import hashlib
import math
import re
import uuid
from urllib.parse import quote

from .adaptive_policy import compile_variant, next_experiment, source_profile, number


class AutomaticPrint:
    def __init__(self, learning):
        self.learning = learning
        self.lock = asyncio.Lock()

    def pending(self):
        return self.learning.setting("automatic_print")

    def save(self, operation):
        self.learning.setting("automatic_print", operation)
        self.learning.setting("automatic_print:" + operation["filename"], operation)

    async def download(self, client, filename):
        content = bytearray()
        async with client.stream(
            "GET", "/server/files/gcodes/" + quote(filename, safe="/")
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 8 * 1024 * 1024:
                    raise ValueError("The file exceeds the automatic trial limit of 8 MiB.")
        return bytes(content)

    def observations(self, source_sha):
        result = []
        for offset in range(0, 100000, 200):
            page = self.learning.store.recent_trials(200, offset)
            for trial in page:
                evidence = trial.get("evidence") or {}
                if trial["context"]["model_sha256"] != source_sha or not evidence.get(
                    "automatic_profile"
                ):
                    continue
                assessment = trial.get("learning") or {}
                with self.learning.db() as connection:
                    run = connection.execute(
                        "SELECT phase FROM learning_runs WHERE trial_id=?", (trial["id"],)
                    ).fetchone()
                revisions = trial.get("revisions") or []
                ratings = revisions[-1].get("ratings", {}) if revisions else {}
                result.append(
                    {
                        "trial_id": trial["id"],
                        "session_id": trial["context"]["session_id"],
                        "completed": bool(run and run["phase"] == "complete"),
                        "human_score": trial["human_score"],
                        "human_quality": (ratings.get("surface", 0) + ratings.get("geometry", 0))
                        / 2,
                        "usable_images": assessment.get("features", {}).get("eligible", False),
                        "combined_score": assessment.get("combined_score"),
                        "model_validated": assessment.get("model_validated", False),
                        "prediction_error": assessment.get("prediction_error", 100),
                        "profile": evidence["automatic_profile"],
                    }
                )
            if len(page) < 200:
                break
        return list(reversed(result))

    async def prepare(self, client, filename, state):
        run = self.learning.current_run()
        if run and run["phase"] == "finishing":
            raise ValueError("Wait for the previous trial final photographs to be saved.")
        previous = self.pending()
        if previous and previous["phase"] not in ("restored", "not_started"):
            raise ValueError(
                "The previous trial must finish and its restoration must be verified before another print."
            )
        if filename.startswith("KL-Learn-"):
            raise ValueError("Select the original file, not a generated trial variant.")
        if state["webhooks"]["state"] != "ready" or state["print_stats"]["state"] not in (
            "standby",
            "complete",
            "cancelled",
        ):
            raise ValueError("The printer is unavailable for another trial.")
        raw = await self.download(client, filename)
        source = raw.decode("utf-8-sig")
        live = {
            "pressure_advance": state["extruder"].get("pressure_advance"),
            "extrusion_factor": state["gcode_move"].get("extrude_factor"),
            "accel_mm_s2": state["toolhead"].get("max_accel"),
        }
        maximum = state["configfile"]["settings"]["printer"]["max_accel"]
        if not all(number(value) for value in [*live.values(), maximum]):
            raise ValueError("Current settings and limits could not be verified.")
        source_sha = hashlib.sha256(raw).hexdigest()
        batch = self.learning.setting("six-zone-source:" + source_sha)
        baseline = source_profile(source, live)
        decision = next_experiment(baseline, self.observations(source_sha), maximum)
        if batch:
            decision = {
                "profile": baseline,
                "kind": "six_zone_screen",
                "parameter": None,
                "adopted": False,
                "reason": "Six independent zones within one physical screening session.",
            }
        variant, audit = compile_variant(source, baseline, decision, live, maximum)
        if batch:
            variant = (
                variant.split("; KL_RESTORE_START", 1)[0]
                + "; KL_RESTORE_START\n"
                + f"M221 S{live['extrusion_factor'] * 100:.8g}\nSET_VELOCITY_LIMIT ACCEL={live['accel_mm_s2']:.8g}\nM400\n"
            )
            audit = {
                "changed": True,
                "parameter": "batch_settings",
                "motion_unchanged": True,
                "expected": {
                    "extrusion_factor": 1.0,
                    "accel_mm_s2": batch["source_spec"]["acceleration_mm_s2"],
                },
                "restore_commands": [
                    f"M221 S{live['extrusion_factor'] * 100:.8g}",
                    f"SET_VELOCITY_LIMIT ACCEL={live['accel_mm_s2']:.8g}",
                ],
            }
            # Unknown macros may override candidate settings invisibly. Do not tune
            # such files until a dedicated adapter verifies their semantics.
        if audit["changed"] and not batch:
            safe_extended = {
                "SET_PRESSURE_ADVANCE",
                "SET_VELOCITY_LIMIT",
                "SET_PRINT_STATS_INFO",
                "EXCLUDE_OBJECT_DEFINE",
                "EXCLUDE_OBJECT_START",
                "EXCLUDE_OBJECT_END",
                "BED_MESH_PROFILE",
                "BED_MESH_CLEAR",
                "SET_FAN_SPEED",
            }
            for line in source.splitlines():
                command = line.split(";", 1)[0].strip().split()
                if (
                    command
                    and not re.fullmatch(r"[GMT]\d+", command[0], re.I)
                    and command[0].upper() not in safe_extended
                ):
                    decision = {
                        "profile": baseline,
                        "kind": "baseline",
                        "parameter": None,
                        "adopted": False,
                        "reason": "Unverified macros: the baseline will be printed unchanged.",
                    }
                    variant, audit = source, {"changed": False, "motion_unchanged": True}
                    break
        identifier = uuid.uuid4().hex
        generated = "KL-Learn-" + identifier + ".gcode"
        content = ("; KlipperLearn evidence " + identifier + "\n" + variant).encode("utf-8")
        operation = {
            "id": identifier,
            "filename": generated,
            "source_filename": filename,
            "source_sha256": source_sha,
            "variant_sha256": hashlib.sha256(content).hexdigest(),
            "baseline": baseline,
            "decision": decision,
            "restore": live,
            "audit": audit,
            "phase": "preparing",
            "maximum_accel": maximum,
        }
        if batch:
            operation["batch_manifest"] = batch
            operation["source_prefix_bytes"] = len(
                ("; KlipperLearn evidence " + identifier + "\n").encode()
            )
        height = re.search(r"^;\s*max_z_height:\s*([0-9.]+)\s*$", source, re.M)
        if height:
            try:
                declared_height = float(height[1])
                if number(declared_height) and declared_height > 0:
                    operation["declared_object_height"] = declared_height
            except ValueError:
                pass
        self.save(operation)
        try:
            response = await client.post(
                "/server/files/upload",
                data={"root": "gcodes"},
                files={"file": (generated, content, "application/octet-stream")},
            )
            response.raise_for_status()
            if (
                hashlib.sha256(await self.download(client, generated)).hexdigest()
                != operation["variant_sha256"]
            ):
                raise ValueError("The trial copy does not match the verified file.")
        except Exception:
            operation["phase"] = "not_started"
            self.save(operation)
            raise
        operation["phase"] = "prepared"
        self.save(operation)
        return operation

    async def restore(self, client, state):
        operation = self.pending()
        if not operation or operation["phase"] in (
            "restored",
            "not_started",
            "preparing",
            "prepared",
        ):
            return
        stats = state["print_stats"]
        if stats.get("filename") != operation["filename"] or stats["state"] not in (
            "complete",
            "cancelled",
            "error",
        ):
            return
        if state["webhooks"]["state"] != "ready":
            return
        audit = operation["audit"]
        if not audit["changed"]:
            operation["phase"] = "restored"
            self.save(operation)
            return
        parameter = audit["parameter"]
        if parameter == "batch_settings":
            observed = {
                "extrusion_factor": state["gcode_move"].get("extrude_factor"),
                "accel_mm_s2": state["toolhead"].get("max_accel"),
            }
            if all(
                number(value) and math.isclose(value, operation["restore"][key], abs_tol=1e-6)
                for key, value in observed.items()
            ):
                operation["phase"] = "restored"
                self.save(operation)
                return
            if not all(
                number(value)
                and any(
                    math.isclose(value, v, abs_tol=1e-6)
                    for v in (audit["expected"][key], operation["restore"][key])
                )
                for key, value in observed.items()
            ):
                operation["phase"] = "restore_review_required"
                self.save(operation)
                return
            if operation["phase"] == "restore_sent":
                return
            operation["phase"] = "restore_sent"
            self.save(operation)
            response = await client.post(
                "/printer/gcode/script", json={"script": "\n".join(audit["restore_commands"])}
            )
            response.raise_for_status()
            return
        key, observed = {
            "flow_multiplier": ("extrusion_factor", state["gcode_move"].get("extrude_factor")),
            "pressure_advance": ("pressure_advance", state["extruder"].get("pressure_advance")),
            "accel_mm_s2": ("accel_mm_s2", state["toolhead"].get("max_accel")),
        }[parameter]
        original = operation["restore"][key]
        if number(observed) and math.isclose(observed, original, abs_tol=1e-6):
            operation["phase"] = "restored"
            self.save(operation)
            return
            # Only undo our exact candidate; never overwrite an unexplained setting.
        if not number(observed) or not math.isclose(observed, audit["value"], abs_tol=1e-6):
            operation["phase"] = "restore_review_required"
            self.save(operation)
            return
        if operation["phase"] == "restore_sent":
            return
        operation["phase"] = "restore_sent"
        self.save(operation)
        response = await client.post(
            "/printer/gcode/script", json={"script": "\n".join(audit["restore_commands"])}
        )
        response.raise_for_status()
        # Fresh observation on the next tick verifies the restoration. A lost
        # response cannot trigger a second command or start another print.
