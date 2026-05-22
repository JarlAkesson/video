#!/usr/bin/env python3

import argparse
import copy
import xml.etree.ElementTree as ET
from pathlib import Path


DURATION_TO_TYPE = {
    3: "16th",
    6: "eighth",
    12: "quarter",
    24: "half",
    48: "whole",
}


GM = {
    "kick": ("C", None, 2),
    "snare": ("D", None, 2),
    "hat": ("F", 1, 2),
    "tom": ("A", None, 2),
    "clap": ("E", None, 2),
}


def make_score_part():
    score_part = ET.Element("score-part", {"id": "P3"})
    ET.SubElement(score_part, "part-name").text = "Drumset"
    ET.SubElement(score_part, "part-abbreviation").text = "Dr."
    score_instrument = ET.SubElement(score_part, "score-instrument", {"id": "P3-I1"})
    ET.SubElement(score_instrument, "instrument-name").text = "Drumset"
    ET.SubElement(score_part, "midi-device", {"id": "P3-I1", "port": "1"})
    midi_instrument = ET.SubElement(score_part, "midi-instrument", {"id": "P3-I1"})
    ET.SubElement(midi_instrument, "midi-channel").text = "10"
    ET.SubElement(midi_instrument, "midi-program").text = "1"
    ET.SubElement(midi_instrument, "volume").text = "86"
    ET.SubElement(midi_instrument, "pan").text = "0"
    return score_part


def make_attributes(divisions, fifths, beats, beat_type):
    attrs = ET.Element("attributes")
    ET.SubElement(attrs, "divisions").text = str(divisions)
    key = ET.SubElement(attrs, "key")
    ET.SubElement(key, "fifths").text = str(fifths)
    time = ET.SubElement(attrs, "time")
    ET.SubElement(time, "beats").text = str(beats)
    ET.SubElement(time, "beat-type").text = str(beat_type)
    clef = ET.SubElement(attrs, "clef")
    ET.SubElement(clef, "sign").text = "percussion"
    ET.SubElement(clef, "line").text = "2"
    return attrs


def make_note(kind, duration):
    step, alter, octave = GM[kind]
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
        notehead = ET.SubElement(note, "notehead")
        notehead.text = "x"
    return note


def make_rest(duration):
    note = ET.Element("note")
    ET.SubElement(note, "rest")
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = DURATION_TO_TYPE[duration]
    return note


def duration_chunks(duration):
    chunks = []
    for unit in (24, 12, 6, 3):
        while duration >= unit:
            chunks.append(unit)
            duration -= unit
    if duration != 0:
        raise ValueError(f"Unsupported residual duration {duration}")
    return chunks


def make_direction(label):
    direction = ET.Element("direction", {"placement": "above"})
    direction_type = ET.SubElement(direction, "direction-type")
    words = ET.SubElement(direction_type, "words")
    words.text = label

    dyn = ET.Element("direction", {"placement": "below"})
    dyn_type = ET.SubElement(dyn, "direction-type")
    dynamics = ET.SubElement(dyn_type, "dynamics")
    ET.SubElement(dynamics, "mf")
    sound = ET.SubElement(dyn, "sound")
    sound.set("dynamics", "76")
    return [direction, dyn]


def segment_name(measure_index):
    if measure_index <= 8:
        return "none"
    if measure_index <= 24:
        return "shadow"
    if measure_index <= 40:
        return "swagger"
    if measure_index <= 56:
        return "drive"
    return "finale"


def pattern_for_measure(measure_index):
    seg = segment_name(measure_index)
    cycle8 = (measure_index - 1) % 8
    cycle4 = (measure_index - 1) % 4

    if seg == "none":
        return []

    if seg == "shadow":
        if cycle8 == 7:
            return [
                (0, "tom"),
                (18, "kick"),
                (24, "clap"),
                (33, "hat"),
                (42, "kick"),
            ]
        if cycle4 == 1:
            return [
                (0, "kick"),
                (21, "hat"),
                (24, "clap"),
                (30, "kick"),
                (45, "hat"),
            ]
        return [
            (0, "tom"),
            (18, "kick"),
            (24, "clap"),
            (33, "hat"),
            (42, "kick"),
        ]

    if seg == "swagger":
        if cycle8 in {3, 7}:
            return [
                (0, "kick"),
                (9, "hat"),
                (18, "kick"),
                (24, "clap"),
                (30, "tom"),
                (33, "hat"),
                (42, "kick"),
            ]
        return [
            (0, "kick"),
            (9, "hat"),
            (18, "kick"),
            (24, "clap"),
            (33, "hat"),
            (39, "kick"),
        ]

    if seg == "drive":
        if cycle4 == 3:
            return [
                (0, "kick"),
                (9, "hat"),
                (15, "kick"),
                (24, "clap"),
                (30, "kick"),
                (33, "hat"),
                (42, "tom"),
                (45, "kick"),
            ]
        return [
            (0, "kick"),
            (9, "hat"),
            (18, "kick"),
            (24, "clap"),
            (33, "hat"),
            (39, "kick"),
            (45, "kick"),
        ]

    # finale
    if cycle8 in {6, 7}:
        return [
            (0, "kick"),
            (9, "hat"),
            (18, "kick"),
            (24, "clap"),
            (30, "kick"),
            (33, "hat"),
            (42, "tom"),
            (45, "kick"),
        ]
    return [
        (0, "kick"),
        (9, "hat"),
        (18, "kick"),
        (24, "clap"),
        (30, "tom"),
        (33, "hat"),
        (39, "kick"),
        (45, "kick"),
    ]


def add_pattern(measure, events):
    current = 0
    for onset, kind in sorted(events):
        if onset > current:
            for chunk in duration_chunks(onset - current):
                measure.append(make_rest(chunk))
        measure.append(make_note(kind, 3))
        current = onset + 3
    if current < 48:
        for chunk in duration_chunks(48 - current):
            measure.append(make_rest(chunk))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="assets/_build/xml/G_Minor_Bach_With_Violin.musicxml",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default="assets/_build/xml/G_Minor_Bach_With_Violin_And_Drums_Swagger.musicxml",
        type=Path,
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    root = ET.parse(args.input).getroot()
    part_list = root.find("part-list")
    parts = root.findall("part")
    if part_list is None or len(parts) < 2:
        raise ValueError("Expected arranged score with piano and violin parts")

    part_list.append(make_score_part())

    piano_part = parts[0]
    drum_part = ET.Element("part", {"id": "P3"})

    divisions = 12
    beats = 4
    beat_type = 4
    fifths = -2

    for measure_index, source_measure in enumerate(piano_part.findall("measure"), start=1):
        drum_measure = ET.Element("measure", dict(source_measure.attrib))

        print_el = source_measure.find("print")
        if print_el is not None:
            drum_measure.append(copy.deepcopy(print_el))

        attrs = source_measure.find("attributes")
        if attrs is not None:
            div_el = attrs.find("divisions")
            if div_el is not None:
                divisions = int(div_el.text)
            time = attrs.find("time")
            if time is not None:
                beats = int(time.findtext("beats"))
                beat_type = int(time.findtext("beat-type"))
            key = attrs.find("key")
            if key is not None and key.find("fifths") is not None:
                fifths = int(key.findtext("fifths"))

        if measure_index == 1 or attrs is not None:
            drum_measure.append(make_attributes(divisions, fifths, beats, beat_type))

        if measure_index in {9, 25, 41, 57}:
            labels = {
                9: "drums enter, dark",
                25: "drums gain swagger",
                41: "drums hit harder",
                57: "drums close in",
            }
            for direction in make_direction(labels[measure_index]):
                drum_measure.append(direction)

        if beats == 4 and beat_type == 4 and divisions == 12:
            add_pattern(drum_measure, pattern_for_measure(measure_index))
        else:
            drum_measure.append(make_rest(divisions * beats * 4 // beat_type))

        for barline in source_measure.findall("barline"):
            drum_measure.append(copy.deepcopy(barline))

        drum_part.append(drum_measure)

    root.append(drum_part)
    ET.indent(root, space="  ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(args.output, encoding="UTF-8", xml_declaration=True)


if __name__ == "__main__":
    main()
