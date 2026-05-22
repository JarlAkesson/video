#!/usr/bin/env python3

import argparse
import copy
import xml.etree.ElementTree as ET
from pathlib import Path


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

DURATION_TO_TYPE = {
    3: "16th",
    6: "eighth",
    12: "quarter",
    24: "half",
    48: "whole",
}

DRUMS = {
    "subkick": ("B", None, 1),
    "kick": ("C", None, 2),
    "snare": ("D", None, 2),
    "clap": ("E", -1, 2),
    "hat": ("F", 1, 2),
    "tom": ("F", None, 2),
}


def pitch_to_midi(pitch):
    step = pitch.findtext("step")
    alter = int(pitch.findtext("alter", "0"))
    octave = int(pitch.findtext("octave"))
    return 12 * (octave + 1) + STEP_TO_PC[step] + alter


def midi_to_pitch(midi):
    pc = midi % 12
    octave = midi // 12 - 1
    step, alter = PC_TO_STEP_ALTER_FLAT[pc]
    return step, alter, octave


def set_pitch_from_midi(pitch, midi):
    step, alter, octave = midi_to_pitch(midi)
    for child in list(pitch):
        pitch.remove(child)
    ET.SubElement(pitch, "step").text = step
    if alter is not None:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(octave)


def duration_chunks(duration):
    chunks = []
    for unit in (24, 12, 6, 3):
        while duration >= unit:
            chunks.append(unit)
            duration -= unit
    if duration != 0:
        raise ValueError(f"Unsupported residual duration {duration}")
    return chunks


def part_states(part):
    divisions = 12
    beats = 4
    beat_type = 4
    fifths = -2

    for measure in part.findall("measure"):
        attrs = measure.find("attributes")
        if attrs is not None:
            div = attrs.find("divisions")
            if div is not None:
                divisions = int(div.text)
            time = attrs.find("time")
            if time is not None:
                beats = int(time.findtext("beats"))
                beat_type = int(time.findtext("beat-type"))
            key = attrs.find("key")
            if key is not None and key.find("fifths") is not None:
                fifths = int(key.findtext("fifths"))
        yield {
            "measure": measure,
            "divisions": divisions,
            "beats": beats,
            "beat_type": beat_type,
            "measure_duration": divisions * beats * 4 // beat_type,
            "fifths": fifths,
        }


def transpose_existing_parts(root, semitones, new_fifths):
    work_title = root.find("./work/work-title")
    if work_title is not None:
        work_title.text = "Bach Hip-Hop Remix"

    for part in root.findall("part"):
        for measure in part.findall("measure"):
            attrs = measure.find("attributes")
            if attrs is not None:
                key = attrs.find("key")
                if key is not None:
                    fifths = key.find("fifths")
                    if fifths is None:
                        fifths = ET.SubElement(key, "fifths")
                    fifths.text = str(new_fifths)
                    mode = key.find("mode")
                    if mode is None:
                        mode = ET.SubElement(key, "mode")
                    mode.text = "minor"

            for note in measure.findall("note"):
                pitch = note.find("pitch")
                if pitch is None:
                    continue
                midi = pitch_to_midi(pitch) + semitones
                set_pitch_from_midi(pitch, midi)


def scale_tempos(root, factor):
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


def extract_staff_events(measure, staff_number):
    events = []
    time_pos = 0
    last_onset = 0
    for child in measure:
        if child.tag == "note":
            duration = int(child.findtext("duration", "0"))
            onset = last_onset if child.find("chord") is not None else time_pos
            if child.find("rest") is None and child.findtext("staff", "1") == str(staff_number):
                pitch = child.find("pitch")
                if pitch is not None:
                    events.append(
                        {
                            "onset": onset,
                            "duration": duration,
                            "midi": pitch_to_midi(pitch),
                        }
                    )
            if child.find("chord") is None:
                last_onset = onset
                time_pos += duration
        elif child.tag == "backup":
            time_pos -= int(child.findtext("duration", "0"))
        elif child.tag == "forward":
            time_pos += int(child.findtext("duration", "0"))
    return events


def lowest_in_bucket(events, start, end):
    bucket = [event["midi"] for event in events if start <= event["onset"] < end]
    if not bucket:
        bucket = [event["midi"] for event in events if event["onset"] >= start]
    if not bucket:
        bucket = [event["midi"] for event in events if event["onset"] < start]
    return min(bucket) if bucket else None


def fit_bass_register(midi, previous):
    if midi is None:
        return None
    candidates = []
    for shift in (-36, -24, -12, 0):
        candidate = midi + shift
        if 34 <= candidate <= 52:
            candidates.append(candidate)
    if not candidates:
        while midi > 52:
            midi -= 12
        while midi < 34:
            midi += 12
        return midi
    if previous is None:
        return min(candidates, key=lambda value: abs(value - 41))
    return min(candidates, key=lambda value: abs(value - previous))


def make_score_part(part_id, name, abbr, instrument_name, channel, program, volume, pan):
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
    return score_part


def make_note_from_midi(midi, duration, voice="1"):
    note = ET.Element("note")
    pitch = ET.SubElement(note, "pitch")
    step, alter, octave = midi_to_pitch(midi)
    ET.SubElement(pitch, "step").text = step
    if alter is not None:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(octave)
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = voice
    ET.SubElement(note, "type").text = DURATION_TO_TYPE[duration]
    ET.SubElement(note, "stem").text = "down"
    return note


def make_rest(duration, voice="1"):
    note = ET.Element("note")
    ET.SubElement(note, "rest")
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = voice
    ET.SubElement(note, "type").text = DURATION_TO_TYPE[duration]
    return note


def make_drum_note(kind, duration):
    step, alter, octave = DRUMS[kind]
    note = ET.Element("note")
    pitch = ET.SubElement(note, "pitch")
    ET.SubElement(pitch, "step").text = step
    if alter is not None:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(octave)
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = DURATION_TO_TYPE[duration]
    ET.SubElement(note, "stem").text = "up"
    if kind == "hat":
        ET.SubElement(note, "notehead").text = "x"
    return note


def make_attributes(divisions, fifths, beats, beat_type, clef_sign, clef_line):
    attrs = ET.Element("attributes")
    ET.SubElement(attrs, "divisions").text = str(divisions)
    key = ET.SubElement(attrs, "key")
    ET.SubElement(key, "fifths").text = str(fifths)
    ET.SubElement(key, "mode").text = "minor"
    time = ET.SubElement(attrs, "time")
    ET.SubElement(time, "beats").text = str(beats)
    ET.SubElement(time, "beat-type").text = str(beat_type)
    clef = ET.SubElement(attrs, "clef")
    ET.SubElement(clef, "sign").text = clef_sign
    ET.SubElement(clef, "line").text = str(clef_line)
    return attrs


def segment_name(measure_index):
    if measure_index <= 8:
        return "intro"
    if measure_index <= 24:
        return "shadow"
    if measure_index <= 40:
        return "swagger"
    if measure_index <= 56:
        return "drive"
    return "finale"


def bass_pattern(root, alt, segment):
    if root is None:
        return [(None, 48)]
    alt = alt if alt is not None else root
    if segment == "intro":
        return [(None, 48)]
    if segment == "shadow":
        return [(root, 12), (None, 12), (alt, 12), (None, 12)]
    if segment == "swagger":
        return [(root, 12), (None, 6), (root, 6), (alt, 12), (root, 12)]
    if segment == "drive":
        return [(root, 12), (None, 6), (alt, 6), (root, 12), (alt, 12)]
    return [(root, 12), (alt, 6), (root, 6), (alt, 12), (root, 12)]


def drum_pattern(segment, measure_index):
    cycle8 = (measure_index - 1) % 8
    cycle4 = (measure_index - 1) % 4
    if segment == "intro":
        return []
    if segment == "shadow":
        if cycle4 == 1:
            return [(0, "subkick"), (24, "clap"), (30, "kick"), (42, "hat")]
        return [(0, "subkick"), (18, "kick"), (24, "clap"), (42, "hat")]
    if segment == "swagger":
        if cycle8 in {3, 7}:
            return [(0, "subkick"), (9, "hat"), (18, "kick"), (24, "clap"), (33, "hat"), (39, "kick"), (45, "tom")]
        return [(0, "subkick"), (9, "hat"), (18, "kick"), (24, "clap"), (39, "kick")]
    if segment == "drive":
        if cycle4 == 3:
            return [(0, "subkick"), (9, "hat"), (15, "kick"), (24, "clap"), (30, "kick"), (39, "hat"), (45, "tom")]
        return [(0, "subkick"), (12, "hat"), (18, "kick"), (24, "clap"), (39, "kick"), (45, "kick")]
    # finale
    if cycle8 in {6, 7}:
        return [(0, "subkick"), (9, "hat"), (18, "kick"), (24, "clap"), (30, "kick"), (39, "hat"), (42, "tom"), (45, "subkick")]
    return [(0, "subkick"), (12, "hat"), (18, "kick"), (24, "clap"), (33, "hat"), (39, "kick"), (45, "subkick")]


def add_bass_part(root, piano_part, part_list):
    part_list.append(make_score_part("P3", "Bass", "Bs.", "Electric Bass (finger)", 3, 34, 86, -8))
    bass_part = ET.Element("part", {"id": "P3"})
    previous = None

    for measure_index, state in enumerate(part_states(piano_part), start=1):
        measure = ET.Element("measure", dict(state["measure"].attrib))
        print_el = state["measure"].find("print")
        if print_el is not None:
            measure.append(copy.deepcopy(print_el))

        attrs = state["measure"].find("attributes")
        if measure_index == 1 or attrs is not None:
            measure.append(make_attributes(state["divisions"], state["fifths"], state["beats"], state["beat_type"], "F", 4))

        events = extract_staff_events(state["measure"], 2)
        beat_duration = state["divisions"] * 4 // state["beat_type"]
        bass_root = lowest_in_bucket(events, 0, 2 * beat_duration)
        alt = lowest_in_bucket(events, 2 * beat_duration, state["measure_duration"])
        bass_root = fit_bass_register(bass_root, previous)
        alt = fit_bass_register(alt, bass_root)
        if bass_root is not None:
            previous = bass_root

        for pitch, duration in bass_pattern(bass_root, alt, segment_name(measure_index)):
            for chunk in duration_chunks(duration):
                measure.append(make_rest(chunk) if pitch is None else make_note_from_midi(pitch, chunk))

        for barline in state["measure"].findall("barline"):
            measure.append(copy.deepcopy(barline))
        bass_part.append(measure)

    root.append(bass_part)


def add_drum_part(root, piano_part, part_list):
    part_list.append(make_score_part("P4", "Drumset", "Dr.", "Drumset", 10, 1, 110, 0))
    drum_part = ET.Element("part", {"id": "P4"})

    labels = {
        9: "drums and bass enter",
        25: "heavier pocket",
        41: "harder low end",
        57: "final push",
    }

    for measure_index, state in enumerate(part_states(piano_part), start=1):
        measure = ET.Element("measure", dict(state["measure"].attrib))
        print_el = state["measure"].find("print")
        if print_el is not None:
            measure.append(copy.deepcopy(print_el))

        attrs = state["measure"].find("attributes")
        if measure_index == 1 or attrs is not None:
            measure.append(make_attributes(state["divisions"], state["fifths"], state["beats"], state["beat_type"], "percussion", 2))

        if measure_index in labels:
            direction = ET.Element("direction", {"placement": "above"})
            direction_type = ET.SubElement(direction, "direction-type")
            ET.SubElement(direction_type, "words").text = labels[measure_index]
            measure.append(direction)
            dyn = ET.Element("direction", {"placement": "below"})
            dyn_type = ET.SubElement(dyn, "direction-type")
            dynamics = ET.SubElement(dyn_type, "dynamics")
            ET.SubElement(dynamics, "f")
            sound = ET.SubElement(dyn, "sound")
            sound.set("dynamics", "92")
            measure.append(dyn)

        current = 0
        for onset, kind in drum_pattern(segment_name(measure_index), measure_index):
            if onset > current:
                for chunk in duration_chunks(onset - current):
                    measure.append(make_rest(chunk))
            measure.append(make_drum_note(kind, 3))
            current = onset + 3
        if current < state["measure_duration"]:
            for chunk in duration_chunks(state["measure_duration"] - current):
                measure.append(make_rest(chunk))

        for barline in state["measure"].findall("barline"):
            measure.append(copy.deepcopy(barline))
        drum_part.append(measure)

    root.append(drum_part)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="assets/_build/xml/G_Minor_Bach_With_Violin.musicxml",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default="assets/_build/xml/Bach_Hiphop_Remix_F_Minor.musicxml",
        type=Path,
    )
    args = parser.parse_args()

    root = ET.parse(args.input).getroot()
    part_list = root.find("part-list")
    parts = root.findall("part")
    if part_list is None or len(parts) != 2:
        raise ValueError("Expected piano+violin arranged score as input")

    transpose_existing_parts(root, semitones=-2, new_fifths=-4)
    scale_tempos(root, factor=0.85)
    piano_part = root.findall("part")[0]
    add_bass_part(root, piano_part, part_list)
    add_drum_part(root, piano_part, part_list)

    ET.indent(root, space="  ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(args.output, encoding="UTF-8", xml_declaration=True)


if __name__ == "__main__":
    main()
