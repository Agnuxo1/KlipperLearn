"""Static checks for the sensor/photo integration in the touch console."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
MOBILE = ROOT / "src" / "klipperlearn" / "mobile_app"
STATIC = ROOT / "src" / "klipperlearn" / "static"


class ConsoleSensorAssetTests(unittest.TestCase):
    def test_mobile_assets_are_exact_copies_of_static_contracts(self):
        for name in ("trial-telemetry.js", "photo-pair.js"):
            self.assertEqual(
                (MOBILE / name).read_bytes(),
                (STATIC / name).read_bytes(),
                name,
            )

    def test_console_loads_local_assets_before_console_code(self):
        html = (MOBILE / "console.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
        names = [Path(script.split("?", 1)[0]).name for script in scripts]
        self.assertLess(names.index("trial-telemetry.js"), names.index("console.js"))
        self.assertLess(names.index("photo-pair.js"), names.index("console.js"))
        self.assertNotIn("/static/", html)

    def test_console_wires_opt_in_collection_upload_and_photo_queue(self):
        source = (MOBILE / "console.js").read_text(encoding="utf-8")
        for required in (
            "KlipperLearnTrialTelemetry",
            "requestPermissions",
            "trial-telemetry/active",
            "trial-telemetry/",
            "/snapshot",
            "KlipperLearnPhotoPair",
            "captureJob",
            "torch-off/on",
            "sensorPermissions",
        ):
            self.assertIn(required, source)

    def test_photo_queue_does_not_block_on_camera_and_restores_live_camera(self):
        source = (MOBILE / "console.js").read_text(encoding="utf-8")
        queue = re.search(
            r"async function processPhotoPairQueue\(\) \{(.*?)\n  \}\n  function setCommand",
            source,
            re.S,
        )
        self.assertIsNotNone(queue)
        body = queue.group(1)
        self.assertIn("onboardingBusy", body)
        guard = re.search(r"if \((.*?)\) \{\n      schedulePhotoPair", body, re.S)
        self.assertIsNotNone(guard)
        self.assertNotRegex(guard.group(1), r"\bcamera\b")
        self.assertIn("!cameraWanted", guard.group(1))
        self.assertNotIn("sensorActiveTrialId", guard.group(1))
        self.assertNotIn("startingCamera", guard.group(1))
        self.assertIn("const resumeLive = Boolean(camera || cameraWanted);", body)
        self.assertLess(body.index("controller.claimNext"), body.index("await stopCamera"))
        self.assertIn("if (!job) return;", body)
        self.assertIn("controller.captureJob(job, {signal})", body)
        self.assertIn(
            "if (pausedLive && resumeLive && cameraWanted && !document.hidden) await startCamera();",
            body,
        )
        self.assertNotIn("stopSensorCollector", body)

    def test_console_onboarding_is_one_gesture_and_keeps_token_internal(self):
        html = (MOBILE / "console.html").read_text(encoding="utf-8")
        source = (MOBILE / "console.js").read_text(encoding="utf-8")
        self.assertIn('id="activatePrinter"', html)
        self.assertIn(">Connect printer<", html)
        self.assertIn('id="pairingStatus"', html)
        self.assertNotIn('id="token"', html)
        self.assertNotIn("setup=samsung-1", html)
        self.assertNotIn("Mainsail", html)
        for required in (
            "activatePrinter",
            "activated: true",
            "getUserMedia",
            "sensorSources",
            "startCamera({throwOnError: true})",
            "await connectLocal()",
            "armSensorsFromGesture({onboarding: true",
            "trial-telemetry/active",
            "printer/status",
            "printer/capabilities",
            "reconnectOnboardingIfReady",
        ):
            self.assertIn(required, source)
        self.assertNotIn("tokenInput", source)

    def test_console_onboarding_is_a_full_viewport_sheet_with_visible_footer_action(self):
        html = (MOBILE / "console.html").read_text(encoding="utf-8")
        css = (MOBILE / "console.css").read_text(encoding="utf-8")
        print_card = re.search(r'<article class="print-card">(.*?)</article>', html, re.S)
        onboarding = re.search(r'<section id="onboardingCard".*?</section>', html, re.S)
        self.assertIsNotNone(print_card)
        self.assertIsNotNone(onboarding)
        self.assertNotIn('id="onboardingCard"', print_card.group(1))
        self.assertIn('role="dialog"', onboarding.group(0))
        self.assertIn('aria-modal="true"', onboarding.group(0))
        self.assertIn('class="onboarding-surface"', onboarding.group(0))
        self.assertIn('class="onboarding-footer"', onboarding.group(0))
        self.assertRegex(
            onboarding.group(0), r'class="onboarding-footer"[\s\S]*id="activatePrinter"'
        )
        self.assertRegex(
            css, r"\.onboarding-card\{[^}]*position:fixed[^}]*inset:0[^}]*z-index:1000"
        )
        self.assertIn(".onboarding-card::before", css)
        self.assertIn("backdrop-filter:blur(5px)", css)
        self.assertIn(".onboarding-body{min-height:0;overflow:auto;", css)
        self.assertIn(".onboarding-footer{position:sticky;bottom:0;", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn(".onboarding-card[hidden]{display:none!important}", css)

    def test_mobile_root_redirects_to_console_without_dropping_pair_hash(self):
        index = (MOBILE / "index.html").read_text(encoding="utf-8")
        self.assertIn("console.html", index)
        self.assertIn("window.location.hash", index)
        self.assertIn("window.location.replace(target)", index)
        self.assertNotIn('id="prepareButton"', index)

    def test_history_and_calibration_use_internal_pairing_action(self):
        history = (MOBILE / "history.js").read_text(encoding="utf-8")
        calibration = (MOBILE / "calibration-workflow.js").read_text(encoding="utf-8")
        for source in (history, calibration):
            self.assertIn("localStorage.getItem('klipperlearn-token')", source)
            self.assertIn("location.hash", source)
            self.assertIn("Connect printer", source)
            self.assertNotIn("tokenInput", source)
            self.assertNotIn("Introduce la clave local", source)


if __name__ == "__main__":
    unittest.main()
