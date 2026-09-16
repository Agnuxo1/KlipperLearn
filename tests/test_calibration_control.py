import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from klipperlearn.calibration_control import CalibrationControlError, CalibrationController


class FakeMoonraker:
    def __init__(self) -> None:
        self.state = "standby"
        self.ready = "ready"
        self.pressure_advance = 0.025
        self.max_accel = 2500.0
        self.extrude_factor = 1.0
        self.config_max_accel = 5000.0
        self.requests: list[tuple[str, str, dict | None]] = []
        self.fail_post = False
        self.readback_override: float | None = None
        self.malformed: str | None = None
        self.malformed_after_post = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.respond)

    def respond(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, payload))
        if request.method == "POST":
            if self.fail_post:
                raise httpx.ConnectError("synthetic failure", request=request)
            script = payload["script"]
            if script.startswith("SET_PRESSURE_ADVANCE ADVANCE="):
                self.pressure_advance = float(script.split("=", 1)[1])
            elif script.startswith("SET_VELOCITY_LIMIT ACCEL="):
                self.max_accel = float(script.split("=", 1)[1])
            elif script.startswith("M221 S"):
                self.extrude_factor = float(script[6:]) / 100.0
            else:
                raise AssertionError(script)
            if self.malformed_after_post:
                self.malformed = "extruder"
            return httpx.Response(200, json={"result": "ok"})

        pressure_advance = (
            self.readback_override if self.readback_override is not None else self.pressure_advance
        )
        status = {
            "webhooks": {"state": self.ready},
            "print_stats": {"state": self.state},
            "extruder": {"pressure_advance": pressure_advance},
            "toolhead": {"max_accel": self.max_accel},
            "gcode_move": {"extrude_factor": self.extrude_factor},
            "configfile": {"settings": {"printer": {"max_accel": self.config_max_accel}}},
        }
        if self.malformed == "extruder":
            status["extruder"] = None
        return httpx.Response(
            200,
            json={"result": {"status": status}},
        )


class CalibrationControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.audit_path = Path(self.tempdir.name) / "audit.jsonl"
        self.fake = FakeMoonraker()
        self.controller = CalibrationController(
            "http://printer.invalid:7125",
            self.audit_path,
            transport=self.fake.transport(),
        )

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def _preview(self, parameter: str = "pressure_advance", value: float = 0.03):
        return await self.controller.preview(parameter, value, [0.0, 0.2], 0.005)

    def _posts(self) -> list[tuple[str, str, dict | None]]:
        return [request for request in self.fake.requests if request[0] == "POST"]

    def _audit(self) -> list[dict]:
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    async def test_apply_restore_and_replay_are_one_time(self) -> None:
        proposal = await self._preview()
        applied = await self.controller.apply(proposal["id"], confirmed=True)

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(self.fake.pressure_advance, 0.03)
        self.assertEqual(self._posts()[0][2], {"script": "SET_PRESSURE_ADVANCE ADVANCE=0.03"})

        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 1)

        restored = await self.controller.restore(proposal["id"], confirmed=True)
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(self.fake.pressure_advance, 0.025)
        self.assertEqual(self._posts()[1][2], {"script": "SET_PRESSURE_ADVANCE ADVANCE=0.025"})

        with self.assertRaises(CalibrationControlError):
            await self.controller.restore(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 2)

        events = [entry["event"] for entry in self._audit()]
        self.assertIn("attempted", events)
        self.assertGreaterEqual(events.count("applied"), 2)

    async def test_preview_contains_expected_snapshot_and_ttl(self) -> None:
        proposal = await self._preview()

        self.assertEqual(proposal["expires_in_seconds"], 60)
        self.assertEqual(proposal["expected"]["webhooks"]["state"], "ready")
        self.assertEqual(proposal["expected"]["toolhead"]["max_accel"], 2500.0)
        self.assertEqual(proposal["expected"], proposal["expected_snapshot"])

    async def test_expired_proposal_does_not_post(self) -> None:
        proposal = await self._preview()
        with patch("klipperlearn.calibration_control.time.monotonic", return_value=10_000_000):
            # Re-create a proposal under the patched clock so its expiry is known.
            self.fake.requests.clear()
            proposal = await self._preview(value=0.03)
            with patch(
                "klipperlearn.calibration_control.time.monotonic",
                return_value=10_000_061,
            ):
                with self.assertRaises(CalibrationControlError):
                    await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(self._posts(), [])

    async def test_stale_value_printing_and_paused_never_post(self) -> None:
        proposal = await self._preview()
        self.fake.pressure_advance = 0.031
        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(self._posts(), [])

        proposal = await self._preview(value=0.036)
        for state in ("printing", "paused"):
            self.fake.state = state
            with self.assertRaises(CalibrationControlError):
                await self.controller.apply(proposal["id"], confirmed=True)
            self.assertEqual(self._posts(), [])
            # Each confirmed apply consumes its proposal; make the next state
            # test with a newly read live proposal.
            self.fake.state = "standby"
            proposal = await self._preview(value=0.036)

    async def test_unsafe_inputs_and_malicious_parameter_are_rejected(self) -> None:
        for parameter, value, bounds, step in (
            ("shaper_freq_x", 40.0, [0.0, 100.0], 1.0),
            ("pressure_advance", 0.21, [0.0, 0.2], 0.005),
            ("pressure_advance", 0.03, [0.0, 1.0], 0.005),
            ("pressure_advance", 0.03, [0.0, 0.2], 0.006),
            ("pressure_advance", math.nan, [0.0, 0.2], 0.005),
        ):
            with self.assertRaises(CalibrationControlError):
                await self.controller.preview(parameter, value, bounds, step)
        self.assertEqual(self._posts(), [])

    async def test_current_outside_bounds_and_bad_config_never_post(self) -> None:
        with self.assertRaises(CalibrationControlError):
            await self.controller.preview("pressure_advance", 0.031, [0.03, 0.2], 0.005)

        self.fake.config_max_accel = math.nan
        with self.assertRaises(CalibrationControlError):
            await self.controller.preview("pressure_advance", 0.03, [0.0, 0.2], 0.005)
        self.assertEqual(self._posts(), [])

    async def test_malformed_snapshot_before_post_is_rejected(self) -> None:
        self.fake.malformed = "extruder"
        with self.assertRaises(CalibrationControlError):
            await self._preview()
        self.assertEqual(self._posts(), [])

    async def test_malformed_readback_is_uncertain_and_not_replayed(self) -> None:
        proposal = await self._preview()
        self.fake.malformed_after_post = True
        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 1)
        self.assertIn("uncertain", [entry["event"] for entry in self._audit()])

        self.fake.malformed_after_post = False
        self.fake.malformed = None
        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 1)

    async def test_proposal_capacity_purges_terminal_but_keeps_applied(self) -> None:
        for index in range(128):
            proposal = await self._preview(value=0.03)
            self.controller._proposals[proposal["id"]].state = "consumed"
        # The next preview purges consumed records and can proceed.
        proposal = await self._preview(value=0.03)
        await self.controller.apply(proposal["id"], confirmed=True)

        for index in range(127):
            extra = await self._preview(value=0.025)
            self.controller._proposals[extra["id"]].state = "consumed"
        # One applied/restorable plus 127 pending/consumed records reaches the cap
        # only after terminal records are purged; the applied record is retained.
        for record in self.controller._proposals.values():
            if record.state == "consumed":
                record.state = "pending"
                record.expires_at = math.inf
        with self.assertRaises(CalibrationControlError):
            await self._preview(value=0.02)
        self.assertIn(proposal["id"], self.controller._proposals)

    async def test_unconfirmed_has_no_network_mutation(self) -> None:
        proposal = await self._preview()
        request_count = len(self.fake.requests)
        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=False)
        self.assertEqual(len(self.fake.requests), request_count)
        self.assertEqual(self._posts(), [])

    async def test_failed_audit_blocks_post(self) -> None:
        proposal = await self._preview()
        audit_directory = Path(self.tempdir.name) / "audit-directory"
        audit_directory.mkdir()
        self.controller._audit_path = audit_directory

        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(self._posts(), [])

    async def test_apply_network_failure_is_uncertain_and_not_reused(self) -> None:
        proposal = await self._preview()
        self.fake.fail_post = True
        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 1)
        self.assertIn("uncertain", [entry["event"] for entry in self._audit()])

        self.fake.fail_post = False
        with self.assertRaises(CalibrationControlError):
            await self.controller.apply(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 1)

    async def test_restore_does_not_overwrite_external_later_change(self) -> None:
        proposal = await self._preview()
        await self.controller.apply(proposal["id"], confirmed=True)
        self.fake.pressure_advance = 0.04

        with self.assertRaises(CalibrationControlError):
            await self.controller.restore(proposal["id"], confirmed=True)
        self.assertEqual(len(self._posts()), 1)

    async def test_other_parameters_use_only_whitelisted_commands(self) -> None:
        accel = await self.controller.preview("accel_mm_s2", 2600.0, [100.0, 5000.0], 100.0)
        await self.controller.apply(accel["id"], confirmed=True)
        self.assertEqual(self._posts()[-1][2], {"script": "SET_VELOCITY_LIMIT ACCEL=2600"})

        extrusion = await self.controller.preview("extrusion_factor", 1.02, [0.8, 1.2], 0.02)
        await self.controller.apply(extrusion["id"], confirmed=True)
        self.assertEqual(self._posts()[-1][2], {"script": "M221 S102"})


if __name__ == "__main__":
    unittest.main()
