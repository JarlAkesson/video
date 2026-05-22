#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np


NOTE_TO_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pitch_to_hz(pitch: str) -> float:
    # Supports e.g. C4, F#3, Bb5.
    pitch = pitch.strip()
    if pitch.upper() in {"R", "REST"}:
        return 0.0
    m = None
    for i, ch in enumerate(pitch):
        if ch.isdigit() or ch == "-":
            m = i
            break
    if m is None:
        raise ValueError(f"Unparseable pitch {pitch!r}")
    name = pitch[:m]
    octave = int(pitch[m:])
    step = name[0].upper()
    acc = name[1:]
    alter = 0
    if acc == "#":
        alter = 1
    elif acc.lower() == "b":
        alter = -1
    midi = 12 * (octave + 1) + NOTE_TO_PC[step] + alter
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _dbfs_from_int16_peak(peak: int) -> float:
    if peak <= 0:
        return float("-inf")
    return 20.0 * math.log10(peak / 32767.0)


def _write_wav(path: Path, samples: np.ndarray, sr: int) -> None:
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("vocal_events_json", type=Path)
    ap.add_argument("--model", type=str, default=None)
    ap.add_argument("--language", default="English")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--debug-out", type=Path, required=True)
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--backend", choices=["auto", "simple_synth", "openvpi_diffsinger"], default="auto")
    ap.add_argument("--diffsinger-root", type=Path, default=Path("third_party/DiffSinger"))
    ap.add_argument("--variance-exp", type=str, default=None)
    ap.add_argument("--acoustic-exp", type=str, default=None)
    ap.add_argument("--diffsinger-lang", type=str, default=None)
    ap.add_argument("--diffsinger-spk", type=str, default=None)
    ap.add_argument("--sample-rate", type=int, default=44100)
    args = ap.parse_args()

    ve = _load_json(args.vocal_events_json)
    tempo_bpm = float(ve["global"]["tempo_bpm"])
    events = ve["vocal_events"]

    # Build a DS-like debug object from backend-independent vocal_events.
    sr = int(args.sample_rate)

    starts_sec = []
    durs_sec = []
    freqs = []
    is_slur = []
    lyrics = []
    for ev in events:
        start = (float(ev["measure"]) - 1.0) * 4.0 + (float(ev["start_beat"]) - 1.0)
        dur_beats = float(ev["duration_beats"])
        start_sec = start * 60.0 / tempo_bpm
        dur_sec = dur_beats * 60.0 / tempo_bpm
        starts_sec.append(start_sec)
        durs_sec.append(dur_sec)
        freqs.append(_pitch_to_hz(ev["pitch"]))
        is_slur.append(bool(ev["is_slur"]))
        lyrics.append(str(ev["lyric"]))

    ds_param = {
        # Minimal DS fields needed by DiffSinger inference.
        # We do not attempt true G2P here yet; we provide a trivial phoneme sequence.
        "ph_seq": " ".join(["a"] * len(events)),
        "ph_num": " ".join(["1"] * len(events)),
        "note_seq": " ".join([ev["pitch"] for ev in events]),
        "note_dur": " ".join([f"{float(ev['duration_beats']) * 60.0 / tempo_bpm:.3f}" for ev in events]),
        "note_slur": " ".join(["1" if ev["is_slur"] else "0" for ev in events]),
    }
    if args.diffsinger_lang:
        ds_param["lang"] = args.diffsinger_lang

    args.debug_out.parent.mkdir(parents=True, exist_ok=True)
    args.debug_out.write_text(
        json.dumps(
            {
                "text": " ".join([w for w in lyrics if w]),
                "ph_seq": ds_param["ph_seq"],
                "note_seq": ds_param["note_seq"],
                "note_dur_seq": ds_param["note_dur"],
                "is_slur_seq": ds_param["note_slur"],
                "input_type": "phoneme",
                "metadata": {
                    "backend": args.backend,
                    "note": "DS adapter fields generated from vocal_events.json",
                },
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    diffsinger_root = args.diffsinger_root
    diffsinger_infer = diffsinger_root / "scripts" / "infer.py"
    checkpoints_dir = diffsinger_root / "checkpoints"
    have_openvpi = diffsinger_infer.exists() and checkpoints_dir.exists()

    requested_openvpi = args.backend in {"auto", "openvpi_diffsinger"}
    can_try_openvpi = (
        requested_openvpi
        and have_openvpi
        and args.variance_exp
        and args.acoustic_exp
        and (checkpoints_dir / args.variance_exp).exists()
        and (checkpoints_dir / args.acoustic_exp).exists()
    )

    # If auto: try OpenVPI DiffSinger only when exps exist; otherwise fall back.
    if args.backend == "openvpi_diffsinger" and not can_try_openvpi:
        raise SystemExit(
            "OpenVPI DiffSinger backend requested, but required checkpoints are missing.\n"
            f"- diffsinger_root: {diffsinger_root}\n"
            f"- expected variance exp dir: {checkpoints_dir / str(args.variance_exp)}\n"
            f"- expected acoustic exp dir: {checkpoints_dir / str(args.acoustic_exp)}\n"
            "Provide `--variance-exp` and `--acoustic-exp` that exist under the checkpoints directory."
        )

    if can_try_openvpi:
        # Run variance then acoustic inference on the generated DS file.
        ds_path = args.out.with_suffix(".ds.json")
        ds_path.parent.mkdir(parents=True, exist_ok=True)
        ds_path.write_text(json.dumps(ds_param, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(diffsinger_root)
        infer_base = [str(diffsinger_infer)]

        var_cmd = [infer_base[0], "variance", str(ds_path), "--exp", args.variance_exp, "--out", str(ds_path.parent)]
        if args.diffsinger_spk:
            var_cmd += ["--spk", args.diffsinger_spk]
        if args.diffsinger_lang:
            var_cmd += ["--lang", args.diffsinger_lang]

        subprocess.run([sys.executable, *var_cmd], check=True, env=env)  # type: ignore[name-defined]

        variance_out = ds_path.parent / (ds_path.stem + "_variance.json")
        if not variance_out.exists():
            # Fallback to original if naming differs.
            variance_out = ds_path

        ac_cmd = [infer_base[0], "acoustic", str(variance_out), "--exp", args.acoustic_exp, "--out", str(args.out.parent)]
        if args.diffsinger_spk:
            ac_cmd += ["--spk", args.diffsinger_spk]
        if args.diffsinger_lang:
            ac_cmd += ["--lang", args.diffsinger_lang]
        ac_cmd += ["--title", args.out.stem]

        subprocess.run([sys.executable, *ac_cmd], check=True, env=env)  # type: ignore[name-defined]

        produced = args.out.parent / f"{args.out.stem}.wav"
        if not produced.exists():
            raise SystemExit(f"DiffSinger acoustic inference did not produce expected wav: {produced}")
        if produced != args.out:
            produced.replace(args.out)

        log = {
            "backend": "openvpi_diffsinger",
            "output": str(args.out),
            "sample_rate": sr,
            "duration_seconds": float(total_dur),
            "warnings": ["Used placeholder phoneme sequence ('a' per note); add real G2P/phonemization next."],
        }
        if args.log is not None:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            args.log.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return

    # Placeholder backend to keep the pipeline runnable without checkpoints.
    # It produces a vowel-like harmonic tone that follows the melody, not true lyric-conditioned singing.
    total_dur = 0.0
    if starts_sec:
        total_dur = max(s + d for s, d in zip(starts_sec, durs_sec))
    total_samples = int(math.ceil(total_dur * sr)) + 1
    audio = np.zeros(total_samples, dtype=np.float32)

    for s, d, f, slur in zip(starts_sec, durs_sec, freqs, is_slur):
        if f <= 0.0 or d <= 0.0:
            continue
        i0 = max(0, int(round(s * sr)))
        i1 = min(total_samples, int(round((s + d) * sr)))
        n = max(0, i1 - i0)
        if n <= 1:
            continue
        t = np.arange(n, dtype=np.float32) / sr

        # Harmonic stack (very rough voice-like tone).
        sig = np.zeros(n, dtype=np.float32)
        for h in range(1, 8):
            sig += (1.0 / h) * np.sin(2 * math.pi * (h * f) * t)

        # Envelope.
        attack = int(0.01 * sr)
        release = int(0.02 * sr)
        env = np.ones(n, dtype=np.float32)
        if attack > 0:
            env[: min(attack, n)] = np.linspace(0.0, 1.0, min(attack, n), dtype=np.float32)
        if release > 0:
            r = min(release, n)
            env[n - r :] *= np.linspace(1.0, 0.0, r, dtype=np.float32)

        # Slurred notes slightly softer to de-emphasize repeated syllables.
        amp = 0.22 if slur else 0.28
        audio[i0:i1] += amp * sig * env

    # Soft clip.
    audio = np.tanh(audio)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_wav(args.out, audio, sr)

    # "Debug out" shaped like diffsinger_input.json, but with placeholder phonemes.
    dbg = {
        "text": " ".join([w for w in lyrics if w]),
        "ph_seq": " ".join(["a"] * len(events)),
        "note_seq": " ".join([ev["pitch"] for ev in events]),
        "note_dur_seq": " ".join([f"{float(ev['duration_beats']) * 60.0 / tempo_bpm:.3f}" for ev in events]),
        "is_slur_seq": " ".join(["1" if ev["is_slur"] else "0" for ev in events]),
        "input_type": "phoneme",
        "metadata": {"backend": "simple_synth", "note": "placeholder; not DiffSinger inference"},
    }
    peak = int(np.max(np.abs(audio)) * 32767.0) if audio.size else 0
    log = {
        "backend": "simple_synth",
        "output": str(args.out),
        "sample_rate": sr,
        "duration_seconds": float(total_dur),
        "peak_dbfs": _dbfs_from_int16_peak(peak),
        "warnings": [
            "No usable DiffSinger checkpoints found; generated placeholder vocal tone (not lyric-conditioned singing).",
            f"To enable DiffSinger inference, place checkpoints under `{diffsinger_root}/checkpoints/` and pass `--variance-exp` + `--acoustic-exp`.",
        ],
    }
    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
