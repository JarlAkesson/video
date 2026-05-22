#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


STEP_TO_PC = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}

PC_TO_STEP_ALTER_FLAT = {
    0: ("C", None),
    1: ("D", -1),
    2: ("D", None),
    3: ("E", -1),
    4: ("E", None),
    5: ("F", None),
    6: ("G", -1),
    7: ("G", None),
    8: ("A", -1),
    9: ("A", None),
    10: ("B", -1),
    11: ("B", None),
}

SUPPORTED_INSTRUMENTS = {"violin", "cello", "strings_pad", "bass", "drumset"}
RANGE_BANDS = {
    "violin": (62, 88),
    "cello": (43, 69),
    "strings_pad": (55, 79),
    "bass": (34, 52),
}

DRUM_DISPLAY = {
    "subkick": ("F", 3),
    "kick": ("F", 3),
    "snare": ("C", 4),
    "clap": ("C", 5),
    "hat": ("G", 5),
    "tom": ("D", 4),
}

DRUM_MIDI = {
    "subkick": 35,
    "kick": 36,
    "snare": 38,
    "clap": 39,
    "hat": 42,
    "tom": 45,
}

KEY_NAME_TO_INFO = {
    "c major": (0, 0, "major"),
    "g major": (7, 1, "major"),
    "d major": (2, 2, "major"),
    "a major": (9, 3, "major"),
    "e major": (4, 4, "major"),
    "b major": (11, 5, "major"),
    "f# major": (6, 6, "major"),
    "gb major": (6, -6, "major"),
    "db major": (1, -5, "major"),
    "ab major": (8, -4, "major"),
    "eb major": (3, -3, "major"),
    "bb major": (10, -2, "major"),
    "f major": (5, -1, "major"),
    "a minor": (9, 0, "minor"),
    "e minor": (4, 1, "minor"),
    "b minor": (11, 2, "minor"),
    "f# minor": (6, 3, "minor"),
    "gb minor": (6, -3, "minor"),
    "c# minor": (1, 4, "minor"),
    "db minor": (1, -8, "minor"),
    "g# minor": (8, 5, "minor"),
    "ab minor": (8, -7, "minor"),
    "d# minor": (3, 6, "minor"),
    "eb minor": (3, -6, "minor"),
    "bb minor": (10, -5, "minor"),
    "f minor": (5, -4, "minor"),
    "c minor": (0, -3, "minor"),
    "g minor": (7, -2, "minor"),
    "d minor": (2, -1, "minor"),
}

PRESET_DEFAULTS = {
    "none": {},
    "hiphop_dark": {
        "target_key": "transpose:-2",
        "tempo": "slower:15",
        "add_instruments": ["bass", "drumset"],
        "vibe": ["dark", "swagger"],
        "energy": "medium",
        "density": "sparse",
        "groove": "halftime",
        "bass": "strong",
        "drums": "strong",
        "entry_after_bars": 8,
        "harmony_treatment": "darker",
        "register_shift": "lower",
        "expression": "assertive",
    },
    "cinematic_strings": {
        "add_instruments": ["violin", "cello", "strings_pad"],
        "tempo": "slower:8",
        "density": "medium",
        "groove": "straight",
        "bass": "none",
        "drums": "none",
        "entry_after_bars": "auto",
        "melody_treatment": "decorate",
        "expression": "shaped",
    },
    "chamber_additive": {
        "add_instruments": ["violin", "cello"],
        "density": "sparse",
        "groove": "straight",
        "bass": "none",
        "drums": "none",
        "entry_after_bars": "auto",
        "melody_treatment": "shadow",
        "expression": "shaped",
    },
    "lofi_sparse": {
        "tempo": "slower:10",
        "add_instruments": ["bass", "drumset"],
        "density": "sparse",
        "groove": "halftime",
        "bass": "light",
        "drums": "restrained",
        "entry_after_bars": 8,
        "expression": "plain",
    },
}


@dataclass
class PreferenceSpec:
    source_score: str
    goal: str
    preset: str = "none"
    target_key: str = "keep"
    tempo: str = "keep"
    add_instruments: list[str] = field(default_factory=list)
    remove_instruments: list[str] = field(default_factory=list)
    vibe: list[str] = field(default_factory=list)
    energy: str = "medium"
    density: str = "medium"
    groove: str = "straight"
    bass: str = "none"
    drums: str = "none"
    entry_after_bars: str = "auto"
    melody_treatment: str = "preserve"
    harmony_treatment: str = "preserve"
    register_shift: str = "none"
    expression: str = "plain"


@dataclass
class SourceInfo:
    first_tonic_pc: int
    first_fifths: int
    first_mode: str
    first_tempo: float | None
    measure_count: int
    part_names: list[str]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "arranged"


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_xml_root(path: Path) -> ET.Element:
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as zf:
            xml_name = next(
                name for name in zf.namelist() if name.endswith(".xml") and not name.startswith("META-INF/")
            )
            return ET.fromstring(zf.read(xml_name))
    return ET.parse(path).getroot()


def pitch_to_midi(pitch: ET.Element) -> int:
    step = pitch.findtext("step")
    alter = int(pitch.findtext("alter", "0"))
    octave = int(pitch.findtext("octave"))
    return 12 * (octave + 1) + STEP_TO_PC[step] + alter


def midi_to_pitch(midi: int) -> tuple[str, int | None, int]:
    pc = midi % 12
    octave = midi // 12 - 1
    step, alter = PC_TO_STEP_ALTER_FLAT[pc]
    return step, alter, octave


def set_pitch_from_midi(pitch: ET.Element, midi: int) -> None:
    step, alter, octave = midi_to_pitch(midi)
    for child in list(pitch):
        pitch.remove(child)
    ET.SubElement(pitch, "step").text = step
    if alter is not None:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(octave)


def duration_type(duration: int, divisions: int) -> str:
    if duration == 4 * divisions:
        return "whole"
    if duration == 2 * divisions:
        return "half"
    if duration == divisions:
        return "quarter"
    if duration * 2 == divisions:
        return "eighth"
    if duration * 4 == divisions:
        return "16th"
    raise ValueError(f"Unsupported duration/type combination duration={duration} divisions={divisions}")


def duration_chunks(duration: int, divisions: int) -> list[int]:
    chunks: list[int] = []
    base_units = [4 * divisions, 2 * divisions, divisions]
    if divisions % 2 == 0:
        base_units.append(divisions // 2)
    if divisions % 4 == 0:
        base_units.append(divisions // 4)
    for unit in base_units:
        while duration >= unit:
            chunks.append(unit)
            duration -= unit
    if duration != 0:
        raise ValueError(f"Unsupported residual duration {duration}")
    return chunks


def make_rest(duration: int, divisions: int) -> ET.Element:
    note = ET.Element("note")
    ET.SubElement(note, "rest")
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = duration_type(duration, divisions)
    return note


def make_pitch_note(midi: int, duration: int, divisions: int, stem: str = "up") -> ET.Element:
    note = ET.Element("note")
    pitch = ET.SubElement(note, "pitch")
    step, alter, octave = midi_to_pitch(midi)
    ET.SubElement(pitch, "step").text = step
    if alter is not None:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(octave)
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = duration_type(duration, divisions)
    ET.SubElement(note, "stem").text = stem
    return note


def make_percussion_note(kind: str, duration: int, divisions: int) -> ET.Element:
    note = ET.Element("note")
    unpitched = ET.SubElement(note, "unpitched")
    step, octave = DRUM_DISPLAY[kind]
    ET.SubElement(unpitched, "display-step").text = step
    ET.SubElement(unpitched, "display-octave").text = str(octave)
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = duration_type(duration, divisions)
    ET.SubElement(note, "instrument", {"id": f"P4-{kind}"})
    ET.SubElement(note, "stem").text = "up"
    if kind == "hat":
        ET.SubElement(note, "notehead").text = "x"
    elif kind == "clap":
        ET.SubElement(note, "notehead").text = "diamond"
    return note


def make_attributes(divisions: int, fifths: int, mode: str, beats: int, beat_type: int, clef_sign: str, clef_line: int) -> ET.Element:
    attrs = ET.Element("attributes")
    ET.SubElement(attrs, "divisions").text = str(divisions)
    key = ET.SubElement(attrs, "key")
    ET.SubElement(key, "fifths").text = str(fifths)
    ET.SubElement(key, "mode").text = mode
    time = ET.SubElement(attrs, "time")
    ET.SubElement(time, "beats").text = str(beats)
    ET.SubElement(time, "beat-type").text = str(beat_type)
    clef = ET.SubElement(attrs, "clef")
    ET.SubElement(clef, "sign").text = clef_sign
    ET.SubElement(clef, "line").text = str(clef_line)
    return attrs


def first_part(root: ET.Element) -> ET.Element:
    return root.findall("part")[0]


def normalize_key_name(text: str) -> str:
    text = text.strip().lower().replace(" minor", " minor").replace(" major", " major")
    text = text.replace("min", "minor").replace("maj", "major")
    text = re.sub(r"\s+", " ", text)
    if text.endswith("m") and "minor" not in text and "major" not in text:
        text = text[:-1] + " minor"
    elif "major" not in text and "minor" not in text:
        text = text + " minor"
    return text


def tonic_pc_from_fifths_mode(fifths: int, mode: str) -> int:
    if mode == "major":
        return (7 * fifths) % 12
    return (9 + 7 * fifths) % 12


def detect_source_info(root: ET.Element) -> SourceInfo:
    part = first_part(root)
    fifths = 0
    mode = "minor"
    tempo = None
    measure_count = len(part.findall("measure"))
    for measure in part.findall("measure"):
        attrs = measure.find("attributes")
        if attrs is not None:
            key = attrs.find("key")
            if key is not None and key.find("fifths") is not None:
                fifths = int(key.findtext("fifths"))
                mode = key.findtext("mode", mode)
                break
    for pm in root.findall(".//per-minute"):
        try:
            tempo = float(pm.text)
            break
        except (TypeError, ValueError):
            continue
    if tempo is None:
        for sound in root.findall(".//sound[@tempo]"):
            try:
                tempo = float(sound.attrib["tempo"])
                break
            except (TypeError, ValueError):
                continue
    part_names = [score_part.findtext("part-name", "") for score_part in root.find("part-list").findall("score-part")]
    return SourceInfo(
        first_tonic_pc=tonic_pc_from_fifths_mode(fifths, mode),
        first_fifths=fifths,
        first_mode=mode,
        first_tempo=tempo,
        measure_count=measure_count,
        part_names=part_names,
    )


def infer_from_goal(goal: str) -> dict[str, object]:
    goal_l = goal.lower()
    inferred: dict[str, object] = {}
    vibe: list[str] = []
    if any(word in goal_l for word in ["hiphop", "hip-hop", "trap", "boom bap", "boombap"]):
        inferred["preset"] = "hiphop_dark" if "dark" in goal_l or "swagger" in goal_l else "lofi_sparse"
        inferred["groove"] = "halftime"
        inferred["bass"] = "strong"
        inferred["drums"] = "strong"
    if "cinematic" in goal_l or "string" in goal_l:
        inferred.setdefault("preset", "cinematic_strings")
    if "chamber" in goal_l:
        inferred.setdefault("preset", "chamber_additive")
    if "lofi" in goal_l or "lo-fi" in goal_l:
        inferred.setdefault("preset", "lofi_sparse")
    if "dark" in goal_l:
        vibe.append("dark")
        inferred.setdefault("harmony_treatment", "darker")
        inferred.setdefault("register_shift", "lower")
    if "swagger" in goal_l:
        vibe.append("swagger")
    if "joy" in goal_l or "joyful" in goal_l or "happy" in goal_l:
        vibe.append("joyful")
    if "tense" in goal_l:
        vibe.append("tense")
    if "sparse" in goal_l:
        inferred["density"] = "sparse"
    elif "dense" in goal_l or "big" in goal_l:
        inferred["density"] = "dense"
    if "slow" in goal_l or "slower" in goal_l:
        inferred.setdefault("tempo", "slower:10")
    if "faster" in goal_l or "quick" in goal_l:
        inferred.setdefault("tempo", "faster:10")
    if "violin" in goal_l:
        inferred.setdefault("add_instruments", []).append("violin")
    if "cello" in goal_l:
        inferred.setdefault("add_instruments", []).append("cello")
    if "pad" in goal_l or "strings pad" in goal_l:
        inferred.setdefault("add_instruments", []).append("strings_pad")
    if "bass" in goal_l:
        inferred.setdefault("add_instruments", []).append("bass")
    if "drum" in goal_l or "beat" in goal_l:
        inferred.setdefault("add_instruments", []).append("drumset")
    if vibe:
        inferred["vibe"] = vibe
    return inferred


def merge_preferences(args: argparse.Namespace, source_info: SourceInfo) -> PreferenceSpec:
    if not args.goal.strip():
        raise ValueError("goal must be non-empty")

    explicit = {
        "preset": args.preset,
        "target_key": args.target_key,
        "tempo": args.tempo,
        "add_instruments": split_csv(args.add_instruments),
        "remove_instruments": split_csv(args.remove_instruments),
        "vibe": split_csv(args.vibe),
        "energy": args.energy,
        "density": args.density,
        "groove": args.groove,
        "bass": args.bass,
        "drums": args.drums,
        "entry_after_bars": args.entry_after_bars,
        "melody_treatment": args.melody_treatment,
        "harmony_treatment": args.harmony_treatment,
        "register_shift": args.register_shift,
        "expression": args.expression,
    }
    inferred = infer_from_goal(args.goal)
    preset_name = explicit["preset"] if explicit["preset"] != "auto" else inferred.get("preset", "none")
    preset = PRESET_DEFAULTS.get(preset_name, {})

    def choose(field: str, default: object) -> object:
        explicit_value = explicit[field]
        if field in {"add_instruments", "remove_instruments", "vibe"}:
            if explicit_value:
                return explicit_value
            inferred_value = inferred.get(field)
            if inferred_value:
                return inferred_value
            preset_value = preset.get(field)
            if preset_value:
                return preset_value
            return default
        if explicit_value not in {None, "auto"}:
            return explicit_value
        if field in inferred:
            return inferred[field]
        if field in preset:
            return preset[field]
        return default

    spec = PreferenceSpec(
        source_score=str(Path(args.source_score).resolve()),
        goal=args.goal.strip(),
        preset=preset_name,
        target_key=str(choose("target_key", "keep")),
        tempo=str(choose("tempo", "keep")),
        add_instruments=list(dict.fromkeys(choose("add_instruments", []))),
        remove_instruments=list(dict.fromkeys(choose("remove_instruments", []))),
        vibe=list(dict.fromkeys(choose("vibe", []))),
        energy=str(choose("energy", "medium")),
        density=str(choose("density", "medium")),
        groove=str(choose("groove", "straight")),
        bass=str(choose("bass", "none")),
        drums=str(choose("drums", "none")),
        entry_after_bars=str(choose("entry_after_bars", "auto")),
        melody_treatment=str(choose("melody_treatment", "preserve")),
        harmony_treatment=str(choose("harmony_treatment", "preserve")),
        register_shift=str(choose("register_shift", "none")),
        expression=str(choose("expression", "plain")),
    )

    unsupported = [name for name in spec.add_instruments if name not in SUPPORTED_INSTRUMENTS]
    if unsupported:
        raise ValueError(f"Unsupported requested instruments: {', '.join(sorted(unsupported))}")

    if spec.bass != "none" and "bass" not in spec.add_instruments:
        spec.add_instruments.append("bass")
    if spec.drums != "none" and "drumset" not in spec.add_instruments:
        spec.add_instruments.append("drumset")
    if spec.preset == "hiphop_dark" and not spec.add_instruments:
        spec.add_instruments = ["bass", "drumset"]

    if spec.target_key == "keep" and spec.preset == "hiphop_dark":
        spec.target_key = "transpose:-2"
    if spec.tempo == "keep" and spec.preset == "hiphop_dark":
        spec.tempo = "slower:15"

    if spec.target_key.startswith("transpose:") and spec.target_key == "transpose:0":
        spec.target_key = "keep"
    if spec.groove == "halftime" and spec.drums == "none":
        spec.drums = "restrained"
        if "drumset" not in spec.add_instruments:
            spec.add_instruments.append("drumset")

    if spec.energy == "low" and spec.density == "dense":
        spec.density = "medium"

    if spec.entry_after_bars == "auto":
        spec.entry_after_bars = "8" if spec.drums != "none" or spec.bass != "none" else "0"

    if spec.target_key != "keep":
        parse_target_key(spec.target_key, source_info)

    return spec


def parse_target_key(target_key: str, source_info: SourceInfo) -> tuple[int, int, str]:
    if target_key == "keep":
        return 0, source_info.first_fifths, source_info.first_mode
    if target_key.startswith("transpose:"):
        semitones = int(target_key.split(":", 1)[1])
        tonic = (source_info.first_tonic_pc + semitones) % 12
        mode = source_info.first_mode
        candidates = [
            (name, info)
            for name, info in KEY_NAME_TO_INFO.items()
            if info[0] == tonic and info[2] == mode
        ]
        if not candidates:
            return semitones, source_info.first_fifths, mode
        candidates.sort(key=lambda item: abs(item[1][1]))
        return semitones, candidates[0][1][1], mode
    normalized = normalize_key_name(target_key)
    if normalized not in KEY_NAME_TO_INFO:
        raise ValueError(f"Unsupported target_key {target_key!r}")
    tonic, fifths, mode = KEY_NAME_TO_INFO[normalized]
    semitones = (tonic - source_info.first_tonic_pc) % 12
    if semitones > 6:
        semitones -= 12
    return semitones, fifths, mode


def tempo_factor(tempo_spec: str, source_info: SourceInfo) -> float:
    if tempo_spec == "keep":
        return 1.0
    if tempo_spec.startswith("slower:"):
        return 1.0 - int(tempo_spec.split(":", 1)[1]) / 100.0
    if tempo_spec.startswith("faster:"):
        return 1.0 + int(tempo_spec.split(":", 1)[1]) / 100.0
    if tempo_spec.startswith("bpm:"):
        if source_info.first_tempo is None:
            raise ValueError("Cannot use bpm:<number> when source tempo is unavailable")
        bpm = float(tempo_spec.split(":", 1)[1])
        return bpm / source_info.first_tempo
    raise ValueError(f"Unsupported tempo spec {tempo_spec!r}")


def scale_tempos(root: ET.Element, factor: float) -> None:
    if abs(factor - 1.0) < 1e-9:
        return
    for per_minute in root.findall(".//per-minute"):
        try:
            value = float(per_minute.text)
        except (TypeError, ValueError):
            continue
        per_minute.text = f"{value * factor:.3f}".rstrip("0").rstrip(".")
    for sound in root.findall(".//sound[@tempo]"):
        try:
            value = float(sound.attrib["tempo"])
        except (TypeError, ValueError):
            continue
        sound.set("tempo", f"{value * factor:.4f}".rstrip("0").rstrip("."))


def transpose_root(root: ET.Element, semitones: int, fifths: int, mode: str) -> None:
    if semitones == 0 and fifths == 0 and mode == "major":
        return
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            attrs = measure.find("attributes")
            if attrs is not None:
                key = attrs.find("key")
                if key is not None:
                    fifths_el = key.find("fifths")
                    if fifths_el is None:
                        fifths_el = ET.SubElement(key, "fifths")
                    fifths_el.text = str(fifths)
                    mode_el = key.find("mode")
                    if mode_el is None:
                        mode_el = ET.SubElement(key, "mode")
                    mode_el.text = mode
            for note in measure.findall("note"):
                pitch = note.find("pitch")
                if pitch is None:
                    continue
                set_pitch_from_midi(pitch, pitch_to_midi(pitch) + semitones)


def iter_measure_states(part: ET.Element) -> Iterable[dict[str, object]]:
    divisions = 12
    beats = 4
    beat_type = 4
    fifths = 0
    mode = "minor"
    for measure in part.findall("measure"):
        attrs = measure.find("attributes")
        if attrs is not None:
            if attrs.find("divisions") is not None:
                divisions = int(attrs.findtext("divisions"))
            time = attrs.find("time")
            if time is not None:
                beats = int(time.findtext("beats"))
                beat_type = int(time.findtext("beat-type"))
            key = attrs.find("key")
            if key is not None and key.find("fifths") is not None:
                fifths = int(key.findtext("fifths"))
                mode = key.findtext("mode", mode)
        yield {
            "measure": measure,
            "divisions": divisions,
            "beats": beats,
            "beat_type": beat_type,
            "measure_duration": divisions * beats * 4 // beat_type,
            "fifths": fifths,
            "mode": mode,
        }


def extract_note_events(measure: ET.Element, prefer_staff: str | None = None) -> list[dict[str, int]]:
    events = []
    time_pos = 0
    last_onset = 0
    for child in measure:
        if child.tag == "note":
            duration = int(child.findtext("duration", "0"))
            onset = last_onset if child.find("chord") is not None else time_pos
            if child.find("rest") is None and child.find("grace") is None:
                if prefer_staff is None or child.findtext("staff", "1") == prefer_staff:
                    pitch = child.find("pitch")
                    if pitch is not None:
                        events.append({"onset": onset, "duration": duration, "midi": pitch_to_midi(pitch)})
            if child.find("chord") is None:
                last_onset = onset
                time_pos += duration
        elif child.tag == "backup":
            time_pos -= int(child.findtext("duration", "0"))
        elif child.tag == "forward":
            time_pos += int(child.findtext("duration", "0"))
    return events


def bucket_pitch(events: list[dict[str, int]], start: int, end: int, mode: str) -> int | None:
    bucket = [event["midi"] for event in events if start <= event["onset"] < end]
    if not bucket:
        bucket = [event["midi"] for event in events if event["onset"] >= start]
    if not bucket:
        bucket = [event["midi"] for event in events if event["onset"] < start]
    if not bucket:
        return None
    selector = max if mode == "high" else min
    return selector(bucket)


def fit_register(midi: int | None, band: tuple[int, int], previous: int | None) -> int | None:
    if midi is None:
        return None
    low, high = band
    candidates = []
    for shift in range(-36, 37, 12):
        candidate = midi + shift
        if low <= candidate <= high:
            candidates.append(candidate)
    if not candidates:
        while midi < low:
            midi += 12
        while midi > high:
            midi -= 12
        return midi
    if previous is None:
        center = (low + high) // 2
        return min(candidates, key=lambda value: abs(value - center))
    return min(candidates, key=lambda value: abs(value - previous) + (6 if abs(value - previous) > 9 else 0))


def segment_name(index: int, measure_count: int) -> str:
    if measure_count < 16:
        if index <= 2:
            return "intro"
        if index <= measure_count - 2:
            return "body"
        return "finale"
    quart = max(4, measure_count // 4)
    if index <= quart // 2:
        return "intro"
    if index <= quart * 2:
        return "shadow"
    if index <= quart * 3:
        return "drive"
    return "finale"


def should_play(index: int, entry_after_bars: int) -> bool:
    return index > entry_after_bars


def dynamic_word(expression: str, energy: str) -> str:
    if expression == "assertive" or energy == "high":
        return "f"
    if expression == "shaped":
        return "mf"
    return "mp"


def make_dynamic_directions(word: str, label: str | None = None) -> list[ET.Element]:
    directions: list[ET.Element] = []
    if label:
        direction = ET.Element("direction", {"placement": "above"})
        direction_type = ET.SubElement(direction, "direction-type")
        ET.SubElement(direction_type, "words").text = label
        directions.append(direction)
    dyn = ET.Element("direction", {"placement": "below"})
    dyn_type = ET.SubElement(dyn, "direction-type")
    dynamics = ET.SubElement(dyn_type, "dynamics")
    ET.SubElement(dynamics, word)
    sound = ET.SubElement(dyn, "sound")
    sound.set("dynamics", {"mp": "54", "mf": "70", "f": "88"}[word])
    directions.append(dyn)
    return directions


def track_part_names(root: ET.Element) -> list[str]:
    return [score_part.findtext("part-name", "") for score_part in root.find("part-list").findall("score-part")]


def remove_parts(root: ET.Element, remove_names: list[str]) -> list[str]:
    normalized = {name.strip().lower() for name in remove_names}
    removed: list[str] = []
    if not normalized:
        return removed
    part_list = root.find("part-list")
    score_parts = part_list.findall("score-part")
    part_map = {score_part.attrib["id"]: score_part.findtext("part-name", "") for score_part in score_parts}
    for score_part in list(score_parts):
        name = score_part.findtext("part-name", "").strip().lower()
        if name in normalized:
            removed.append(score_part.findtext("part-name", ""))
            part_list.remove(score_part)
    for part in list(root.findall("part")):
        name = part_map.get(part.attrib["id"], "").strip().lower()
        if name in normalized:
            root.remove(part)
    return removed


def unique_part_id(root: ET.Element) -> str:
    used = {score_part.attrib["id"] for score_part in root.find("part-list").findall("score-part")}
    index = 1
    while True:
        candidate = f"P{index}"
        if candidate not in used:
            return candidate
        index += 1


def add_instrument_score_part(part_list: ET.Element, part_id: str, name: str, abbr: str, instrument_name: str, channel: int, program: int, volume: int, pan: int) -> None:
    score_part = ET.Element("score-part", {"id": part_id})
    ET.SubElement(score_part, "part-name").text = name
    ET.SubElement(score_part, "part-abbreviation").text = abbr
    score_instrument = ET.SubElement(score_part, "score-instrument", {"id": f"{part_id}-I1"})
    ET.SubElement(score_instrument, "instrument-name").text = instrument_name
    ET.SubElement(score_part, "midi-device", {"id": f"{part_id}-I1", "port": "1"})
    midi_instrument = ET.SubElement(score_part, "midi-instrument", {"id": f"{part_id}-I1"})
    ET.SubElement(midi_instrument, "midi-channel").text = str(channel)
    ET.SubElement(midi_instrument, "midi-program").text = str(program)
    ET.SubElement(midi_instrument, "volume").text = str(volume)
    ET.SubElement(midi_instrument, "pan").text = str(pan)
    part_list.append(score_part)


def add_drum_score_part(part_list: ET.Element, part_id: str, volume: int) -> None:
    score_part = ET.Element("score-part", {"id": part_id})
    ET.SubElement(score_part, "part-name").text = "Drumset"
    ET.SubElement(score_part, "part-abbreviation").text = "Dr."
    for name in ["subkick", "kick", "snare", "clap", "hat", "tom"]:
        score_instrument = ET.SubElement(score_part, "score-instrument", {"id": f"{part_id}-{name}"})
        ET.SubElement(score_instrument, "instrument-name").text = name.replace("_", " ")
        midi_instrument = ET.SubElement(score_part, "midi-instrument", {"id": f"{part_id}-{name}"})
        ET.SubElement(midi_instrument, "midi-channel").text = "10"
        ET.SubElement(midi_instrument, "midi-unpitched").text = str(DRUM_MIDI[name])
        ET.SubElement(midi_instrument, "volume").text = str(volume)
        ET.SubElement(midi_instrument, "pan").text = "0"
    part_list.append(score_part)


def add_upper_part(root: ET.Element, source_part: ET.Element, spec: PreferenceSpec, instrument: str, part_name: str, abbr: str, program: int, pan: int, clef: tuple[str, int], label: str, stem: str) -> str:
    part_id = unique_part_id(root)
    part_list = root.find("part-list")
    add_instrument_score_part(part_list, part_id, part_name, abbr, part_name, len(part_list.findall("score-part")) + 1, program, 72 if instrument != "strings_pad" else 64, pan)
    new_part = ET.Element("part", {"id": part_id})
    previous = None
    entry_after_bars = int(spec.entry_after_bars)
    band = RANGE_BANDS[instrument]
    dynamics = dynamic_word(spec.expression, spec.energy)

    for index, state in enumerate(iter_measure_states(source_part), start=1):
        source_measure = state["measure"]
        measure = ET.Element("measure", dict(source_measure.attrib))
        print_el = source_measure.find("print")
        if print_el is not None:
            measure.append(copy.deepcopy(print_el))
        attrs = source_measure.find("attributes")
        if index == 1 or attrs is not None:
            measure.append(make_attributes(state["divisions"], state["fifths"], state["mode"], state["beats"], state["beat_type"], clef[0], clef[1]))
        if index == max(1, entry_after_bars + 1):
            for direction in make_dynamic_directions(dynamics, label):
                measure.append(direction)

        events = extract_note_events(source_measure, prefer_staff="1")
        beat_duration = state["divisions"] * 4 // state["beat_type"]
        segment = segment_name(index, len(source_part.findall("measure")))
        if not should_play(index, entry_after_bars):
            for chunk in duration_chunks(state["measure_duration"], state["divisions"]):
                measure.append(make_rest(chunk, state["divisions"]))
        else:
            if spec.density == "sparse" or instrument == "strings_pad":
                anchors = [
                    bucket_pitch(events, 0, 2 * beat_duration, "high"),
                    bucket_pitch(events, 2 * beat_duration, state["measure_duration"], "high"),
                ]
                if segment == "finale" and spec.density != "sparse":
                    anchors = [bucket_pitch(events, start, min(start + beat_duration, state["measure_duration"]), "high") for start in range(0, state["measure_duration"], beat_duration)]
            else:
                anchors = [bucket_pitch(events, start, min(start + beat_duration, state["measure_duration"]), "high") for start in range(0, state["measure_duration"], beat_duration)]

            normalized: list[tuple[int | None, int]] = []
            span = state["measure_duration"] // len(anchors) if anchors else state["measure_duration"]
            for pitch in anchors:
                fitted = fit_register(pitch, band, previous)
                if fitted is not None:
                    previous = fitted
                normalized.append((fitted, span))

            merged: list[tuple[int | None, int]] = []
            for pitch, duration in normalized:
                if merged and merged[-1][0] == pitch:
                    merged[-1] = (pitch, merged[-1][1] + duration)
                else:
                    merged.append((pitch, duration))
            for pitch, duration in merged:
                for chunk in duration_chunks(duration, state["divisions"]):
                    if pitch is None:
                        measure.append(make_rest(chunk, state["divisions"]))
                    else:
                        note = make_pitch_note(pitch, chunk, state["divisions"], stem=stem)
                        if spec.expression == "assertive" and chunk <= beat_duration:
                            notations = ET.SubElement(note, "notations")
                            articulations = ET.SubElement(notations, "articulations")
                            ET.SubElement(articulations, "accent")
                        measure.append(note)

        for barline in source_measure.findall("barline"):
            measure.append(copy.deepcopy(barline))
        new_part.append(measure)

    root.append(new_part)
    return part_name


def add_bass_part(root: ET.Element, source_part: ET.Element, spec: PreferenceSpec) -> str:
    part_id = unique_part_id(root)
    part_list = root.find("part-list")
    add_instrument_score_part(part_list, part_id, "Bass", "Bs.", "Electric Bass (finger)", len(part_list.findall("score-part")) + 1, 34, 88 if spec.bass == "strong" else 72, -10)
    bass_part = ET.Element("part", {"id": part_id})
    previous = None
    entry_after_bars = int(spec.entry_after_bars)
    dynamics = dynamic_word(spec.expression, "high" if spec.bass == "strong" else spec.energy)

    for index, state in enumerate(iter_measure_states(source_part), start=1):
        source_measure = state["measure"]
        measure = ET.Element("measure", dict(source_measure.attrib))
        print_el = source_measure.find("print")
        if print_el is not None:
            measure.append(copy.deepcopy(print_el))
        attrs = source_measure.find("attributes")
        if index == 1 or attrs is not None:
            measure.append(make_attributes(state["divisions"], state["fifths"], state["mode"], state["beats"], state["beat_type"], "F", 4))
        if index == max(1, entry_after_bars + 1):
            for direction in make_dynamic_directions(dynamics, "bass enters"):
                measure.append(direction)

        beat_duration = state["divisions"] * 4 // state["beat_type"]
        events = extract_note_events(source_measure, prefer_staff="2") or extract_note_events(source_measure)
        root_pitch = fit_register(bucket_pitch(events, 0, 2 * beat_duration, "low"), RANGE_BANDS["bass"], previous)
        alt_pitch = fit_register(bucket_pitch(events, 2 * beat_duration, state["measure_duration"], "low"), RANGE_BANDS["bass"], root_pitch)
        if root_pitch is not None:
            previous = root_pitch

        half_beat = max(1, beat_duration // 2)

        if not should_play(index, entry_after_bars):
            pattern = [(None, state["measure_duration"])]
        elif spec.groove == "halftime":
            pattern = [(root_pitch, 2 * beat_duration), (None, beat_duration), (alt_pitch, beat_duration)]
        elif spec.groove == "syncopated":
            pattern = [
                (root_pitch, beat_duration),
                (None, half_beat),
                (root_pitch, half_beat),
                (alt_pitch, beat_duration),
                (root_pitch, beat_duration),
            ]
        else:
            pattern = [(root_pitch, beat_duration), (root_pitch, beat_duration), (alt_pitch, beat_duration), (root_pitch, beat_duration)]

        if spec.bass == "light":
            pattern = [(root_pitch, beat_duration), (None, beat_duration), (alt_pitch, beat_duration), (None, beat_duration)]

        for pitch, duration in pattern:
            for chunk in duration_chunks(duration, state["divisions"]):
                measure.append(
                    make_rest(chunk, state["divisions"])
                    if pitch is None
                    else make_pitch_note(pitch, chunk, state["divisions"], stem="down")
                )

        for barline in source_measure.findall("barline"):
            measure.append(copy.deepcopy(barline))
        bass_part.append(measure)

    root.append(bass_part)
    return "Bass"


def drum_pattern(segment: str, spec: PreferenceSpec, measure_index: int, beat_duration: int, measure_duration: int) -> list[tuple[int, str]]:
    half_beat = max(1, beat_duration // 2)
    cycle8 = (measure_index - 1) % 8
    cycle4 = (measure_index - 1) % 4
    if segment == "intro":
        return []
    if spec.drums == "restrained":
        events = [(0, "subkick"), (2 * beat_duration, "clap"), (3 * beat_duration + half_beat, "hat")]
    elif spec.groove == "halftime":
        if cycle4 == 3:
            events = [
                (0, "subkick"),
                (beat_duration + half_beat, "kick"),
                (2 * beat_duration, "clap"),
                (3 * beat_duration + half_beat, "hat"),
            ]
            if measure_duration >= 4 * beat_duration:
                events.append((measure_duration - half_beat, "tom"))
        else:
            events = [
                (0, "subkick"),
                (beat_duration, "hat"),
                (beat_duration + half_beat, "kick"),
                (2 * beat_duration, "clap"),
                (3 * beat_duration + half_beat, "kick"),
            ]
            if measure_duration >= 4 * beat_duration:
                events.append((measure_duration - half_beat, "subkick"))
    elif spec.groove == "syncopated":
        if cycle8 in {3, 7}:
            events = [
                (0, "subkick"),
                (half_beat + beat_duration // 3, "hat"),
                (beat_duration + half_beat, "kick"),
                (2 * beat_duration, "clap"),
                (2 * beat_duration + half_beat, "hat"),
                (3 * beat_duration, "kick"),
            ]
            if measure_duration >= 4 * beat_duration:
                events.append((measure_duration - half_beat, "tom"))
        else:
            events = [
                (0, "subkick"),
                (half_beat + beat_duration // 3, "hat"),
                (beat_duration + half_beat, "kick"),
                (2 * beat_duration, "clap"),
                (3 * beat_duration, "kick"),
            ]
    elif spec.groove == "swung":
        events = [(0, "kick"), (beat_duration + half_beat, "hat"), (2 * beat_duration, "clap"), (3 * beat_duration, "kick"), (3 * beat_duration + half_beat, "hat")]
    if spec.groove == "halftime":
        pass
    elif spec.groove == "syncopated":
        pass
    elif spec.groove == "swung":
        pass
    else:
        events = [(0, "kick"), (beat_duration, "hat"), (2 * beat_duration, "clap"), (3 * beat_duration, "kick"), (3 * beat_duration + half_beat, "hat")]
    return [(onset, kind) for onset, kind in events if 0 <= onset < measure_duration]


def add_drum_part(root: ET.Element, source_part: ET.Element, spec: PreferenceSpec) -> str:
    part_id = unique_part_id(root)
    part_list = root.find("part-list")
    volume = 112 if spec.drums == "strong" else 86
    add_drum_score_part(part_list, part_id, volume)
    drum_part = ET.Element("part", {"id": part_id})
    entry_after_bars = int(spec.entry_after_bars)

    for index, state in enumerate(iter_measure_states(source_part), start=1):
        source_measure = state["measure"]
        measure = ET.Element("measure", dict(source_measure.attrib))
        print_el = source_measure.find("print")
        if print_el is not None:
            measure.append(copy.deepcopy(print_el))
        attrs = source_measure.find("attributes")
        if index == 1 or attrs is not None:
            measure.append(make_attributes(state["divisions"], state["fifths"], state["mode"], state["beats"], state["beat_type"], "percussion", 2))
        if index == max(1, entry_after_bars + 1):
            for direction in make_dynamic_directions(dynamic_word("assertive" if spec.drums == "strong" else spec.expression, spec.energy), "drums enter"):
                measure.append(direction)

        current = 0
        pulse = max(1, state["divisions"] * 4 // state["beat_type"] // 2)
        segment = segment_name(index, len(source_part.findall("measure")))
        events = [] if not should_play(index, entry_after_bars) else drum_pattern(segment, spec, index, state["divisions"] * 4 // state["beat_type"], state["measure_duration"])
        filtered_events: list[tuple[int, str]] = []
        occupied_until = 0
        for onset, kind in sorted(events, key=lambda event: event[0]):
            if onset < occupied_until:
                continue
            filtered_events.append((onset, kind))
            occupied_until = onset + pulse
        for onset, kind in filtered_events:
            if onset > current:
                for chunk in duration_chunks(onset - current, state["divisions"]):
                    measure.append(make_rest(chunk, state["divisions"]))
            measure.append(make_percussion_note(kind, pulse, state["divisions"]))
            current = onset + pulse
        if current < state["measure_duration"]:
            for chunk in duration_chunks(state["measure_duration"] - current, state["divisions"]):
                measure.append(make_rest(chunk, state["divisions"]))
        for barline in source_measure.findall("barline"):
            measure.append(copy.deepcopy(barline))
        drum_part.append(measure)

    root.append(drum_part)
    return "Drumset"


def apply_expression(root: ET.Element, spec: PreferenceSpec) -> None:
    if spec.expression == "plain":
        return
    dynamics = dynamic_word(spec.expression, spec.energy)
    for part in root.findall("part"):
        first_measure = part.find("measure")
        if first_measure is None:
            continue
        if first_measure.find("direction") is None:
            for direction in make_dynamic_directions(dynamics):
                first_measure.insert(1, direction)


def validate_score(root: ET.Element, strict_duration_part_ids: set[str] | None = None) -> None:
    part_list = root.find("part-list")
    score_parts = part_list.findall("score-part")
    score_part_ids = [score_part.attrib["id"] for score_part in score_parts]
    if len(score_part_ids) != len(set(score_part_ids)):
        raise ValueError("Duplicate score-part ids detected")

    instrument_ids = []
    for score_part in score_parts:
        instrument_ids.extend(score_instrument.attrib["id"] for score_instrument in score_part.findall("score-instrument"))
    if len(instrument_ids) != len(set(instrument_ids)):
        raise ValueError("Duplicate score-instrument ids detected")

    if len(root.findall("part")) != len(score_parts):
        raise ValueError("Mismatch between score-part declarations and part bodies")

    for part in root.findall("part"):
        divisions = 12
        beats = 4
        beat_type = 4
        expected = None
        check_durations = strict_duration_part_ids is None or part.attrib["id"] in strict_duration_part_ids
        for measure in part.findall("measure"):
            attrs = measure.find("attributes")
            if attrs is not None:
                if attrs.find("divisions") is not None:
                    divisions = int(attrs.findtext("divisions"))
                time = attrs.find("time")
                if time is not None:
                    beats = int(time.findtext("beats"))
                    beat_type = int(time.findtext("beat-type"))
            expected = divisions * beats * 4 // beat_type
            time_pos = 0
            last_onset = 0
            for child in measure:
                if child.tag == "note":
                    duration = int(child.findtext("duration", "0"))
                    onset = last_onset if child.find("chord") is not None else time_pos
                    if child.find("chord") is None:
                        last_onset = onset
                        time_pos += duration
                elif child.tag == "backup":
                    time_pos -= int(child.findtext("duration", "0"))
                elif child.tag == "forward":
                    time_pos += int(child.findtext("duration", "0"))
            if check_durations and time_pos != expected:
                raise ValueError(f"Measure duration mismatch in part {part.attrib['id']} measure {measure.attrib.get('number')}: expected {expected}, got {time_pos}")


def build_output_path(source_score: Path, goal: str, preset: str, explicit_output: str | None) -> Path:
    if explicit_output:
        return Path(explicit_output)
    tag = slugify(preset if preset != "none" else goal)
    return Path("assets/_build/xml") / f"{source_score.stem}.{tag}.musicxml"


def arrange_score(spec: PreferenceSpec, output_path: Path) -> dict[str, object]:
    source_path = Path(spec.source_score)
    root = load_xml_root(source_path)
    source_info = detect_source_info(root)
    original_part_ids = {part.attrib["id"] for part in root.findall("part")}

    removed = remove_parts(root, spec.remove_instruments)
    source_part = first_part(root)
    source_info = detect_source_info(root)
    semitones, fifths, mode = parse_target_key(spec.target_key, source_info)
    if spec.target_key != "keep":
        transpose_root(root, semitones, fifths, mode)
    scale_tempos(root, tempo_factor(spec.tempo, source_info))

    added: list[str] = []
    part_names = {name.lower() for name in track_part_names(root)}
    if "violin" in spec.add_instruments and "violin" not in part_names:
        added.append(add_upper_part(root, source_part, spec, "violin", "Violin", "Vln.", 41, -10, ("G", 2), "violin enters", "up"))
    if "cello" in spec.add_instruments and "cello" not in part_names:
        added.append(add_upper_part(root, source_part, spec, "cello", "Cello", "Vc.", 43, 8, ("F", 4), "cello enters", "down"))
    if "strings_pad" in spec.add_instruments and "strings pad" not in part_names:
        added.append(add_upper_part(root, source_part, spec, "strings_pad", "Strings Pad", "Pad.", 49, 0, ("G", 2), "pad enters", "up"))
    if "bass" in spec.add_instruments and "bass" not in part_names:
        added.append(add_bass_part(root, source_part, spec))
    if "drumset" in spec.add_instruments and "drumset" not in part_names:
        added.append(add_drum_part(root, source_part, spec))

    apply_expression(root, spec)
    generated_part_ids = {part.attrib["id"] for part in root.findall("part")} - original_part_ids
    validate_score(root, strict_duration_part_ids=generated_part_ids)
    ET.indent(root, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_path, encoding="UTF-8", xml_declaration=True)

    return {
        "input_path": str(source_path),
        "output_path": str(output_path.resolve()),
        "resolved_preferences": asdict(spec),
        "parts_added": added,
        "parts_removed": removed,
        "key_change": spec.target_key,
        "tempo_change": spec.tempo,
        "limitations": [
            "v1 uses deterministic heuristics",
            "v1 does not perform arbitrary reharmonization",
            "playback humanization is deferred to MIDI/audio downstream steps",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arrange a MusicXML score into a new MusicXML score.")
    parser.add_argument("source_score")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--output")
    parser.add_argument("--preset", default="auto")
    parser.add_argument("--target-key", default="auto")
    parser.add_argument("--tempo", default="auto")
    parser.add_argument("--add-instruments", default="")
    parser.add_argument("--remove-instruments", default="")
    parser.add_argument("--vibe", default="")
    parser.add_argument("--energy", default="auto")
    parser.add_argument("--density", default="auto")
    parser.add_argument("--groove", default="auto")
    parser.add_argument("--bass", default="auto")
    parser.add_argument("--drums", default="auto")
    parser.add_argument("--entry-after-bars", default="auto")
    parser.add_argument("--melody-treatment", default="auto")
    parser.add_argument("--harmony-treatment", default="auto")
    parser.add_argument("--register-shift", default="auto")
    parser.add_argument("--expression", default="auto")
    parser.add_argument("--print-summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_root = load_xml_root(Path(args.source_score))
    source_info = detect_source_info(source_root)
    spec = merge_preferences(args, source_info)
    output_path = build_output_path(Path(args.source_score), spec.goal, spec.preset, args.output)
    summary = arrange_score(spec, output_path)
    if args.print_summary:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
