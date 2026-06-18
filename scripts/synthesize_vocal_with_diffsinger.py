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
import yaml


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


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_nishiren_phoneme_map(nishiren_root: Path) -> dict[str, int]:
    # The voicebank's authoritative phoneme-id mapping is the json file referenced
    # by dsconfig.yaml (not the training-time dsdict.yaml ordering).
    obj = _load_json(nishiren_root / "dsmain" / "phonemes.json")
    if not isinstance(obj, dict):
        raise ValueError(f"Unexpected dsmain/phonemes.json shape: {type(obj)}")
    return {str(k): int(v) for k, v in obj.items()}


def _load_nishiren_language_map(nishiren_root: Path) -> dict[str, int]:
    obj = _load_json(nishiren_root / "dsmain" / "languages.json")
    if isinstance(obj, dict) and all(isinstance(v, int) for v in obj.values()):
        return obj
    raise ValueError(f"Could not understand Nishiren languages.json: {obj}")


def _load_nishiren_embedding(path: Path, hidden: int) -> np.ndarray:
    try:
        arr = np.load(path, allow_pickle=False).astype(np.float32).reshape(-1)
        if arr.size == hidden:
            return arr
    except Exception:
        pass

    try:
        arr = np.loadtxt(path, dtype=np.float32).reshape(-1)
        if arr.size == hidden:
            return arr
    except Exception:
        pass

    arr = np.fromfile(path, dtype=np.float32).reshape(-1)
    if arr.size == hidden:
        return arr
    raise ValueError(f"Could not load speaker embedding from {path}; expected {hidden} floats, got {arr.size}.")


def _arpabet_to_nishiren(phones: list[str]) -> list[str]:
    out = []
    for p in phones:
        p = p.strip()
        if not p:
            continue
        while p and p[-1].isdigit():
            p = p[:-1]
        out.append(f"en/{p.lower()}")
    return out


def _normalize_nishiren_phonemes(phonemes: list[str], language_prefix: str) -> list[str]:
    out: list[str] = []
    for ph in phonemes:
        ph = str(ph).strip()
        if not ph:
            continue
        # Accept already-prefixed Nishiren tokens like "en/aa".
        if "/" in ph:
            out.append(ph)
            continue
        # Accept ARPABET-like tokens like "HH" or "AH0".
        while ph and ph[-1].isdigit():
            ph = ph[:-1]
        out.append(f"{language_prefix}/{ph.lower()}")
    return out


def _old_macdonald_arpabet_lexicon() -> dict[str, list[str]]:
    return {
        "old": ["OW", "L", "D"],
        "macdonald": ["M", "AE", "K", "D", "AA", "N", "AH", "L", "D"],
        "mac": ["M", "AE", "K"],
        "don": ["D", "AA", "N"],
        "ald": ["AH", "L", "D"],
        "had": ["HH", "AE", "D"],
        "a": ["AH"],
        "farm": ["F", "AA", "R", "M"],
        "e": ["IY"],
        "i": ["AY"],
        "o": ["OW"],
        "and": ["AE", "N", "D"],
        "on": ["AA", "N"],
        "that": ["DH", "AE", "T"],
        "he": ["HH", "IY"],
        "cow": ["K", "AW"],
        "with": ["W", "IH", "TH"],
        "moo": ["M", "UW"],
        "here": ["HH", "IY", "R"],
        "there": ["DH", "EH", "R"],
        "everywhere": ["EH", "V", "R", "IY", "W", "EH", "R"],
        "ev": ["EH", "V"],
        "ry": ["R", "IY"],
        "where": ["W", "EH", "R"],
        "his": ["HH", "IH", "Z"],
    }


def _word_to_phones(word: str, lex: dict[str, list[str]]) -> list[str]:
    w = "".join([c.lower() for c in word if c.isalpha() or c in {"'", "-"}]).strip("-'")
    if not w:
        return []
    if w in lex:
        return lex[w]
    # Try g2p_en if available (preferred for prototyping English lyrics).
    try:
        # Keep g2p_en offline by default by pointing NLTK at a repo-local cache
        # (created once via nltk.download(...)).
        if "NLTK_DATA" not in os.environ:
            repo_root = Path(__file__).resolve().parents[1]
            os.environ["NLTK_DATA"] = str(repo_root / "_build" / "nltk_data")
        from g2p_en import G2p  # type: ignore[import-not-found]

        g2p = G2p()
        phones = [p for p in g2p(w) if p and p != " "]
        # Drop punctuation-like tokens, keep ARPABET phones.
        phones = [p for p in phones if any(ch.isalpha() for ch in p)]
        if phones:
            return phones
    except Exception:
        pass

    raise KeyError(f"No ARPABET phones for word {word!r} (normalized {w!r}).")


def _run_nishiren_onnx(
    *,
    nishiren_root: Path,
    language: str,
    style: str,
    events: list[dict],
    tempo_bpm: float,
    sr: int,
    out_wav: Path,
    log_path: Path | None,
    debug_out: Path | None,
    vel: float,
    gender: float,
    steps: int,
) -> dict:
    os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")
    import onnxruntime as ort  # type: ignore[import-not-found]
    import soundfile as sf  # type: ignore[import-not-found]

    HOP = 512
    HIDDEN = 384

    # Use duration model (dsdur) to get realistic phoneme timing.
    dsdur_root = nishiren_root / "dsdur"
    if not (dsdur_root / "linguistic.onnx").exists() or not (dsdur_root / "dur.onnx").exists():
        raise SystemExit(f"Missing Nishiren duration models under {dsdur_root}.")

    ph_id_map = _load_json(dsdur_root / "phonemes.json")
    lang_map = _load_json(dsdur_root / "languages.json")
    if language not in lang_map:
        raise SystemExit(f"Nishiren language {language!r} not found in {lang_map}.")

    ling = ort.InferenceSession(str(dsdur_root / "linguistic.onnx"), providers=["CPUExecutionProvider"])
    dur_sess = ort.InferenceSession(str(dsdur_root / "dur.onnx"), providers=["CPUExecutionProvider"])

    lex = _old_macdonald_arpabet_lexicon()
    seconds_per_beat = 60.0 / tempo_bpm

    word_div: list[int] = []
    word_dur: list[int] = []
    ph_seq: list[str] = []
    ph_ids: list[int] = []
    ph_lang_ids: list[int] = []
    ph_midi: list[int] = []
    ph_to_event: list[int] = []

    for ev_idx, ev in enumerate(events):
        lyric = str(ev.get("lyric", "")).strip()
        if lyric == "":
            continue
        explicit_ph = ev.get("phonemes", None)
        if isinstance(explicit_ph, list) and explicit_ph:
            phones = _normalize_nishiren_phonemes(explicit_ph, language)
        else:
            phones = _arpabet_to_nishiren(_word_to_phones(lyric, lex))
        if not phones:
            continue

        dur_sec = float(ev["duration_beats"]) * seconds_per_beat
        frames = max(1, int(round(dur_sec * sr / HOP)))
        word_div.append(len(phones))
        word_dur.append(frames)

        # Midi note id per phoneme.
        hz = _pitch_to_hz(str(ev["pitch"]))
        midi = int(round(69 + 12 * math.log2(hz / 440.0))) if hz > 0 else 0

        for ph in phones:
            if ph not in ph_id_map:
                raise KeyError(f"Missing Nishiren phoneme id for {ph}.")
            ph_seq.append(ph)
            ph_ids.append(int(ph_id_map[ph]))
            ph_lang_ids.append(int(lang_map[language]))
            ph_midi.append(int(midi))
            ph_to_event.append(ev_idx)

    if not ph_ids:
        raise SystemExit("No phonemes produced; check lyric/phonemes in vocal_events.json.")

    dur_tokens = np.array([ph_ids], dtype=np.int64)
    dur_languages = np.array([ph_lang_ids], dtype=np.int64)
    word_div_arr = np.array([word_div], dtype=np.int64)
    word_dur_arr = np.array([word_dur], dtype=np.int64)

    encoder_out, x_masks = ling.run(
        None, {"tokens": dur_tokens, "languages": dur_languages, "word_div": word_div_arr, "word_dur": word_dur_arr}
    )

    style_emb_path = dsdur_root / f"{style}.emb"
    if not style_emb_path.exists():
        style_emb_path = nishiren_root / "dsmain" / f"{style}.emb"
    spk_tok = _load_nishiren_embedding(style_emb_path, HIDDEN)
    spk_embed_tok = np.tile(spk_tok.reshape(1, 1, HIDDEN), (1, dur_tokens.shape[1], 1)).astype(np.float32)
    ph_midi_arr = np.array([ph_midi], dtype=np.int64)

    ph_dur_pred = dur_sess.run(
        None, {"encoder_out": encoder_out, "x_masks": x_masks, "ph_midi": ph_midi_arr, "spk_embed": spk_embed_tok}
    )[0].reshape(-1).astype(np.float32)

    # Rescale predicted phoneme durations so per-word sums match the note durations.
    ph_frames: list[int] = []
    cur = 0
    for w_len, w_frames in zip(word_div, word_dur):
        seg = np.maximum(ph_dur_pred[cur : cur + w_len], 1.0)
        cur += w_len
        scale = float(w_frames) / float(seg.sum()) if float(seg.sum()) > 0 else 1.0
        seg_scaled = np.maximum(np.round(seg * scale), 1.0).astype(int)
        drift = int(w_frames) - int(seg_scaled.sum())
        if drift != 0:
            seg_scaled[-1] = max(1, int(seg_scaled[-1]) + drift)
        ph_frames.extend([int(x) for x in seg_scaled.tolist()])

    durations = np.array([ph_frames], dtype=np.int64)
    n_frames = int(durations.sum())

    # Piecewise-constant f0 per phoneme (per event pitch).
    f0 = np.zeros((1, n_frames), dtype=np.float32)
    t = 0
    for ph_f, ev_idx in zip(ph_frames, ph_to_event):
        hz = _pitch_to_hz(str(events[ev_idx]["pitch"]))
        f0[0, t : t + ph_f] = float(hz) if hz > 0 else 0.0
        t += int(ph_f)

    base_pitch = f0.copy()

    # Pitch model (dspitch): predicts a more realistic pitch curve from notes + phonemes.
    dspitch_root = nishiren_root / "dspitch"
    pitch_curve = f0.copy()
    if (dspitch_root / "linguistic.onnx").exists() and (dspitch_root / "pitch.onnx").exists():
        pitch_ph_map = _load_json(dspitch_root / "phonemes.json")
        pitch_lang_map = _load_json(dspitch_root / "languages.json")
        pitch_tokens = np.array([[int(pitch_ph_map[p]) for p in ph_seq]], dtype=np.int64)
        pitch_languages = np.array([[int(pitch_lang_map[language]) for _ in ph_seq]], dtype=np.int64)
        pitch_ling = ort.InferenceSession(str(dspitch_root / "linguistic.onnx"), providers=["CPUExecutionProvider"])
        pitch_onx = ort.InferenceSession(str(dspitch_root / "pitch.onnx"), providers=["CPUExecutionProvider"])
        pitch_encoder_out, _ = pitch_ling.run(None, {"tokens": pitch_tokens, "languages": pitch_languages, "ph_dur": durations})

        note_midi: list[float] = []
        note_rest: list[bool] = []
        note_dur: list[int] = []
        for ev in events:
            dur_sec = float(ev["duration_beats"]) * seconds_per_beat
            frames = max(1, int(round(dur_sec * sr / HOP)))
            hz = _pitch_to_hz(str(ev["pitch"]))
            midi = float(69 + 12 * math.log2(hz / 440.0)) if hz > 0 else 0.0
            note_midi.append(midi)
            note_rest.append(hz <= 0)
            note_dur.append(frames)

        pitch_spk_path = dspitch_root / f"{style}.emb"
        if not pitch_spk_path.exists():
            pitch_spk_path = nishiren_root / "dsmain" / f"{style}.emb"
        pitch_spk = _load_nishiren_embedding(pitch_spk_path, HIDDEN)
        pitch_spk_embed = np.tile(pitch_spk.reshape(1, 1, HIDDEN), (1, n_frames, 1)).astype(np.float32)

        expr = np.zeros((1, n_frames), dtype=np.float32)
        retake = np.zeros((1, n_frames), dtype=bool)
        steps_arr = np.array(int(steps), dtype=np.int64)
        pitch_curve_pred = pitch_onx.run(
            None,
            {
                "encoder_out": pitch_encoder_out,
                "ph_dur": durations,
                "note_midi": np.array([note_midi], dtype=np.float32),
                "note_rest": np.array([note_rest], dtype=bool),
                "note_dur": np.array([note_dur], dtype=np.int64),
                "pitch": pitch_curve.astype(np.float32),
                "expr": expr,
                "retake": retake,
                "spk_embed": pitch_spk_embed,
                "steps": steps_arr,
            },
        )[0].astype(np.float32)

        # Fallback: if the pitch model collapses to near-monotone, keep the note-derived pitch.
        voiced = pitch_curve_pred[pitch_curve_pred > 1.0]
        voiced_std = float(np.std(voiced)) if voiced.size else 0.0
        if voiced_std < 8.0:
            pitch_curve = base_pitch
        else:
            pitch_curve = pitch_curve_pred

    # Variance model (dsvariance): predicts breathiness/voicing/tension curves given pitch + phonemes.
    dsvar_root = nishiren_root / "dsvariance"
    breathiness = np.zeros((1, n_frames), dtype=np.float32)
    voicing = np.zeros((1, n_frames), dtype=np.float32)
    tension = np.zeros((1, n_frames), dtype=np.float32)
    if (dsvar_root / "linguistic.onnx").exists() and (dsvar_root / "variance.onnx").exists():
        var_ph_map = _load_json(dsvar_root / "phonemes.json")
        var_lang_map = _load_json(dsvar_root / "languages.json")
        var_tokens = np.array([[int(var_ph_map[p]) for p in ph_seq]], dtype=np.int64)
        var_languages = np.array([[int(var_lang_map[language]) for _ in ph_seq]], dtype=np.int64)
        var_ling = ort.InferenceSession(str(dsvar_root / "linguistic.onnx"), providers=["CPUExecutionProvider"])
        var_onx = ort.InferenceSession(str(dsvar_root / "variance.onnx"), providers=["CPUExecutionProvider"])
        var_encoder_out, _ = var_ling.run(None, {"tokens": var_tokens, "languages": var_languages, "ph_dur": durations})

        var_spk_path = dsvar_root / f"{style}.emb"
        if not var_spk_path.exists():
            var_spk_path = nishiren_root / "dsmain" / f"{style}.emb"
        var_spk = _load_nishiren_embedding(var_spk_path, HIDDEN)
        var_spk_embed = np.tile(var_spk.reshape(1, 1, HIDDEN), (1, n_frames, 1)).astype(np.float32)

        retake3 = np.zeros((1, n_frames, 3), dtype=bool)
        steps_arr = np.array(int(steps), dtype=np.int64)
        breathiness, voicing, tension = var_onx.run(
            None,
            {
                "encoder_out": var_encoder_out,
                "ph_dur": durations,
                "pitch": pitch_curve.astype(np.float32),
                "breathiness": breathiness,
                "voicing": voicing,
                "tension": tension,
                "retake": retake3,
                "spk_embed": var_spk_embed,
                "steps": steps_arr,
            },
        )
        breathiness = breathiness.astype(np.float32)
        voicing = voicing.astype(np.float32)
        tension = tension.astype(np.float32)

    gender = np.full((1, n_frames), float(gender), dtype=np.float32)
    velocity = np.full((1, n_frames), float(vel), dtype=np.float32)

    # Add a tiny vibrato to reduce “robotic” output, but keep it subtle.
    # Only apply where pitch is voiced.
    vib_rate_hz = 5.5
    vib_depth = 0.015
    tt = (np.arange(n_frames, dtype=np.float32) * (HOP / float(sr))).reshape(1, -1)
    vib = (1.0 + vib_depth * np.sin(2.0 * math.pi * vib_rate_hz * tt)).astype(np.float32)
    pitch_curve = np.where(pitch_curve > 1.0, pitch_curve * vib, pitch_curve).astype(np.float32)

    # Acoustic model uses dsmain phoneme ids per dsconfig.yaml.
    acoustic_ph_map = _load_nishiren_phoneme_map(nishiren_root)
    acoustic_lang_map = _load_nishiren_language_map(nishiren_root)
    acoustic_tokens = np.array([[int(acoustic_ph_map[p]) for p in ph_seq]], dtype=np.int64)
    acoustic_languages = np.array([[int(acoustic_lang_map[language]) for _ in ph_seq]], dtype=np.int64)

    emb_path = nishiren_root / "dsmain" / f"{style}.emb"
    if not emb_path.exists():
        raise SystemExit(f"Nishiren style embedding not found: {emb_path}")
    spk = _load_nishiren_embedding(emb_path, HIDDEN)
    spk_embed = np.tile(spk.reshape(1, 1, HIDDEN), (1, n_frames, 1)).astype(np.float32)

    acoustic = ort.InferenceSession(str(nishiren_root / "dsmain" / "acoustic.onnx"), providers=["CPUExecutionProvider"])
    vocoder_candidates = sorted((nishiren_root / "dsvocoder").glob("*.onnx"))
    if not vocoder_candidates:
        raise SystemExit(f"No vocoder ONNX found under {nishiren_root / 'dsvocoder'}")
    vocoder = ort.InferenceSession(str(vocoder_candidates[0]), providers=["CPUExecutionProvider"])

    steps_arr = np.array(int(steps), dtype=np.int64)
    mel = acoustic.run(
        None,
        {
            "tokens": acoustic_tokens,
            "languages": acoustic_languages,
            "durations": durations,
            "f0": pitch_curve.astype(np.float32),
            "breathiness": breathiness,
            "voicing": voicing,
            "tension": tension,
            "gender": gender,
            "velocity": velocity,
            "spk_embed": spk_embed,
            "steps": steps_arr,
        },
    )[0].astype(np.float32)

    waveform = vocoder.run(None, {"mel": mel, "f0": pitch_curve.astype(np.float32)})[0].reshape(-1).astype(np.float32)

    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    if peak > 1.0:
        waveform = waveform / peak * 0.95

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, waveform, sr)

    log = {
        "backend": "nishiren_onnx",
        "nishiren_root": str(nishiren_root),
        "language": language,
        "style": style,
        "vocoder": str(vocoder_candidates[0]),
        "output": str(out_wav),
        "sample_rate": sr,
        "phoneme_count": int(len(ph_seq)),
        "duration_seconds": float(waveform.size) / float(sr) if sr else None,
        "peak": peak,
        "warnings": [
            "Uses a minimal hand-built ARPABET lexicon for Old MacDonald; extend lexicon or add real G2P for general lyrics."
        ],
    }
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if debug_out is not None:
        debug_out.parent.mkdir(parents=True, exist_ok=True)
        debug_out.write_text(
            json.dumps(
                {
                    "text": " ".join([str(ev.get("lyric", "")).strip() for ev in events if str(ev.get("lyric", "")).strip()]),
                    "ph_seq": " ".join(ph_seq),
                    "note_seq": " ".join(["x"] * len(ph_seq)),
                    "note_dur_seq": " ".join([str(int(x)) for x in ph_frames]),
                    "is_slur_seq": " ".join(["0"] * len(ph_seq)),
                    "input_type": "phoneme",
                    "metadata": {
                        "backend": "nishiren_onnx",
                        "duration_unit": "frames",
                        "hop": HOP,
                        "sr": sr,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return log


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("vocal_events_json", type=Path)
    ap.add_argument("--model", type=str, default=None)
    ap.add_argument("--language", default="English")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--debug-out", type=Path, required=True)
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--backend", choices=["auto", "simple_synth", "openvpi_diffsinger", "nishiren_onnx"], default="auto")
    ap.add_argument("--diffsinger-root", type=Path, default=Path("third_party/DiffSinger"))
    ap.add_argument("--nishiren-root", type=Path, default=Path("third_party/Nishiren Diffsinger v2.0"))
    ap.add_argument("--nishiren-lang", type=str, default="en")
    ap.add_argument("--nishiren-style", type=str, default="Standard")
    ap.add_argument("--nishiren-vel", type=float, default=1.25)
    ap.add_argument("--nishiren-gender", type=float, default=0.0)
    ap.add_argument("--nishiren-steps", type=int, default=30)
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

    have_nishiren = (args.nishiren_root / "dsmain" / "acoustic.onnx").exists()
    requested_nishiren = args.backend in {"auto", "nishiren_onnx"}
    if requested_nishiren and have_nishiren:
        _run_nishiren_onnx(
            nishiren_root=args.nishiren_root,
            language=args.nishiren_lang,
            style=args.nishiren_style,
            events=events,
            tempo_bpm=tempo_bpm,
            sr=sr,
            out_wav=args.out,
            log_path=args.log,
            debug_out=args.debug_out,
            vel=float(args.nishiren_vel),
            gender=float(args.nishiren_gender),
            steps=int(args.nishiren_steps),
        )
        return

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
