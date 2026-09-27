#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Turn a host microphone WAV into dataset files with the phone app's own detectors:
//   node dataset_audio.mjs <input.wav> <offset_s> <trial_dir>
// offset_s = audio start minus trial start (seconds). Writes audio_features.csv,
// events.jsonl (audio events) and audio_events/*.wav into trial_dir; prints a JSON summary.
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {join, dirname} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const lib = process.env.KL_DATASET_JS || join(here, '..', 'docs', 'app', 'js', 'dataset.js');
const {TrialRecorder} = await import(pathToFileURL(lib).href);

const [wavPath, offsetArg, outDir] = process.argv.slice(2);
const buf = readFileSync(wavPath);
const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
let p = 12, rate = 16000, channels = 1, bits = 16, data = null;
while (p + 8 <= buf.length) {
  const id = buf.toString('ascii', p, p + 4);
  let size = dv.getUint32(p + 4, true);
  if (id === 'fmt ') { channels = dv.getUint16(p + 10, true); rate = dv.getUint32(p + 12, true); bits = dv.getUint16(p + 22, true); }
  if (id === 'data') {
    // arecord stopped by a signal may leave the size field unset (0 or 0xffffffff).
    if (!size || size > buf.length - p - 8) size = buf.length - p - 8;
    data = {start: p + 8, size}; break;
  }
  p += 8 + size + (size & 1);
}
if (!data || bits !== 16) throw new Error('Expected 16-bit PCM WAV');
const frames = Math.floor(data.size / (2 * channels));
const offsetMs = parseFloat(offsetArg || '0') * 1000;
const rec = new TrialRecorder({t0: 0});
const block = Math.round(rate / 10);
for (let i = 0; i < frames; i += block) {
  const n = Math.min(block, frames - i), x = new Float32Array(n);
  for (let j = 0; j < n; j++) x[j] = dv.getInt16(data.start + ((i + j) * channels) * 2, true) / 32768;
  rec.addAudio(offsetMs + ((i + n) / rate) * 1000, x, rate);
}
const parts = rec.parts();
mkdirSync(join(outDir, 'audio_events'), {recursive: true});
for (const [name, content] of Object.entries(parts)) {
  if (name === 'printer.csv' || name === 'accel.csv') continue;
  writeFileSync(join(outDir, name), content);
}
const s = rec.summary();
console.log(JSON.stringify({seconds: frames / rate, rate, frames_10hz: s.audio_frames, knocks_audio: s.knocks_audio,
  jam_suspects: s.jam_suspects, clips: rec.clips.length, dropped_clips: s.dropped.clips}));
