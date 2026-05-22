#!/usr/bin/env python3

import argparse
import copy
import xml.etree.ElementTree as ET
import zipfile
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

PC_TO_STEP_ALTER = {
    0: ("C", None),
    1: ("C", 1),
    2: ("D", None),
    3: ("E", -1),
    4: ("E", None),
    5: ("F", None),
    6: ("F", 1),
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


def pitch_to_midi(note):
    pitch = note.find("pitch")
    if pitch is None:
        return None
    step = pitch.findtext("step")
    alter = int(pitch.findtext("alter", "0"))
    octave = int(pitch.findtext("octave"))
    return 12 * (octave + 1) + STEP_TO_PC[step] + alter


def midi_to_pitch(midi):
    pc = midi % 12
    octave = midi // 12 - 1
    step, alter = PC_TO_STEP_ALTER[pc]
    return step, alter, octave


def load_root(path: Path):
    with zipfile.ZipFile(path) as zf:
        xml_name = next(
            name for name in zf.namelist() if name.endswith(".xml") and not name.startswith("META-INF/")
        )
        return ET.fromstring(zf.read(xml_name))


def measure_state_iter(part):
    divisions = None
    beats = None
    beat_type = None
    fifths = None

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

        if divisions is None or beats is None or beat_type is None:
            raise ValueError("Missing divisions or time signature before note data")

        yield {
            "measure": measure,
            "divisions": divisions,
            "beats": beats,
            "beat_type": beat_type,
            "measure_duration": divisions * beats * 4 // beat_type,
            "fifths": fifths,
        }


def extract_staff1_events(measure):
    events = []
    time_pos = 0
    last_onset = 0

    for child in measure:
        if child.tag == "note":
            duration = int(child.findtext("duration", "0"))
            onset = last_onset if child.find("chord") is not None else time_pos
            if child.find("rest") is None and child.findtext("staff", "1") == "1" and child.find("grace") is None:
                midi = pitch_to_midi(child)
                if midi is not None:
                    events.append(
                        {
                            "onset": onset,
                            "duration": duration,
                            "midi": midi,
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


def pick_bucket_pitch(events, start, end):
    bucket = [event for event in events if start <= event["onset"] < end]
    if not bucket:
        bucket = [event for event in events if event["onset"] >= start]
    if not bucket:
        bucket = [event for event in events if event["onset"] < start]
    if not bucket:
        return None
    return max(bucket, key=lambda event: (event["midi"], -event["onset"]))["midi"]


def pick_distinct_bucket_pitch(events, start, end, avoid_pitch):
    bucket = [event for event in events if start <= event["onset"] < end and event["midi"] != avoid_pitch]
    if not bucket:
        return pick_bucket_pitch(events, start, end)
    return max(bucket, key=lambda event: (event["midi"], -event["onset"]))["midi"]


def smooth_violin_octave(raw_midi, previous_midi):
    if raw_midi is None:
        return None

    candidates = []
    for shift in (-12, 0, 12, 24):
        candidate = raw_midi + shift
        if 62 <= candidate <= 88:
            candidates.append(candidate)

    if not candidates:
        while raw_midi < 62:
            raw_midi += 12
        while raw_midi > 88:
            raw_midi -= 12
        return raw_midi

    if previous_midi is None:
        return min(candidates, key=lambda midi: (abs(midi - 74), abs(midi - 79)))

    def cost(candidate):
        jump = abs(candidate - previous_midi)
        penalty = 0
        if jump > 9:
            penalty += 8
        if candidate < 67:
            penalty += 3
        return jump + penalty

    return min(candidates, key=cost)


def build_measure_plan(events, measure_duration, beat_duration, measure_index):
    beat_starts = list(range(0, measure_duration, beat_duration))
    quarter_pitches = [pick_bucket_pitch(events, start, min(start + beat_duration, measure_duration)) for start in beat_starts]
    quarter_pitches = [pitch for pitch in quarter_pitches if pitch is not None]

    if not quarter_pitches:
        return [("rest", measure_duration)]

    if measure_duration == 4 * beat_duration:
        full_quarters = [pick_bucket_pitch(events, start, start + beat_duration) for start in beat_starts]
        cadence_bar = measure_index % 8 in {0, 4}
        moving_bar = len(set(p for p in full_quarters if p is not None)) >= 3

        if cadence_bar or moving_bar:
            return [(pitch, beat_duration) for pitch in full_quarters]

        first = pick_bucket_pitch(events, 0, 2 * beat_duration)
        second = pick_distinct_bucket_pitch(events, 2 * beat_duration, measure_duration, first)
        return [(first, 2 * beat_duration), (second, 2 * beat_duration)]

    anchor = quarter_pitches[0]
    return [(anchor, measure_duration)]


def merge_plan(plan):
    merged = []
    for pitch, duration in plan:
        if merged and merged[-1][0] == pitch:
            merged[-1] = (pitch, merged[-1][1] + duration)
        else:
            merged.append((pitch, duration))
    return merged


def make_attributes(state):
    attrs = ET.Element("attributes")
    divisions = ET.SubElement(attrs, "divisions")
    divisions.text = str(state["divisions"])

    key = ET.SubElement(attrs, "key")
    fifths = ET.SubElement(key, "fifths")
    fifths.text = str(state["fifths"] if state["fifths"] is not None else 0)

    time = ET.SubElement(attrs, "time")
    beats = ET.SubElement(time, "beats")
    beats.text = str(state["beats"])
    beat_type = ET.SubElement(time, "beat-type")
    beat_type.text = str(state["beat_type"])

    clef = ET.SubElement(attrs, "clef")
    sign = ET.SubElement(clef, "sign")
    sign.text = "G"
    line = ET.SubElement(clef, "line")
    line.text = "2"
    return attrs


def make_direction():
    direction = ET.Element("direction", {"placement": "above"})
    direction_type = ET.SubElement(direction, "direction-type")
    words = ET.SubElement(direction_type, "words")
    words.text = "cantabile"

    dynamics_direction = ET.Element("direction", {"placement": "below"})
    dynamics_type = ET.SubElement(dynamics_direction, "direction-type")
    dynamics = ET.SubElement(dynamics_type, "dynamics")
    ET.SubElement(dynamics, "mf")
    sound = ET.SubElement(dynamics_direction, "sound")
    sound.set("dynamics", "70")
    return [direction, dynamics_direction]


def make_note(duration, pitch_midi=None):
    note = ET.Element("note")
    if pitch_midi is None:
        ET.SubElement(note, "rest")
    else:
        pitch = ET.SubElement(note, "pitch")
        step, alter, octave = midi_to_pitch(pitch_midi)
        step_el = ET.SubElement(pitch, "step")
        step_el.text = step
        if alter is not None:
            alter_el = ET.SubElement(pitch, "alter")
            alter_el.text = str(alter)
        octave_el = ET.SubElement(pitch, "octave")
        octave_el.text = str(octave)

    duration_el = ET.SubElement(note, "duration")
    duration_el.text = str(duration)
    voice = ET.SubElement(note, "voice")
    voice.text = "1"
    note_type = ET.SubElement(note, "type")
    note_type.text = DURATION_TO_TYPE[duration]
    stem = ET.SubElement(note, "stem")
    stem.text = "up"
    return note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="assets/xml/G_Minor_Bach_Original.mxl",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default="assets/_build/xml/G_Minor_Bach_With_Violin.musicxml",
        type=Path,
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    root = load_root(args.input)
    part_list = root.find("part-list")
    piano_part = root.find("part")
    if part_list is None or piano_part is None:
        raise ValueError("Expected score-partwise with part-list and one part")

    violin_score_part = ET.Element("score-part", {"id": "P2"})
    part_name = ET.SubElement(violin_score_part, "part-name")
    part_name.text = "Violin"
    part_abbrev = ET.SubElement(violin_score_part, "part-abbreviation")
    part_abbrev.text = "Vln."
    score_instrument = ET.SubElement(violin_score_part, "score-instrument", {"id": "P2-I1"})
    instrument_name = ET.SubElement(score_instrument, "instrument-name")
    instrument_name.text = "Violin"
    ET.SubElement(violin_score_part, "midi-device", {"id": "P2-I1", "port": "1"})
    midi_instrument = ET.SubElement(violin_score_part, "midi-instrument", {"id": "P2-I1"})
    midi_channel = ET.SubElement(midi_instrument, "midi-channel")
    midi_channel.text = "2"
    midi_program = ET.SubElement(midi_instrument, "midi-program")
    midi_program.text = "41"
    volume = ET.SubElement(midi_instrument, "volume")
    volume.text = "72"
    pan = ET.SubElement(midi_instrument, "pan")
    pan.text = "-10"
    part_list.append(violin_score_part)

    violin_part = ET.Element("part", {"id": "P2"})
    previous_midi = None

    for measure_index, state in enumerate(measure_state_iter(piano_part), start=1):
        source_measure = state["measure"]
        violin_measure = ET.Element("measure", dict(source_measure.attrib))

        print_el = source_measure.find("print")
        if print_el is not None:
            violin_measure.append(copy.deepcopy(print_el))

        attrs = source_measure.find("attributes")
        if measure_index == 1 or attrs is not None:
            violin_measure.append(make_attributes(state))

        if measure_index == 1:
            for direction in make_direction():
                violin_measure.append(direction)

        beat_duration = state["divisions"] * 4 // state["beat_type"]
        events = extract_staff1_events(source_measure)
        plan = build_measure_plan(events, state["measure_duration"], beat_duration, measure_index)

        smoothed_plan = []
        for pitch, duration in plan:
            if pitch == "rest":
                smoothed_plan.append((None, duration))
                continue
            chosen = smooth_violin_octave(pitch, previous_midi)
            previous_midi = chosen
            smoothed_plan.append((chosen, duration))

        for pitch, duration in smoothed_plan:
            if duration not in DURATION_TO_TYPE:
                raise ValueError(f"Unsupported duration {duration} in measure {measure_index}")
            violin_measure.append(make_note(duration, pitch))

        for barline in source_measure.findall("barline"):
            violin_measure.append(copy.deepcopy(barline))

        violin_part.append(violin_measure)

    root.append(violin_part)
    ET.indent(root, space="  ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(args.output, encoding="UTF-8", xml_declaration=True)


if __name__ == "__main__":
    main()
