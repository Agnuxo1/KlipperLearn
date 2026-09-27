#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start a G-code file already on the Klipper host (or upload a local one) and record it as a
klipperlearn-dataset/v1 trial: telemetry, both cameras, host microphone with knock/jam detection.

  python record_klipper_job.py --gcode local.gcode --trial-id ID --dataset DIR [--audio-host root@HOST]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from pathlib import Path

from klipper_bed_trials import Moonraker
from trial_dataset import HostAudio, TrialDataset


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://192.168.0.16")
    ap.add_argument("--gcode", type=Path, required=True, help="local copy; uploaded under the same name")
    ap.add_argument("--trial-id", required=True)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--audio-host")
    ap.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh" / "md08tv_codex_ed25519")
    ap.add_argument("--poll", type=float, default=0.5)
    ap.add_argument("--kind", default="motion-diagnostic")
    a = ap.parse_args()

    mr = Moonraker(a.url)
    st = mr.status()
    if st["print_stats"]["state"] in ("printing", "paused") or st["webhooks"]["state"] != "ready":
        raise SystemExit("Printer busy or not ready")
    mr.upload(a.gcode.name, a.gcode.read_bytes())
    ds = TrialDataset(a.dataset, a.trial_id, every_layers=10**9)
    audio = HostAudio(a.audio_host, a.ssh_key) if a.audio_host else None
    if audio:
        audio.start()
        time.sleep(1.0)
    mr.post("/printer/print/start?filename=" + urllib.parse.quote(a.gcode.name))
    ds.begin()
    ds.photo(mr.snapshot, "start")
    seen, t0 = False, time.time()
    while True:
        time.sleep(a.poll)
        try:
            st = mr.status()
        except Exception as exc:
            print("poll error", exc, flush=True)
            continue
        ds.sample(st)
        s = st["print_stats"]["state"]
        seen |= s in ("printing", "paused")
        if (seen and s in ("complete", "cancelled", "error")) or (not seen and time.time() - t0 > 60):
            break
    ps = st["print_stats"]
    measured = {"state": ps["state"], "message": ps.get("message", ""), "total_duration_s": round(ps["total_duration"], 1),
                "planner_stalls": st["toolhead"].get("stalls", 0)}
    ds.photo(mr.snapshot, "final")
    wav = audio.stop_and_fetch(ds.dir / "host_mic.wav") if audio else None
    offset = (audio.started_ms - ds.t0_ms) / 1000 if audio else None
    meta = ds.finish(gcode=a.gcode, params={"kind": a.kind}, measured=measured, session=a.kind, plot=0,
                     audio_wav=wav, audio_offset_s=offset, repo=Path(__file__).resolve().parents[1])
    print(json.dumps({"measured": measured, "sensors": meta["sensors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
