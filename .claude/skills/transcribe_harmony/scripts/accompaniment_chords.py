#!/usr/bin/env python3
"""Name the chords an accompaniment actually plays, rather than inferring them
from the melody.

Given a score whose parts include an accompaniment (a piano grand staff, say),
this reports the harmony that is really sounding, bar by bar, with inversions.
It is the counterpart to inferring harmony from a melody alone: where the melody
leaves a bar ambiguous -- degree 3 and 5 fit both I and vi -- the accompaniment
settles it, and where the two disagree, one of them is wrong and the bar is
worth opening.

Four things it has to get right, each learned from getting it wrong on Alice
Tegner's "Sjung med oss, mamma!":

  * CHANGES LAND ON BEATS. Sampling a bar in fixed halves puts a boundary at
    beat 2.5 of a 3/4 bar, so every window straddles the real chord change: it
    pools the tail of one chord with the head of the next, names something that
    is neither, and reports it at a position that cannot be right. Here beats
    are the only candidate cut points, and whole segmentations of the bar are
    scored against each other, so a change is always reported where one can
    actually occur.

  * A WINDOW IS POOLED, NOT SAMPLED. These accompaniments are broken chords, so
    any single beat holds two notes of a triad and naming it is a guess. Each
    segment is named from every pitch sounding inside it, weighted by duration.

  * NO METRIC PREFERENCE. Every beat is an equally allowable change point. A
    harmonisation CHOSEN for a melody should land its changes on strong beats,
    but this tool READS a harmonisation that already exists: biasing it toward
    beat 3 made it misreport a real beat-2 change in Tegner's own accompaniment.

  * A HELD BASS IS A PEDAL, NOT A ROOT. A sustained bass under moving harmony
    drags the naming toward whatever makes it a chord tone -- a G7 over a tonic
    pedal came out contrived. A pitch class held in the lowest voice for a whole
    bar is down-weighted and reported as the bass, not fed to the root search.

  * THE KEY IS PART OF THE SCORING, not a check applied afterwards. Two chords
    can cover a window equally well and differ only in which note they omit:
    A7 and C#m7b5 share three tones. What separates them is that one is the
    key's secondary dominant and the other belongs to no related key.

Every chord is reported with a FIT score. Low fit means the window did not
spell a chord cleanly -- open those bars against the source rather than
trusting them, and note that a wrong-but-related chord (the relative minor,
say) still fits the melody, so `--check` will not catch it for you.

Examples
--------
  accompaniment_chords.py song.musicxml --key "G major"
  accompaniment_chords.py song.musicxml --key "D minor" --melody-part 0 --check
  accompaniment_chords.py song.musicxml --key "C major" --json out.json \
      --mscz melody.mscz            # write the chords into a MuseScore file
"""

import argparse
import json
import os
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from itertools import combinations

import music21 as m21

# A children's songbook of this period uses triads, the dominant seventh and the
# occasional diminished or half-diminished chord. Major- and minor-seventh
# readings are almost always a passing tone pooled into the window, so they are
# not offered; add them here if the repertoire genuinely uses them.
QUALITIES = {
    '':      (0, 4, 7),
    'm':     (0, 3, 7),
    'dim':   (0, 3, 6),
    '7':     (0, 4, 7, 10),
    'dim7':  (0, 3, 6, 9),
    'm7b5':  (0, 3, 6, 10),
}

SPLIT_PENALTY = 0.5      # cost of each extra chord within a bar
PEDAL_WEIGHT = 0.35      # how much a held bass still counts toward naming
FIFTHS = {'F': -1, 'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5}


# ---------------------------------------------------------------- part choice

def pick_melody(score, ref=None, index=None):
    """(melody part, [accompaniment parts])."""
    if index is not None:
        return score.parts[index], [p for i, p in enumerate(score.parts) if i != index]
    if ref:
        want = {n.pitch.midi for n in m21.converter.parse(ref).parts[0].flatten().notes
                if not n.isChord}
        best, bi = -1.0, 0
        for i, p in enumerate(score.parts):
            got = {n.pitch.midi for n in p.flatten().notes if not n.isChord}
            if not got:
                continue
            j = len(got & want) / max(len(got | want), 1)
            if j > best:
                best, bi = j, i
        return score.parts[bi], [p for i, p in enumerate(score.parts) if i != bi]
    # otherwise: the most monophonic part, tie-broken by sitting highest
    def rank(p):
        notes = list(p.flatten().notes)
        if not notes:
            return (1.0, 0.0)
        chords = sum(1 for n in notes if n.isChord) / len(notes)
        mean = sum(x.ps for n in notes for x in n.pitches) / sum(len(n.pitches) for n in notes)
        return (chords, -mean)
    bi = min(range(len(score.parts)), key=lambda i: rank(score.parts[i]))
    return score.parts[bi], [p for i, p in enumerate(score.parts) if i != bi]


# ------------------------------------------------------------------- scoring

def pool(measures, lo, hi):
    """(duration-weighted pitch classes, functional bass) inside [lo, hi).

    The bass is the lowest note sounding AT the window's start, not the lowest
    found anywhere in it. An alternating left hand -- C, then G below it, over
    and over -- is a root-position chord with a figured bass, not a second
    inversion, and taking the absolute lowest note called every one of those an
    inversion. A bass passing down through a weak beat did the same.
    """
    weight, events = {}, []
    for m in measures:
        flat = m.flatten()
        for x in flat.notes:
            s0 = flat.elementOffset(x)
            e0 = s0 + x.duration.quarterLength
            ov = min(e0, hi) - max(s0, lo)
            if ov <= 1e-9:
                continue
            for p in x.pitches:
                weight[p.pitchClass] = weight.get(p.pitchClass, 0) + ov
                events.append((s0, e0, p.pitchClass, p.ps))
    if not events:
        return weight, None
    # The bass at each moment is the lowest note SOUNDING then -- not the lowest
    # note that happens to begin then, which counts a high entry as the bass
    # moving. An inversion means the bass SITS on a non-root tone; a left hand
    # rocking between two chord tones is figuration, so a bass that moves inside
    # the window yields no inversion and the root is used instead.
    moments = sorted({max(s0, lo) for s0, _e, _pc, _ps in events})
    floor = []
    for t in moments:
        low = min((ps, pc) for s0, e0, pc, ps in events if s0 <= t + 1e-9 < e0)
        floor.append(low)
    stable = len({pc for _ps, pc in floor}) == 1
    return weight, (floor[0][1] if stable else None)


def pedal_pc(measures, span):
    """The pitch class held in the lowest voice for the whole bar, if any."""
    low = {}
    for m in measures:
        flat = m.flatten()
        for x in flat.notes:
            s0 = flat.elementOffset(x)
            for t in (s0, s0 + x.duration.quarterLength - 1e-6):
                if 0 <= t < span:
                    k = round(t, 3)
                    for p in x.pitches:
                        if k not in low or p.ps < low[k][1]:
                            low[k] = (p.pitchClass, p.ps)
    if len(low) < 3:
        return None
    pcs = {v[0] for v in low.values()}
    return next(iter(pcs)) if len(pcs) == 1 else None


def key_bias(root, qual, key):
    """Plausibility of this chord in the key, independent of the notes."""
    if key is None:
        return 0.0
    degrees = {key.pitchFromDegree(i).pitchClass: i for i in range(1, 8)}
    if root not in degrees:
        return -1.2
    want = ({1: '', 2: 'm', 3: 'm', 4: '', 5: '', 6: 'm', 7: 'dim'} if key.mode == 'major'
            else {1: 'm', 2: 'dim', 3: '', 4: 'm', 5: '', 6: '', 7: ''})
    if qual == want.get(degrees[root]):
        return 1.5
    if qual in ('', '7'):
        return 0.8               # a secondary dominant on a diatonic degree
    return 0.0


def score_chord(weight, bass, prev_root=None, key=None):
    """(root pc, quality, bass pc, fit) for the best-fitting chord."""
    best, total = None, (sum(weight.values()) or 1)
    for root in range(12):
        for qual, ivs in QUALITIES.items():
            tones = {(root + i) % 12 for i in ivs}
            inside = sum(w for pc, w in weight.items() if pc in tones) / total
            missing = len([t for t in tones if weight.get(t, 0) == 0])
            sc = inside * 10 - missing * 1.5
            if bass is not None and bass in tones:
                sc += 1.0
            if bass is not None and bass == root:
                sc += 1.0
            if len(ivs) == 4:
                # only discount a seventh when its seventh is not really
                # sounding; where all four tones are present it is earned
                if weight.get((root + ivs[-1]) % 12, 0) / total < 0.05:
                    sc -= 1.2
            if prev_root is not None and root == prev_root:
                sc += 0.4
            sc += key_bias(root, qual, key)
            if best is None or sc > best[-1]:
                best = (root, qual, bass, round(sc, 2))
    return best


def segment(measures, span, beat, key, prev_root=None, max_spans=3):
    """[(offset, root, quality, bass, fit)] for the best beat-aligned split."""
    nbeats = max(1, int(round(span / beat)))
    cuts = list(range(1, nbeats))
    ped = pedal_pc(measures, span)
    best = None
    for k in range(0, min(max_spans, nbeats)):
        for combo in combinations(cuts, k):
            bounds = [0.0] + [c * beat for c in combo] + [span]
            segs, tot, prev = [], 0.0, prev_root
            for lo, hi in zip(bounds, bounds[1:]):
                w, b = pool(measures, lo, hi)
                if not w:
                    segs.append((lo, None))
                    continue
                if ped is not None and len(w) > 2:
                    w = dict(w)
                    w[ped] *= PEDAL_WEIGHT
                root, qual, bs, sc = score_chord(w, b if ped is None else None, prev, key)
                segs.append((lo, (root, qual, ped if ped is not None else bs, sc)))
                tot += sc * (hi - lo) / span
                prev = root
            tot -= SPLIT_PENALTY * k
            if best is None or tot > best[0]:
                best = (tot, segs)
    return [(lo,) + got for lo, got in best[1] if got is not None]


def analyse(melody, accomp, ts, key, bar_offset=0):
    """[(bar, beat, root, quality, bass, fit)] for the whole piece."""
    beat = ts.beatDuration.quarterLength
    melbars = {m.number for m in melody.getElementsByClass(m21.stream.Measure)}
    per = {}
    for p in accomp:
        for m in p.getElementsByClass(m21.stream.Measure):
            per.setdefault(m.number, []).append(m)
    out, prev = [], None
    for num in sorted(per):
        if num + bar_offset not in melbars:
            continue
        ms = per[num]
        span = max(m.barDuration.quarterLength for m in ms)
        for lo, root, qual, bs, sc in segment(ms, span, beat, key,
                                              prev[0] if prev else None):
            if prev and root == prev[0]:
                # same root: the harmony has not moved. A seventh that is simply
                # not restruck in this window does not turn G7 back into G, so
                # the richer identity is kept and nothing is reported.
                continue
            out.append((num + bar_offset, lo / beat + 1, root, qual, bs, sc))
            prev = (root, qual)
    return out


# ------------------------------------------------------------------- reports

def offgrid_bars(accomp, ts):
    """Bars whose accompaniment does not lie on the beat grid, or does not fill.

    A chord change can only be reported on a beat, so a bar whose accompaniment
    the engine read as triplets against a duple metre -- or whose voices do not
    add up -- will have its change placed at the nearest beat below where it
    really falls. That is a defect in the input, not in the reading, but it is
    invisible in the output unless it is said.
    """
    grid = ts.beatDuration.quarterLength / 4
    bad = {}
    for p in accomp:
        for m in p.getElementsByClass(m21.stream.Measure):
            flat = m.flatten()
            span = m.barDuration.quarterLength
            reasons = []
            for x in flat.notes:
                off = flat.elementOffset(x)
                if abs(off / grid - round(off / grid)) > 1e-6:
                    reasons.append('off-grid onset')
                    break
            # coverage, not the sum of durations: an accompaniment staff is
            # polyphonic, so summing every note double-counts the ones sounding
            # together and reports a full bar as overlong
            iv = sorted((flat.elementOffset(x),
                         flat.elementOffset(x) + x.duration.quarterLength)
                        for x in flat.notesAndRests)
            covered, end = 0.0, None
            for a, b in iv:
                if end is None or a > end:
                    covered += b - a
                    end = b
                elif b > end:
                    covered += b - end
                    end = b
            if iv and covered < span - 1e-6:
                reasons.append(f'covers {float(covered):g} of {float(span):g} beats')
            if reasons:
                bad.setdefault(m.number, set()).update(reasons)
    return bad


def check(melody, rows, ts, key):
    """Report chords whose melody notes are stranded, or whose root is foreign."""
    beat = ts.beatDuration.quarterLength
    strong = ([0.0, 1.5] if ts.ratioString == '6/8'
              else [0.0, 2.0] if ts.numerator in (3, 4) else [0.0, 1.0])
    spans = {}
    for bar, bt, root, qual, bs, sc in rows:
        spans.setdefault(bar, []).append((bt, root, qual))
    problems = []
    for m in melody.getElementsByClass(m21.stream.Measure):
        vs = list(m.getElementsByClass(m21.stream.Voice))
        src = vs[0] if vs else m
        ev = sorted(((src.elementOffset(x), x) for x in src.notes), key=lambda t: t[0])
        if not ev or m.number not in spans:
            continue
        here = sorted(spans[m.number])
        for off, note in [(o, x) for o, x in ev if o in strong]:
            cur = here[0]
            for c in here:
                if off >= (c[0] - 1) * beat - 1e-9:
                    cur = c
            tones = {(cur[1] + i) % 12 for i in QUALITIES[cur[2]]}
            if note.pitch.pitchClass in tones:
                continue
            i = [k for k, (o, _) in enumerate(ev) if o == off][0]
            if i + 1 < len(ev):
                nx = ev[i + 1][1]
                if abs(nx.pitch.midi - note.pitch.midi) <= 2 and nx.pitch.pitchClass in tones:
                    continue
            problems.append(f'm{m.number} {note.nameWithOctave}@beat'
                            f'{off / beat + 1:g} stranded under '
                            f'{m21.pitch.Pitch(cur[1]).name}{cur[2]}')
    diatonic = {key.pitchFromDegree(i).pitchClass for i in range(1, 8)}
    foreign = [f'm{b} {m21.pitch.Pitch(r).name}{q}'
               for b, _bt, r, q, _bs, _sc in rows if r not in diatonic]
    return problems, foreign


# --------------------------------------------------------- MuseScore writing

def tpc(pitch):
    alter = pitch.accidental.alter if pitch.accidental else 0
    return int(14 + FIFTHS[pitch.step] + 7 * alter)


def write_mscz(path, rows, ts, pickup=False, replace=False):
    """Insert the chords into a .mscz as <Harmony> elements. Edits in place.

    A score that already carries chord symbols will end up with two sets laid
    over each other, so existing ones are counted and reported; pass replace to
    clear them first. Replacing discards any chord symbol already in the file,
    including hand-made corrections, so it is never the default.
    """
    DIV = 480
    DUR = {'breve': 3840, 'whole': 1920, 'half': 960, 'quarter': 480,
           'eighth': 240, '16th': 120, '32nd': 60, '64th': 30}

    def ticks(el):
        dt = el.find('durationType')
        if dt is None:
            return 0
        if dt.text == 'measure':
            d = el.find('duration')
            return int(DIV * 4 * int(d.get('z')) / int(d.get('n'))) if d is not None else 0
        base = DUR.get(dt.text, 0)
        dots = el.find('dots')
        if dots is not None and dots.text:
            base = int(base * (2 - 2 ** -int(dots.text)))
        return base

    z = zipfile.ZipFile(path)
    inner = [x for x in z.namelist() if x.endswith('.mscx')][0]
    blobs = {x: z.read(x) for x in z.namelist()}
    z.close()
    tree = ET.fromstring(blobs[inner].decode('utf-8'))
    # two Staff elements exist: the part definition and the one carrying music
    staff = next(x for x in tree.findall('.//Staff') if x.find('Measure') is not None)
    measures = staff.findall('Measure')
    existing = 0
    for m in measures:
        v = m.find('voice')
        if v is None:
            continue
        for h in v.findall('Harmony'):
            existing += 1
            if replace:
                v.remove(h)
    if existing and not replace:
        print(f'  note: {existing} chord symbol(s) already in {os.path.basename(path)}; '
              f'the new ones are added alongside. Pass --replace to clear them first.',
              file=sys.stderr)
    beat_ql = ts.beatDuration.quarterLength
    placed = 0
    for bar, bt, root, qual, bs, _sc in sorted(rows):
        idx = bar if pickup else bar - 1
        if not (0 <= idx < len(measures)):
            continue
        voice = measures[idx].find('voice')
        kids = list(voice)
        target = int(round((bt - 1) * beat_ql * DIV))
        pos, at = 0, None
        for i, el in enumerate(kids):
            if el.tag in ('Chord', 'Rest'):
                if pos >= target:
                    at = i
                    break
                pos += ticks(el)
        if at is None:
            continue
        h = ET.Element('Harmony')
        rp = m21.pitch.Pitch(root)
        ET.SubElement(h, 'root').text = str(tpc(rp))
        if qual:
            ET.SubElement(h, 'name').text = qual
        if bs is not None and bs != root:
            ET.SubElement(h, 'base').text = str(tpc(m21.pitch.Pitch(bs)))
        voice.insert(list(voice).index(kids[at]), h)
        placed += 1
    ET.indent(tree, space='  ')
    blobs[inner] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                    + ET.tostring(tree, encoding='unicode')).encode('utf-8')
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as out:
        for k, v in blobs.items():
            out.writestr(k, v)
    shutil.move(tmp, path)
    return placed


# ----------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score', help='MusicXML/MXL containing melody and accompaniment')
    ap.add_argument('--key', required=True, help='e.g. "G major", "D minor"')
    ap.add_argument('--meter', help='override, e.g. 6/8, when the export lost it')
    ap.add_argument('--melody-part', type=int, help='0-based index of the melody part')
    ap.add_argument('--melody-ref', help='score whose part 0 is the melody, matched by pitch')
    ap.add_argument('--bar-offset', type=int, default=0,
                    help='add to every bar number (when the export starts mid-piece)')
    ap.add_argument('--json', help='write the chords here')
    ap.add_argument('--mscz', help='insert the chords into this MuseScore file, in place')
    ap.add_argument('--replace', action='store_true',
                    help='clear chord symbols already in the .mscz before writing')
    ap.add_argument('--pickup', action='store_true',
                    help='the .mscz first measure is an upbeat (bar 0)')
    ap.add_argument('--restate', action='store_true',
                    help='name the chord again at every beat it is in force, '
                         'instead of only where it changes')
    ap.add_argument('--check', action='store_true',
                    help='also report stranded melody notes and chords foreign to the key')
    args = ap.parse_args()

    key = m21.key.Key(*args.key.split())
    score = m21.converter.parse(args.score)
    melody, accomp = pick_melody(score, args.melody_ref, args.melody_part)
    if not accomp:
        print('no accompaniment parts found', file=sys.stderr)
        return 2
    if args.meter:
        ts = m21.meter.TimeSignature(args.meter)
    else:
        found = list(score.recurse().getElementsByClass(m21.meter.TimeSignature))
        if not found:
            print('no time signature in the score; pass --meter', file=sys.stderr)
            return 2
        ts = found[0]

    rows = analyse(melody, accomp, ts, key, args.bar_offset)
    print(f'{os.path.basename(args.score)}: {args.key}, {ts.ratioString}, '
          f'{len(rows)} chord(s), melody part "{melody.id}"')
    for bar, bt, root, qual, bs, sc in rows:
        name = m21.pitch.Pitch(root).name + qual
        slash = f'/{m21.pitch.Pitch(bs).name}' if bs is not None and bs != root else ''
        mark = '   <-- weak, check the source' if sc < 8 else ''
        print(f'  m{bar:<3d} beat {bt:<4g} {name}{slash:<4s}  fit {sc}{mark}')

    rc = 0
    if args.check:
        for bar, why in sorted(offgrid_bars(accomp, ts).items()):
            print(f'  SUSPECT m{bar}: {"; ".join(sorted(why))} -- the change '
                  f'position here may be wrong')
        stranded, foreign = check(melody, rows, ts, key)
        for s in stranded:
            print(f'  STRANDED {s}')
        for f in foreign:
            print(f'  FOREIGN  {f} is not diatonic here (may be real, check it)')
        rc = 1 if stranded else 0

    if args.json:
        json.dump([{'measure': b, 'beat': bt, 'symbol': m21.pitch.Pitch(r).name + q,
                    'root_pc': r, 'quality': q,
                    'bass': m21.pitch.Pitch(bs).name if bs is not None else None,
                    'fit': sc} for b, bt, r, q, bs, sc in rows],
                  open(args.json, 'w'), ensure_ascii=False, indent=2)
        print(f'wrote {args.json}')
    if args.mscz:
        n = write_mscz(args.mscz, rows, ts, args.pickup, args.replace)
        print(f'wrote {n} chord(s) into {args.mscz}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
