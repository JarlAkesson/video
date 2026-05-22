#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import wave
from pathlib import Path


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        sr = wf.getframerate()
    if sr <= 0:
        return 0.0
    return frames / sr


def _wav_peak_dbfs(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        sampwidth = wf.getsampwidth()
        if sampwidth != 2:
            return float("nan")
        frames = wf.readframes(wf.getnframes())
    import numpy as np

    data = np.frombuffer(frames, dtype=np.int16)
    peak = int(np.max(np.abs(data))) if data.size else 0
    if peak <= 0:
        return float("-inf")
    return 20.0 * math.log10(peak / 32767.0)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arranged_musicxml", type=Path)
    ap.add_argument("vocal_wav", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--instrumental-out", type=Path, default=None)
    ap.add_argument("--vocal-gain", type=float, default=1.0)
    ap.add_argument("--inst-gain", type=float, default=1.0)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    instrumental_out = args.instrumental_out
    if instrumental_out is None:
        instrumental_out = Path("assets/_build/audio") / (args.arranged_musicxml.stem + ".instrumental.wav")
    instrumental_out.parent.mkdir(parents=True, exist_ok=True)

    # Render instrumental with MuseScore (most reliable in this environment).
    _run(
        [
            "env",
            "HOME=/tmp/musescore-home",
            "XDG_CONFIG_HOME=/tmp/musescore-home",
            "QT_QPA_PLATFORM=offscreen",
            "musescore3",
            "--no-webview",
            "-o",
            str(instrumental_out),
            str(args.arranged_musicxml),
        ]
    )

    # Mix using ffmpeg.
    # Apply gains first, then amix.
    mix_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(instrumental_out),
        "-i",
        str(args.vocal_wav),
        "-filter_complex",
        f"[0:a]volume={args.inst_gain}[a0];[1:a]volume={args.vocal_gain}[a1];[a0][a1]amix=inputs=2:duration=longest:dropout_transition=2[aout]",
        "-map",
        "[aout]",
        str(args.out),
        "-loglevel",
        "error",
    ]
    _run(mix_cmd)

    inst_dur = _wav_duration_seconds(instrumental_out)
    voc_dur = _wav_duration_seconds(args.vocal_wav)
    final_dur = _wav_duration_seconds(args.out)

    report = {
        "files": {"instrumental": str(instrumental_out), "vocal": str(args.vocal_wav), "final": str(args.out)},
        "timing": {
            "vocal_start_seconds": 0.0,
            "detected_offset_warning": False,
            "instrumental_duration_seconds": inst_dur,
            "vocal_duration_seconds": voc_dur,
        },
        "levels": {
            "vocal_peak_dbfs": _wav_peak_dbfs(args.vocal_wav),
            "instrumental_peak_dbfs": _wav_peak_dbfs(instrumental_out),
            "final_peak_dbfs": _wav_peak_dbfs(args.out),
        },
        "musical_warnings": [],
        "suggested_next_actions": [],
    }

    if abs(inst_dur - final_dur) > 0.25:
        report["suggested_next_actions"].append("Inspect mix duration mismatch; check for trailing silence or render settings.")
    if report["levels"]["final_peak_dbfs"] > -0.5:
        report["suggested_next_actions"].append("Reduce overall mix gain to avoid clipping.")

    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
