#!/usr/bin/python3
"""Realize a lead sheet's chord symbols as block chords on a second staff.

Input : a single-part melody + chord-symbol score (.mscz or .musicxml).
Output: <stem>_chords.mscz  (top staff "Grand Piano" = melody, bottom staff
        "Melody"/Voice = block chords, chord symbols on both) and <stem>.mid.

Voicing (the user's convention, verified against every chord of SMOM 5 song 1):
  bass  = bass note (slash bass) or root, placed in octave 2
  upper = each pitch class of the triad/7th placed in octave 4 (C4-B4), sorted
          ascending
  each chord is ONE sustained block from its symbol to the next symbol or the
  end of the bar; a bar with no symbol becomes a whole-bar rest.

Needs /usr/bin/python3 (has music21) and MuseScore 4.
"""
import argparse, copy, os, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"

# (quarter-lengths) -> (note type, dotted)
TYPES = {0.5: ("eighth", 0), 1.0: ("quarter", 0), 1.5: ("quarter", 1),
         2.0: ("half", 0), 3.0: ("half", 1), 4.0: ("whole", 0), 6.0: ("whole", 1)}

PART_LIST = {  # copied from the MuseScore export of the user's song-1 score
    "P1": """<score-part id="P1"><part-name>Grand Piano</part-name>
      <part-abbreviation>Pno.</part-abbreviation>
      <score-instrument id="P1-I1"><instrument-name>Grand Piano</instrument-name>
        <instrument-sound>keyboard.piano.grand</instrument-sound></score-instrument>
      <midi-device id="P1-I1" port="1"></midi-device>
      <midi-instrument id="P1-I1"><midi-channel>3</midi-channel><midi-program>1</midi-program>
        <volume>78.7402</volume><pan>0</pan></midi-instrument></score-part>""",
    "P2": """<score-part id="P2"><part-name>Melody</part-name>
      <part-abbreviation>Mel.</part-abbreviation>
      <score-instrument id="P2-I1"><instrument-name>Voice</instrument-name>
        <instrument-sound>voice.vocals</instrument-sound></score-instrument>
      <midi-device id="P2-I1" port="1"></midi-device>
      <midi-instrument id="P2-I1"><midi-channel>1</midi-channel><midi-program>54</midi-program>
        <volume>78.7402</volume><pan>0</pan></midi-instrument></score-part>""",
}


def voice(cs):
    from music21 import pitch
    root = cs.root()
    bass = cs.bass() or root
    b = pitch.Pitch(bass.name); b.octave = 2
    ups = {}
    for p in cs.pitches:
        q = pitch.Pitch(p.name); q.octave = 4
        ups[q.midi] = q
    return [b] + [ups[k] for k in sorted(ups)]


def mscore(*args):
    r = subprocess.run([MSCORE, *args], capture_output=True, text=True)
    return r


def build(src_musicxml, out_musicxml):
    from music21 import converter, harmony
    tree = ET.parse(src_musicxml); root = tree.getroot()
    parts = root.findall("part")
    if len(parts) != 1:
        sys.exit(f"source must be a single-part lead sheet, found {len(parts)} parts")
    p1 = parts[0]
    attrs = p1.find("measure/attributes")
    div = int(attrs.findtext("divisions"))
    beats = int(attrs.findtext("time/beats")); beat_type = int(attrs.findtext("time/beat-type"))
    bar_q = beats * 4 / beat_type

    plist = root.find("part-list")
    for sp in list(plist): plist.remove(sp)
    for k in ("P1", "P2"): plist.append(ET.fromstring(PART_LIST[k]))
    p2 = ET.SubElement(root, "part", id="P2")

    score = converter.parse(src_musicxml)
    syms = {m.number: sorted(m.flatten().getElementsByClass(harmony.ChordSymbol),
                             key=lambda c: c.offset)
            for m in score.parts[0].getElementsByClass("Measure")}

    def add_type(nt, q):
        if q not in TYPES:
            sys.exit(f"unsupported chord length {q} quarters (add it to TYPES or split it)")
        typ, dots = TYPES[q]
        ET.SubElement(nt, "duration").text = str(int(q * div))
        ET.SubElement(nt, "voice").text = "1"
        ET.SubElement(nt, "type").text = typ
        for _ in range(dots): ET.SubElement(nt, "dot")

    for meas in p1.findall("measure"):
        n = int(meas.get("number"))
        m2 = ET.SubElement(p2, "measure", number=str(n))
        if meas.find("attributes") is not None and n == int(p1.find("measure").get("number")):
            m2.append(copy.deepcopy(meas.find("attributes")))
        hs = meas.findall("harmony"); cs_list = syms.get(n, [])
        if len(hs) != len(cs_list):
            sys.exit(f"bar {n}: {len(hs)} <harmony> vs {len(cs_list)} ChordSymbols")
        if not cs_list:                                    # no symbol -> rest bar
            r = ET.SubElement(m2, "note"); ET.SubElement(r, "rest", measure="yes")
            ET.SubElement(r, "duration").text = str(int(bar_q * div)); ET.SubElement(r, "voice").text = "1"
            continue
        first = cs_list[0].offset
        if first:                                          # rest before first symbol
            r = ET.SubElement(m2, "note"); ET.SubElement(r, "rest"); add_type(r, first)
        for i, cs in enumerate(cs_list):
            end = cs_list[i + 1].offset if i + 1 < len(cs_list) else bar_q
            m2.append(copy.deepcopy(hs[i]))
            for k, p in enumerate(voice(cs)):
                nt = ET.SubElement(m2, "note")
                if k: ET.SubElement(nt, "chord")
                pt = ET.SubElement(nt, "pitch")
                ET.SubElement(pt, "step").text = p.step
                if p.accidental and p.accidental.alter:
                    ET.SubElement(pt, "alter").text = str(int(p.accidental.alter))
                ET.SubElement(pt, "octave").text = str(p.octave)
                add_type(nt, end - cs.offset)
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    with open(out_musicxml, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE score-partwise PUBLIC '
                '"-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                '"http://www.musicxml.org/dtds/partwise.dtd">\n' + body)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="lead sheet .mscz or .musicxml (single part, chord symbols)")
    ap.add_argument("--outdir", help="default: next to the source")
    ap.add_argument("--force", action="store_true", help="overwrite existing outputs")
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    outdir = os.path.abspath(a.outdir or os.path.dirname(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    out_mscz = os.path.join(outdir, stem + "_chords.mscz"); out_mid = os.path.join(outdir, stem + ".mid")
    for f in (out_mscz, out_mid):
        if os.path.exists(f) and not a.force:
            sys.exit(f"{f} exists; refusing to overwrite delivered files (use --force)")
    with tempfile.TemporaryDirectory() as t:
        xml_in = src
        if src.endswith((".mscz", ".mscx")):               # mscz is the authority for chords
            xml_in = os.path.join(t, "lead.musicxml"); mscore("-o", xml_in, src)
        xml_out = os.path.join(t, "chords.musicxml")
        build(xml_in, xml_out)
        tmp_mscz = os.path.join(t, "chords.mscz"); mscore("-o", tmp_mscz, xml_out)
        tmp_mid = os.path.join(t, "chords.mid"); mscore("-o", tmp_mid, tmp_mscz)
        for f in (tmp_mscz, tmp_mid):
            if not os.path.exists(f): sys.exit("MuseScore conversion failed: " + f)
        os.replace(tmp_mscz, out_mscz); os.replace(tmp_mid, out_mid)
    print(out_mscz); print(out_mid)


if __name__ == "__main__":
    main()
