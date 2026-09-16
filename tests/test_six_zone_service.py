import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.companion import install_companion


def test_preparing_six_zones_never_starts_or_moves_printer(tmp_path):
    source = b"; filament_flow_ratio = 0.98\n; filament_max_volumetric_speed = 4\nG1 X1 E1\n"
    files = {"reference.gcode": source}
    calls = []
    state = {
        "webhooks": {"state": "ready"},
        "print_stats": {"state": "complete", "filename": "reference.gcode"},
        "toolhead": {"max_accel": 1500, "axis_maximum": [270, 215, 195]},
        "extruder": {"pressure_advance": 0},
        "gcode_move": {"extrude_factor": 1},
        "configfile": {
            "settings": {
                "printer": {"kinematics": "cartesian", "max_accel": 3000, "max_velocity": 150},
                "extruder": {"nozzle_diameter": 0.4, "max_temp": 270},
                "heater_bed": {"max_temp": 120},
            }
        },
    }

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/printer/objects/query":
            return httpx.Response(200, json={"result": {"status": state}})
        if request.url.path == "/server/files/metadata":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "nozzle_diameter": 0.4,
                        "filament_type": "PLA",
                        "first_layer_extr_temp": 220,
                        "first_layer_bed_temp": 60,
                    }
                },
            )
        if request.url.path.startswith("/server/files/gcodes/"):
            return httpx.Response(200, content=files[request.url.path.rsplit("/", 1)[-1]])
        if request.url.path == "/server/files/upload":
            body = request.read()
            filename = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            files[filename] = (
                body.split(b'filename="', 1)[1].split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            )
            return httpx.Response(200, json={"result": {"item": {"path": filename}}})
        return httpx.Response(404)

    app = FastAPI()
    install_companion(
        app,
        "test",
        moonraker="http://printer",
        transport=httpx.MockTransport(respond),
        experiments_root=tmp_path,
        enable_learning=True,
        enable_automatic_print=True,
    )
    client = TestClient(app)
    assert client.post("/mobile/api/learning/six-zone/prepare", json={}).status_code == 401
    response = client.post(
        "/mobile/api/learning/six-zone/prepare", json={}, headers={"X-KlipperLearn-Token": "test"}
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result["started"]
    assert [zone["rate"] for zone in result["zones"]] == [4, 4.4, 4.8, 5.2, 5.6, 6]
    assert len(files) == 2 and files["reference.gcode"] == source
    assert not any(method == "POST" and path.startswith("/printer/") for method, path in calls)
    state["print_stats"]["state"] = "printing"
    assert (
        client.post(
            "/mobile/api/learning/six-zone/prepare",
            json={},
            headers={"X-KlipperLearn-Token": "test"},
        ).status_code
        == 409
    )


def test_automatic_preference_is_authorized_and_does_not_mutate_machine(tmp_path):
    app = FastAPI()
    install_companion(
        app, "test", experiments_root=tmp_path, enable_learning=True, enable_automatic_print=True
    )
    client = TestClient(app)
    assert client.post("/mobile/api/learning/settings", json={"enabled": False}).status_code == 401
    assert (
        client.post(
            "/mobile/api/learning/settings",
            json={"enabled": False},
            headers={"X-KlipperLearn-Token": "test"},
        ).status_code
        == 200
    )
    result = client.get(
        "/mobile/api/learning/status", headers={"X-KlipperLearn-Token": "test"}
    ).json()["result"]
    assert result["automatic_enabled"] is False
    assert (
        client.post(
            "/mobile/api/learning/settings",
            json={"enabled": "true"},
            headers={"X-KlipperLearn-Token": "test"},
        ).status_code
        == 422
    )
