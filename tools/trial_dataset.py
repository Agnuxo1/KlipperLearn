# SPDX-License-Identifier: GPL-3.0-or-later
"""Record a Klipper bed-trial plot as a klipperlearn-dataset/v1 trial folder.

Used by klipper_bed_trials.py `run --dataset DIR`:
  * printer.csv  1 Hz Moonraker telemetry (temps, heater power, position, speed, progress, layer)
  * photos/      both cameras every N layers, at half progress and at the end
  * audio        the host's USB microphone (PS Eye) recorded with arecord over SSH, then turned
                 into audio_features.csv, knock/jam events and WAV clips by the phone app's own
                 detectors (docs/app/js/dataset.js via tools/dataset_audio.mjs), so features match
  * meta.json, gcode_params.json, labels.json, events.jsonl, program.gcode, manifest.jsonl
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import time
from pathlib import Path

SCHEMA = "klipperlearn-dataset/v1"
PRINTER_COLUMNS = ["t", "hotend", "hotend_target", "hotend_power", "bed", "bed_target", "bed_power",
                   "x", "y", "z", "speed_mm_s", "speed_factor", "progress", "layer", "state"]
STATUS_QUERY = ("/printer/objects/query?extruder=temperature,target,power&heater_bed=temperature,target,power"
                "&gcode_move=gcode_position,speed,speed_factor&toolhead=position,stalls"
                "&print_stats&display_status=progress&virtual_sdcard=progress&webhooks&mcu")


class HostAudio:
    """arecord on the Klipper host through SSH; the WAV stays in /tmp (tmpfs) until fetched."""

    def __init__(self, host: str, key: Path, device: str = "plughw:1,0", remote: str = "/tmp/kl-trial.wav"):
        self.host, self.key, self.device, self.remote = host, key, device, remote
        self.proc = None
        self.started_ms = None

    def ssh(self, cmd: str, timeout: int = 30):
        return subprocess.run(["ssh", "-i", str(self.key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.host, cmd],
                               capture_output=True, text=True, timeout=timeout)

    def start(self) -> bool:
        try:
            self.ssh(f"pkill -f 'arecord .*{self.remote}' ; rm -f {self.remote}", 15)
            self.proc = subprocess.Popen(["ssh", "-i", str(self.key), "-o", "BatchMode=yes", self.host,
                                          f"exec arecord -q -D {self.device} -f S16_LE -r 16000 -c 1 {self.remote}"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.started_ms = time.time() * 1000 + 400      # typical ssh + device open latency
            return True
        except Exception as exc:  # audio is optional; the print must not depend on it
            print("audio start failed:", exc, flush=True)
            self.proc = None
            return False

    def stop_and_fetch(self, dest: Path) -> Path | None:
        if not self.proc:
            return None
        try:
            self.ssh(f"pkill -INT -f 'arecord .*{self.remote}'; sleep 1", 15)
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        try:
            r = subprocess.run(["scp", "-q", "-i", str(self.key), "-o", "BatchMode=yes", f"{self.host}:{self.remote}", str(dest)],
                               capture_output=True, text=True, timeout=300)
            self.ssh(f"rm -f {self.remote}", 15)
            return dest if r.returncode == 0 and dest.exists() else None
        except Exception as exc:
            print("audio fetch failed:", exc, flush=True)
            return None


def status_row(t: float, st: dict, layer: int | None) -> dict:
    e, b, g, th = st.get("extruder", {}), st.get("heater_bed", {}), st.get("gcode_move", {}), st.get("toolhead", {})
    pos = g.get("gcode_position") or th.get("position") or [None] * 4
    ps = st.get("print_stats", {})
    return {"t": round(t, 3), "hotend": e.get("temperature"), "hotend_target": e.get("target"), "hotend_power": e.get("power"),
            "bed": b.get("temperature"), "bed_target": b.get("target"), "bed_power": b.get("power"),
            "x": pos[0], "y": pos[1], "z": pos[2], "speed_mm_s": (g["speed"] / 60) if g.get("speed") is not None else None,
            "speed_factor": g.get("speed_factor"),
            "progress": st.get("virtual_sdcard", {}).get("progress", st.get("display_status", {}).get("progress")),
            "layer": (ps.get("info") or {}).get("current_layer") or layer, "state": ps.get("state")}


class TrialDataset:
    def __init__(self, root: Path, trial_id: str, every_layers: int = 10):
        self.root, self.trial_id, self.every = root, trial_id, every_layers
        self.dir = root / "trials" / trial_id
        if self.dir.exists():
            shutil.rmtree(self.dir)
        (self.dir / "photos").mkdir(parents=True)
        self.rows, self.events, self.photos = [], [], []
        self.t0_ms = None
        self.layer, self.last_z, self.last_state = 0, None, None

    def begin(self):
        self.t0_ms = time.time() * 1000

    def t(self) -> float:
        return (time.time() * 1000 - self.t0_ms) / 1000

    def event(self, kind: str, **data):
        self.events.append({"t": round(self.t(), 3), "type": kind, **data})

    def sample(self, st: dict) -> int | None:
        """Add one telemetry row; returns the new layer number when a layer starts."""
        ps = st.get("print_stats", {})
        state = ps.get("state")
        if state != self.last_state and self.last_state is not None and state in ("paused", "printing"):
            self.event("pause" if state == "paused" else "resume")
        if state == "error":
            self.event("error", message=ps.get("message", ""))
        self.last_state = state
        z = ((st.get("gcode_move") or {}).get("gcode_position") or [None] * 3)[2]
        new_layer = None
        cur = (ps.get("info") or {}).get("current_layer")
        if cur is not None and cur != self.layer:
            self.layer = new_layer = cur
        elif cur is None and state == "printing" and z is not None and 0 < z < 15:
            # Only extrusion heights count; the 20 mm travel lifts between plots are ignored.
            if self.last_z is None or z > self.last_z + 0.05:
                if self.last_z is not None:
                    self.layer += 1
                    new_layer = self.layer
                self.last_z = z
        self.rows.append(status_row(self.t(), st, self.layer))
        return new_layer if new_layer and new_layer % self.every == 0 else None

    def photo(self, snapshot, name: str):
        for cam, path in (("eye", "/webcam/snapshot"), ("samsung", "/samsung/snapshot")):
            fname = f"{name}_{cam}.jpg"
            try:
                snapshot(path, self.dir / "photos" / fname)
                self.photos.append({"t": round(self.t(), 3), "name": "photos/" + fname})
            except Exception as exc:
                print("photo error", fname, exc, flush=True)

    def finish(self, *, gcode: Path, params: dict, measured: dict, session: str, plot: int, audio_wav: Path | None,
               audio_offset_s: float | None, repo: Path):
        with open(self.dir / "printer.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=PRINTER_COLUMNS)
            w.writeheader()
            for r in self.rows:
                w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in PRINTER_COLUMNS})
        shutil.copyfile(gcode, self.dir / "program.gcode")
        audio_summary = None
        if audio_wav:
            (self.dir / "audio_events").mkdir(exist_ok=True)
            try:
                r = subprocess.run(["node", str(repo / "tools" / "dataset_audio.mjs"), str(audio_wav), str(audio_offset_s or 0), str(self.dir)],
                                   capture_output=True, text=True, timeout=900)
                audio_summary = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {"error": r.stderr[-500:]}
            except Exception as exc:
                audio_summary = {"error": str(exc)}
            (self.dir / "audio_raw").mkdir(exist_ok=True)
            shutil.move(str(audio_wav), self.dir / "audio_raw" / "host_mic_16k.wav")
        events = list(self.events)
        ev_file = self.dir / "events.jsonl"
        if ev_file.exists():                              # audio events written by dataset_audio.mjs
            events += [json.loads(l) for l in ev_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        events.sort(key=lambda e: (e.get("t") is None, e.get("t") or 0))
        ev_file.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        meta = {"schema": SCHEMA, "trial_id": self.trial_id, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.t0_ms / 1000)),
                "printer_id": "anycubic-4max-pro", "printer": "Anycubic 4Max Pro (Klipper)", "firmware": "Klipper",
                "host": "moonraker (Box TV Armbian)", "session": session, "plot": plot,
                "source": {"kind": "bed-trial", "name": gcode.name}, "measured": measured,
                "sensors": {"camera": ["ps_eye_top", "samsung_front"], "microphone": "PS Eye on the Klipper host (16 kHz mono)" if audio_wav else False,
                            "accelerometer": False, "audio_offset_s": audio_offset_s, "audio": audio_summary,
                            "printer_rows": len(self.rows), "photos": len(self.photos)},
                "photos": self.photos, "app": {"name": "klipper_bed_trials.py", "recorder": "trial_dataset.py"}}
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.dir / "gcode_params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")
        write_labels(self.dir, measured=measured)
        rebuild_manifest(self.root)
        return meta


def write_labels(tdir: Path, measured: dict | None = None, assessment: dict | None = None):
    f = tdir / "labels.json"
    labels = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {
        "outcome": "unknown", "overall": None, "surface": None, "dimensions": None, "defects": {}, "notes": "",
        "labeled_by": None, "labeled_at": None}
    if measured and measured.get("state") not in (None, "complete") and labels["outcome"] == "unknown":
        labels.update({"outcome": "failure", "labeled_by": "printer", "notes": f"print ended {measured.get('state')}"})
    if assessment and labels.get("labeled_by") != "human":
        gross = assessment.get("gross_failure")
        overall = assessment.get("overall")
        labels.update({"outcome": "failure" if gross or (overall is not None and overall < 3) else "success",
                       "overall": overall, "notes": json.dumps(assessment.get("defects") or {}, ensure_ascii=False),
                       "visual_quality": assessment.get("visual_quality"), "labeled_by": "agent-camera",
                       "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    f.write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")


def rebuild_manifest(root: Path):
    lines = []
    for tdir in sorted((root / "trials").iterdir()):
        meta_f = tdir / "meta.json"
        if not meta_f.exists():
            continue
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        labels = json.loads((tdir / "labels.json").read_text(encoding="utf-8")) if (tdir / "labels.json").exists() else {}
        params = json.loads((tdir / "gcode_params.json").read_text(encoding="utf-8")) if (tdir / "gcode_params.json").exists() else {}
        paths = sorted(str(p.relative_to(tdir)).replace("\\", "/") for p in tdir.rglob("*") if p.is_file())
        lines.append({"trial_id": meta["trial_id"], "schema": SCHEMA, "printer_id": meta.get("printer_id"),
                      "created_at": meta.get("created_at"), "source_hash": (meta.get("source") or {}).get("hash"),
                      "params": params, "outcome": labels.get("outcome", "unknown"), "labels": labels, "paths": paths,
                      "provenance": "klipper_bed_trials" if meta.get("app", {}).get("recorder") else "migrated:" + str(meta.get("session"))})
    lines.sort(key=lambda m: m.get("created_at") or "")
    (root / "manifest.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in lines), encoding="utf-8")
