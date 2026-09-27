#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Convert KlipperLearn bed-trial sessions (session.json + photos + G-code + JEV files,
written by tools/klipper_bed_trials.py) into the klipperlearn-dataset/v1 layout used by
the phone app recorder:

    <out>/manifest.jsonl
    <out>/trials/<trial_id>/{meta.json, gcode_params.json, labels.json, events.jsonl,
                             program.gcode, photos/*.jpg, jev/*.json}

Only plots that were actually printed (measured.state present) become trials. Old sessions
had no accelerometer or microphone stream, so accel.csv/audio files are absent and
meta.sensors says so. An optional operator-labels JSON overrides the automatic outcome.

Usage: python migrate_bed_trials_to_dataset.py --out DATASET_DIR SESSION_DIR [SESSION_DIR ...]
       [--labels operator-labels.json]
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

SCHEMA = "klipperlearn-dataset/v1"


def created_at(gcode_name, session_name):
    m = re.search(r"(\d{8})-(\d{4})", gcode_name or "")
    if not m:
        m = re.search(r"(\d{8})", session_name)
        return dt.datetime.strptime(m.group(1), "%Y%m%d").isoformat() if m else None
    return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").isoformat()


def photo_name(fname, n):
    """plot3-mid-eye.jpg -> mid_eye.jpg; plot3-samsung.jpg -> final_samsung.jpg; others -> extra_*."""
    stem = Path(fname).stem
    rest = re.sub(rf"^(plot|p){n}-", "", stem)
    rest = rest.replace("samsung", "sam")
    if rest in ("sam", "eye"):
        return f"final_{'samsung' if rest == 'sam' else 'eye'}.jpg"
    m = re.match(r"mid-(sam|eye)$", rest)
    if m:
        return f"mid_{'samsung' if m.group(1) == 'sam' else 'eye'}.jpg"
    return f"extra_{rest.replace('-', '_')}.jpg"


def auto_labels(plot):
    a = plot.get("assessment") or {}
    if a.get("gross_failure"):
        outcome = "failure"
    elif a.get("overall") is not None:
        outcome = "success" if a["overall"] >= 3 else "failure"
    else:
        outcome = "unknown"
    return {"outcome": outcome, "overall": a.get("overall"), "surface": None, "dimensions": None,
            "defects": {}, "notes": json.dumps(a.get("defects") or {}, ensure_ascii=False) + (" " + a["notes"] if a.get("notes") else ""),
            "visual_quality": a.get("visual_quality"), "labeled_by": "agent-camera" if a else None, "labeled_at": None}


def migrate(sessions, out, overrides):
    out = Path(out)
    (out / "trials").mkdir(parents=True, exist_ok=True)
    manifest = []
    for sdir in map(Path, sessions):
        sess = json.loads((sdir / "session.json").read_text(encoding="utf-8"))
        for n, plot in sorted(sess["plots"].items(), key=lambda kv: int(kv[0])):
            measured = plot.get("measured") or {}
            if not measured.get("state"):
                continue  # prepared but never printed
            tid = f"{sdir.name}-plot{n}"
            tdir = out / "trials" / tid
            if tdir.exists():
                shutil.rmtree(tdir)
            (tdir / "photos").mkdir(parents=True)
            files = []

            gcode = sdir / plot["file"]
            source_hash = None
            if gcode.exists():
                data = gcode.read_bytes()
                source_hash = hashlib.sha256(data).hexdigest()[:16]
                shutil.copyfile(gcode, tdir / "program.gcode")
                files.append("program.gcode")

            photos = sorted(p for p in sdir.glob("*.jpg") if re.match(rf"^(plot|p){n}-", p.name))
            for p in photos:
                name = photo_name(p.name, n)
                shutil.copyfile(p, tdir / "photos" / name)
                files.append("photos/" + name)

            jev = sorted(sdir.glob(f"jev-plot{n}-*.json"))
            if jev:
                (tdir / "jev").mkdir()
                for p in jev:
                    shutil.copyfile(p, tdir / "jev" / p.name)
                    files.append("jev/" + p.name)

            labels = auto_labels(plot)
            key = f"{sdir.name}/{n}"
            ov = overrides.get(key)
            if ov:
                labels.update({k: v for k, v in ov.items() if k in ("outcome", "overall", "defects")})
                auto = labels["notes"] if labels["notes"] not in ("{}", "") else ""
                labels["notes"] = " | auto: ".join(x for x in (ov.get("cause", ""), auto) if x)
                labels["labeled_by"] = "human"
                labels["labeled_at"] = "2026-09-27"
            exclude = bool(plot.get("excluded_from_learning") or (ov or {}).get("exclude_from_param_learning"))
            labels["exclude_from_param_learning"] = exclude

            meta = {
                "schema": SCHEMA, "trial_id": tid, "created_at": created_at(plot.get("file"), sdir.name),
                "printer_id": "anycubic-4max-pro", "printer": sess.get("printer"), "firmware": "Klipper",
                "host": "moonraker (Box TV Armbian)", "session": sdir.name, "plot": int(n),
                "source": {"kind": "bed-trial", "name": plot.get("file"), "hash": source_hash, "base_file": sess.get("base_file")},
                "bbox": plot.get("bbox"), "bed_c": sess.get("bed_c"), "measured": measured,
                "score": plot.get("score"), "jev": plot.get("jev"),
                "sensors": {"camera": ["samsung_front", "ps_eye_top"], "accelerometer": False, "microphone": False,
                            "note": "migrated session: phone accelerometer/microphone were not recorded"},
                "app": {"name": "klipper_bed_trials.py", "migrated_by": "migrate_bed_trials_to_dataset.py"},
            }
            events = []
            if labels["outcome"] == "failure" and ov and ov.get("cause"):
                events.append({"t": None, "type": "operator_report", "message": ov["cause"]})
            (tdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            (tdir / "gcode_params.json").write_text(json.dumps(plot.get("params") or {}, indent=2), encoding="utf-8")
            (tdir / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")
            (tdir / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
            files = ["meta.json", "gcode_params.json", "labels.json", "events.jsonl"] + files
            manifest.append({"trial_id": tid, "schema": SCHEMA, "printer_id": meta["printer_id"], "created_at": meta["created_at"],
                             "source_hash": source_hash, "params": plot.get("params") or {}, "outcome": labels["outcome"],
                             "labels": labels, "paths": files, "provenance": "migrated:" + sdir.name})
    manifest.sort(key=lambda m: m["created_at"] or "")
    (out / "manifest.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in manifest), encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--labels", help="operator-labels JSON ({labels: {'<session>/<plot>': {...}}})")
    a = ap.parse_args()
    overrides = json.loads(Path(a.labels).read_text(encoding="utf-8"))["labels"] if a.labels else {}
    m = migrate(a.sessions, a.out, overrides)
    photos = sum(sum(1 for p in x["paths"] if p.startswith("photos/")) for x in m)
    counts = {}
    for x in m:
        counts[x["outcome"]] = counts.get(x["outcome"], 0) + 1
    print(json.dumps({"trials": len(m), "photos": photos, "outcomes": counts, "out": str(Path(a.out).resolve())}))


if __name__ == "__main__":
    main()
