#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Supervised six-plot bed session for a Klipper printer, with JEV choosing one change per plot.

The same sliced calibration card is shifted to one of six independent bed plots per trial.
Each trial applies the current parameters with native Klipper commands, prints, is
measured (Moonraker status, temperatures, camera snapshots) and assessed. JEV then
chooses exactly one bounded candidate built by this tool for the next plot.

Subcommands (run in order for plots 1..6):
  prepare  N   -> write plot N G-code from the base card and the session parameters
  run      N   -> upload, start and monitor plot N; save measurements and snapshots
  decide   N   -> read the assessment of plot N, ask JEV, store parameters for N+1
  status       -> print session state

Only standard library. Nothing here writes printer.cfg or EEPROM-like state; all
settings are runtime commands inside each trial file and END_PRINT turns heaters off.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from klipperlearn.jev_adapter import PARAMETER_LIMITS, build_decision_request, parse_jev_response  # noqa: E402

BRIDGE = Path(r"D:\PROJECTS\.cognition\jev_health_bridge.py")
BASE_CENTER = (135.0, 107.5)          # centre of the card in the sliced base file
TRAVEL_Z = 20.0                       # safe height above finished 12 mm cards
CONFIG_ACCEL = 1000.0                 # startup max_accel in printer config
ACCEL_CAP = 2000.0                    # hard cap enforced by config/klipper/klipperlearn-limits.cfg

# 3 x 2 grid inside the printable area, away from the X/Y homing corner (-8, -1).
PLOTS = {1: (50.0, 55.0), 2: (135.0, 55.0), 3: (220.0, 55.0),
         4: (50.0, 160.0), 5: (135.0, 160.0), 6: (220.0, 160.0)}

BASELINE = {"hotend_temp_c": 220.0, "speed_factor_pct": 100.0, "accel_mm_s2": 5000.0,
            "pressure_advance": 0.0, "fan_percent": 0.0, "extrusion_factor": 1.0}
BED_C = 50.0
BRIDGE_TYPES = (";TYPE:Bridge", ";TYPE:Internal Bridge", ";TYPE:Overhang wall")
BRIDGE_FAN_PCT = 100.0                # JEV 0.91: full part cooling on bridges and overhang walls

# One-step candidate moves offered to JEV (never more than the adapter step limit).
MOVES = {
    "speed_factor_pct": 25.0, "accel_mm_s2": 250.0, "pressure_advance": 0.02,
    "hotend_temp_c": 5.0, "fan_percent": 50.0, "extrusion_factor": 0.02, "bridge_speed_mm_s": 5.0,
}


# ------------------------------------------------------------------ session files
def session_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_state(root: Path) -> dict:
    f = root / "session.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"schema": "klipperlearn.bed-session/v1", "printer": "Anycubic 4Max Pro (Klipper)",
            "base_file": None, "bed_c": BED_C, "plots": {}, "params": {"1": dict(BASELINE)}}


def save_state(root: Path, state: dict) -> None:
    tmp = root / "session.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(root / "session.json")


# ------------------------------------------------------------------ G-code transform
_XY = re.compile(r"\b([XY])(-?\d*\.?\d+)")


def shift_line(line: str, dx: float, dy: float) -> str:
    if not re.match(r"^G[0123]\b", line):
        return line
    code, sep, comment = line.partition(";")
    code = _XY.sub(lambda m: f"{m.group(1)}{float(m.group(2)) + (dx if m.group(1) == 'X' else dy):.3f}", code)
    return code + (sep + comment if sep else "")


def build_plot(base_lines: list[str], plot: int, p: dict, bed_c: float, total_plots: int = 6) -> list[str]:
    cx, cy = PLOTS[plot]
    dx, dy = cx - BASE_CENTER[0], cy - BASE_CENTER[1]
    temp = round(p["hotend_temp_c"])
    fan_s = round(255 * p["fan_percent"] / 100)
    out: list[str] = []
    layer = 0
    in_body = False
    # Bridge/overhang handling: full fan and an absolute bridge speed (compensating M220).
    bridge_speed = p.get("bridge_speed_mm_s")
    bridge_f = round(bridge_speed * 60 * 100 / p["speed_factor_pct"]) if bridge_speed else None
    in_bridge = restore_f = False
    modal_f = None
    for raw in base_lines:
        line = raw.rstrip("\n")
        low = line.lower()
        fm = re.match(r"^G[0123]\b.*\bF(\d+\.?\d*)", line.partition(";")[0])
        if in_body and bridge_f and line.startswith(";TYPE:"):
            entering = line.startswith(BRIDGE_TYPES)
            if entering and not in_bridge:
                out += [line, f"M106 S{round(255 * BRIDGE_FAN_PCT / 100)} ; KlipperLearn bridge/overhang fan"]
                in_bridge = True
                continue
            if not entering and in_bridge:
                out += [f"M106 S{fan_s if layer >= 3 else 0} ; KlipperLearn restore trial fan", line]
                in_bridge, restore_f = False, True
                continue
        code_part = line.partition(";")[0]
        if (in_bridge and re.match(r"^G[123]\b", code_part) and re.search(r"\b[XY]-?\d", code_part)
                and re.search(r"\bE\.?\d", code_part)):              # extruding moves only, not retract/wipe
            code = re.sub(r"\s*\bF\d+\.?\d*", "", line.partition(";")[0]).rstrip()
            out.append(shift_line(f"{code} F{bridge_f}", dx, dy))
            if fm:
                modal_f = fm.group(1)
            continue
        if restore_f and re.match(r"^G[0123]\b", line):
            if not fm and modal_f:
                line = f"{line.partition(';')[0].rstrip()} F{modal_f}"
            restore_f = False
        if fm:
            modal_f = fm.group(1)
        if low.startswith(("m109 ", "m104 ")):
            out.append(f"M109 S{temp}" if low.startswith("m109") else f"M104 S{temp}")
            continue
        if low.startswith(("m140 ", "m190 ")):
            out.append(f"{line.split()[0].upper()} S{round(bed_c)}")
            continue
        if line.startswith("START_PRINT"):
            out += [
                f"; KlipperLearn bed session - plot {plot}/{total_plots} at X{cx} Y{cy}",
                "SET_IDLE_TIMEOUT TIMEOUT=3600",
                f"START_PRINT BED_TEMP={round(bed_c)} EXTRUDER_TEMP={temp}",
                "G90",
                f"G1 Z{TRAVEL_Z} F600 ; clear earlier plots before any XY move",
                f"SET_VELOCITY_LIMIT ACCEL={round(p['accel_mm_s2'])} MINIMUM_CRUISE_RATIO=0.5",
                f"SET_PRESSURE_ADVANCE ADVANCE={p['pressure_advance']:.4f}",
                f"M220 S{round(p['speed_factor_pct'])}",
                f"M221 S{round(p['extrusion_factor'] * 100)}",
            ]
            in_body = True
            continue
        if line.startswith(";LAYER_CHANGE"):
            layer += 1
            out.append(line)
            if layer == 3 and fan_s > 0:
                out.append(f"M106 S{fan_s} ; KlipperLearn part fan from layer 3")
            continue
        if line.startswith("M106") and in_body:
            continue                               # the trial controls the fan
        if line.startswith("END_PRINT"):
            out += ["M220 S100", "M221 S100", "SET_PRESSURE_ADVANCE ADVANCE=0",
                    f"SET_VELOCITY_LIMIT ACCEL={round(CONFIG_ACCEL)}", "END_PRINT",
                    "G90", f"G1 Z{TRAVEL_Z + 5} F600", "G1 X260 Y210 F6000 ; park so the front camera sees the bed"]
            continue
        out.append(shift_line(line, dx, dy) if in_body else line)
    return out


def check_bounds(lines: list[str], xmin=0.0, xmax=270.0, ymin=0.0, ymax=215.0) -> tuple[float, float, float, float]:
    xs, ys = [], []
    in_body = False
    for l in lines:
        if l.startswith("START_PRINT"):
            in_body = True
        if not in_body or not l.startswith(("G0", "G1", "G2", "G3")):
            continue
        for m in _XY.finditer(l.partition(";")[0]):
            (xs if m.group(1) == "X" else ys).append(float(m.group(2)))
    box = (min(xs), max(xs), min(ys), max(ys))
    if box[0] < xmin or box[1] > xmax or box[2] < ymin or box[3] > ymax:
        raise SystemExit(f"Plot outside printable area: {box}")
    return box


# ------------------------------------------------------------------ Moonraker
class Moonraker:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def get(self, path: str, timeout=10):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return json.loads(r.read())["result"]

    def post(self, path: str, timeout=15):
        req = urllib.request.Request(self.base + path, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["result"]

    def upload(self, name: str, data: bytes):
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"root\"\r\n\r\ngcodes\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + "/server/files/upload", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def status(self):
        q = "print_stats&extruder&heater_bed&toolhead&webhooks&display_status&fan&mcu"
        return self.get(f"/printer/objects/query?{q}")["status"]

    def snapshot(self, path: str, dest: Path):
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            dest.write_bytes(r.read())


# ------------------------------------------------------------------ commands
def cmd_prepare(args, state):
    root = args.session
    base = Path(state.get("base_file") or args.base)
    state["base_file"] = str(base)
    p = state["params"][str(args.plot)]
    lines = build_plot(base.read_text(encoding="utf-8").splitlines(), args.plot, p, state["bed_c"])
    box = check_bounds(lines)
    name = f"KL-bed-plot{args.plot}-{time.strftime('%Y%m%d-%H%M')}.gcode"
    (root / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    state["plots"].setdefault(str(args.plot), {}).update({"file": name, "params": p, "bbox": box})
    save_state(root, state)
    print(json.dumps({"plot": args.plot, "file": name, "params": p, "bbox": box}))


def cmd_run(args, state):
    root, mr = args.session, Moonraker(args.url)
    entry = state["plots"][str(args.plot)]
    st = mr.status()
    if st["print_stats"]["state"] in ("printing", "paused"):
        raise SystemExit("Printer is busy; refusing to start.")
    if st["webhooks"]["state"] != "ready":
        raise SystemExit("Klipper is not ready: " + st["webhooks"].get("state_message", ""))
    # Preflight (JEV 1.0 after an empty print): refuse to start without detected filament.
    sensor = mr.get("/printer/objects/query?filament_switch_sensor%20filament_sensor")["status"].get(
        "filament_switch_sensor filament_sensor")
    # The Anycubic has no physical sensor fitted (config stub reads "no filament" forever):
    # session.json "filament_sensor_installed": false disables this check.
    if (state.get("filament_sensor_installed", True) and sensor is not None and sensor.get("enabled")
            and not sensor.get("filament_detected")
            and not getattr(args, "allow_no_filament", False)):
        raise SystemExit("Preflight failed: the filament sensor reports no filament. Load filament and purge first.")
    data = (root / entry["file"]).read_bytes()
    mr.upload(entry["file"], data)
    mr.post("/printer/print/start?filename=" + urllib.parse.quote(entry["file"]))
    started = time.time()
    samples, max_dev, last_print = [], 0.0, None
    powers, mid_shot = [], False
    mcu0 = (st.get("mcu") or {}).get("last_stats", {})
    stalls0 = st["toolhead"].get("stalls", 0)
    while True:
        time.sleep(5)
        try:
            st = mr.status()
        except Exception as exc:                            # transient network hiccup
            print("poll error", exc, flush=True)
            continue
        ps, ex, bed = st["print_stats"], st["extruder"], st["heater_bed"]
        state_now = ps["state"]
        if state_now == "printing" and ps["print_duration"] > 30 and ex["target"] > 0:
            dev = abs(ex["temperature"] - ex["target"])
            max_dev = max(max_dev, dev)
            samples.append(round(dev, 2))
            powers.append(ex.get("power", 0.0))
        if not mid_shot and st.get("display_status", {}).get("progress", 0) >= 0.5:
            try:
                mr.snapshot("/webcam/snapshot", root / f"plot{args.plot}-mid-eye.jpg")
                mr.snapshot("/samsung/snapshot", root / f"plot{args.plot}-mid-samsung.jpg")
            except Exception as exc:
                print("mid snapshot error", exc, flush=True)
            mid_shot = True
        if last_print != state_now or int(time.time() - started) % 60 < 5:
            prog = st.get("display_status", {}).get("progress", 0)
            print(f"[{int(time.time() - started)}s] {state_now} {prog * 100:.0f}% T={ex['temperature']:.1f}/{ex['target']:.0f} "
                  f"B={bed['temperature']:.1f}/{bed['target']:.0f} Z={st['toolhead']['position'][2]:.2f}", flush=True)
            last_print = state_now
        if state_now in ("complete", "cancelled", "error") or (state_now == "standby" and time.time() - started > 60):
            break
    time.sleep(12)                                          # let END_PRINT park the head
    shots = {}
    for cam, path in (("samsung", "/samsung/snapshot"), ("eye", "/webcam/snapshot")):
        dest = root / f"plot{args.plot}-{cam}.jpg"
        try:
            mr.snapshot(path, dest)
            shots[cam] = dest.name
        except Exception as exc:
            shots[cam] = f"error: {exc}"
    measured = {"state": state_now, "message": ps.get("message", ""), "print_duration_s": round(ps["print_duration"], 1),
                "total_duration_s": round(ps["total_duration"], 1), "filament_mm": round(ps["filament_used"], 1),
                "max_temp_dev_c": round(max_dev, 2),
                "mean_temp_dev_c": round(sum(samples) / len(samples), 2) if samples else None, "snapshots": shots}
    mcu1 = (st.get("mcu") or {}).get("last_stats", {})
    measured.update({
        "max_heater_power": round(max(powers), 3) if powers else None,
        "mean_heater_power": round(sum(powers) / len(powers), 3) if powers else None,
        "planner_stalls": st["toolhead"].get("stalls", 0) - stalls0,
        "mcu_retransmit_bytes": mcu1.get("bytes_retransmit", 0) - mcu0.get("bytes_retransmit", 0),
        "mcu_invalid_bytes": mcu1.get("bytes_invalid", 0) - mcu0.get("bytes_invalid", 0),
        "phone_sensors": "camera only (accelerometer/microphone need the companion pairing token, not used)"})
    # Re-read the session so edits made while this plot printed are not overwritten.
    fresh = load_state(root)
    fresh["plots"].setdefault(str(args.plot), {}).update({**entry, "measured": measured})
    save_state(root, fresh)
    print(json.dumps(measured))


def measured_score(m: dict, ref: dict | None) -> float:
    parts = [(1.0 if m["state"] == "complete" else 0.0, 0.4)]
    if ref and m.get("print_duration_s") and ref.get("print_duration_s"):
        speedup = ref["print_duration_s"] / m["print_duration_s"]
        parts.append((min(1.0, max(0.0, 0.5 + (speedup - 1) * 1.5)), 0.4))
    # JEV (0.61): judge hotend stability by mean deviation; fan-start transients are expected.
    if m.get("mean_temp_dev_c") is not None:
        parts.append((min(1.0, max(0.0, 1 - m["mean_temp_dev_c"] / 2)), 0.2))
    w = sum(x for _, x in parts)
    return sum(v * x for v, x in parts) / w


def candidates_for(p: dict, assessment: dict) -> list[dict]:
    notes = assessment.get("defects", {})
    cands = []
    for param, step in MOVES.items():
        lo, hi, limit = PARAMETER_LIMITS[param]
        if param == "accel_mm_s2":
            hi = ACCEL_CAP                             # never above the operator hard cap
        for sign in (+1, -1):
            value = round(min(hi, max(lo, p[param] + sign * step)), 4)
            if value == p[param]:
                continue
            desc = (f"{'Increase' if sign > 0 else 'Decrease'} {param} from {p[param]} to {value} for the next plot "
                    f"(only this change). Observed defects: {json.dumps(notes)}.")
            cands.append({"id": f"{param}_{'up' if sign > 0 else 'down'}", "parameter": param, "value": value,
                          "bounds": [lo, hi], "maximum_step": min(limit, abs(step)), "description": desc[:512]})
    cands.append({"id": "no_change", "parameter": None, "value": None, "bounds": None, "maximum_step": 0.0,
                  "description": "Repeat the same parameters on the next plot (replicate) because evidence is insufficient or unsafe."})
    return cands


def ask_jev(root: Path, plot: int, request: dict) -> dict:
    state_file = root / f"jev-plot{plot}-state.json"
    questions_file = root / f"jev-plot{plot}-questions.json"
    state_file.write_text(json.dumps(request["state"], ensure_ascii=False), encoding="utf-8")
    questions_file.write_text(json.dumps(request["questions"], ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(BRIDGE), "v2-query", "--state-file", str(state_file),
                           "--questions-file", str(questions_file)], capture_output=True, text=True, timeout=180)
    line = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")][-1]
    res = json.loads(line)
    (root / f"jev-plot{plot}-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    if res.get("provenance") != "jev" or res.get("exit_code") != 0:
        raise SystemExit(f"JEV not available (provenance={res.get('provenance')}); no change applied.")
    d = res["decisions"]
    answers = {"candidate": {"type": "choice", "choice": d["candidate"]["value"], "confidence": d["candidate"]["confidence"]},
               "accept": {"type": "noul", "noul": float(d["accept"]["value"]) if not isinstance(d["accept"]["value"], bool)
                          else (1.0 if d["accept"]["value"] else 0.0)}}
    return {"answers": answers, "model": res.get("model")}


def cmd_decide(args, state):
    root = args.session
    key = str(args.plot)
    entry = state["plots"][key]
    assessment = json.loads(Path(args.assessment).read_text(encoding="utf-8"))
    entry["assessment"] = assessment
    ref = state["plots"].get("1", {}).get("measured")
    m_score = measured_score(entry["measured"], ref)
    v_score = (assessment["overall"] - 1) / 4
    entry["score"] = {"measured": round(m_score, 3), "visual": round(v_score, 3),
                      "total": round(0.4 * m_score + 0.6 * v_score, 3)}
    for other in state["plots"].values():                   # keep every plot on the same metric
        if other.get("assessment") and other.get("measured") and other is not entry:
            ms = measured_score(other["measured"], ref)
            vs = (other["assessment"]["overall"] - 1) / 4
            other["score"] = {"measured": round(ms, 3), "visual": round(vs, 3), "total": round(0.4 * ms + 0.6 * vs, 3)}
    p = entry["params"]
    history = [{"plot": int(k), "params": v["params"], "measured": v.get("measured"), "assessment": v.get("assessment"),
                "score": v.get("score"), "jev": v.get("jev", {}).get("candidate_id")}
               for k, v in sorted(state["plots"].items(), key=lambda kv: int(kv[0])) if v.get("score")]
    jev_state = {
        "task": "Six supervised trials of the same calibration card on independent bed plots of an Anycubic 4Max Pro "
                "running Klipper. Goal: highest speed with good quality. Change exactly one parameter per plot.",
        "plots_remaining": 6 - args.plot,
        "scoring": "total = 0.4 measured (completion, print time vs plot 1, temperature stability) + 0.6 visual rating (1-5) "
                   "from camera snapshots assessed by the supervising agent; the operator stands by the emergency stop.",
        "machine": {"max_velocity": 250, "max_accel_config": CONFIG_ACCEL, "accel_hard_cap": ACCEL_CAP, "max_accel_history": "plots 1-4 ran at 5000 (config before operator correction)", "extruder": "direct drive, 0.4 mm nozzle, PLA",
                    "slicer_limits": "base card sliced with 4 mm3/s max volumetric speed (~33-47 mm/s walls), fan off; bridges and overhang walls now get 100 % fan and bridge_speed_mm_s"},
        "assessment_protocol": state.get("assessment_protocol"),
        "change_policy": state.get("change_policy"),
        "current_params": p, "history": history,
    }
    cands = candidates_for(p, assessment)
    request = build_decision_request(jev_state, cands)
    decision = parse_jev_response(ask_jev(root, args.plot, request), cands)
    entry["jev"] = decision
    nxt = dict(p)
    if decision["status"] == "candidate":
        c = decision["candidate"]
        nxt[c["parameter"]] = c["value"]
    if args.plot < 6:
        state["params"][str(args.plot + 1)] = nxt
    save_state(root, state)
    print(json.dumps({"score": entry["score"], "decision": decision, "next_params": nxt}, indent=2))


def cmd_status(args, state):
    print(json.dumps(state, indent=2, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=Path, required=True)
    ap.add_argument("--url", default="http://192.168.0.16")
    ap.add_argument("--base", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "run", "decide"):
        s = sub.add_parser(name)
        s.add_argument("plot", type=int, choices=range(1, 7))
        if name == "decide":
            s.add_argument("--assessment", required=True)
        if name == "run":
            s.add_argument("--allow-no-filament", action="store_true",
                           help="one-time operator-requested diagnostic run despite the filament sensor")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    args.session = session_dir(args.session)
    state = load_state(args.session)
    {"prepare": cmd_prepare, "run": cmd_run, "decide": cmd_decide, "status": cmd_status}[args.cmd](args, state)


if __name__ == "__main__":
    main()
