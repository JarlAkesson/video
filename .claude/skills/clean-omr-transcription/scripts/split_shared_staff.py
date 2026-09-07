#!/usr/bin/env python3
"""Split a piano-vocal staff that carries melody AND accompaniment together.

SMOM book 6 is engraved on two staves, not three: the vocal line shares the
treble staff with the right-hand accompaniment (verses set between the staves),
so there is no melody staff to crop and Audiveris' voice numbering does not
track the melody -- in song 1 voice 1 filled only 9 of 17 bars.

The melody is the TOP line of that staff throughout this engraving, so it is
recovered as a skyline: at every onset, the highest sounding pitch. Everything
the skyline does not claim becomes accompaniment, and is merged with the bass
staff for chord naming.

Durations are NEVER rewritten -- a skyline note keeps the length the OMR gave
it. Where consecutive melody notes leave a hole in the bar, the bar is LEFT
SHORT and reported. Do not reach for --pad-holes to tidy it: filling holes with
rests makes every bar sum to its meter, so verify_score.py reports "0 problems"
while notes and dots are missing. That is exactly how book 6 song 1 shipped
with four dropped dots and two missing notes behind a clean verification. A
short bar is a visible defect; a padded one is an invisible one.

Run reconcile_repeats.py on the output BEFORE measuring anything against the
scan. These songs state their material three or four times and the OMR damages
each copy differently, so a correct reading of a repeated bar is usually
already in the file.

Outputs
-------
  <out>_melody_raw.musicxml   one monophonic part, the skyline
  <out>_accomp.musicxml       melody part + accompaniment part (for chords)
  stdout / --json             per-bar coverage report
"""
import argparse
import collections
import copy
import json
import sys

from music21 import chord, converter, layout, meter, note, stream


def skyline(part):
    """{measure_number: [(offset, pitch, quarterLength)]} highest note per onset."""
    out = {}
    for m in part.getElementsByClass(stream.Measure):
        ev = collections.defaultdict(list)
        for n in m.recurse().notes:
            off = round(float(n.offset), 4)
            if isinstance(n, chord.Chord):
                top = max(n.pitches, key=lambda p: p.midi)
                ev[off].append((top.midi, top, float(n.quarterLength), n))
            else:
                ev[off].append((n.pitch.midi, n.pitch, float(n.quarterLength), n))
        picks = []
        for off in sorted(ev):
            _, p, ql, src = max(ev[off], key=lambda t: t[0])
            picks.append((off, p, ql, src))
        out[m.number] = picks
    return out


def build(src, out_base, melody_staff=0, report=None, keep_melody=False,
          pad_holes=False):
    sc = converter.parse(src)
    parts = list(sc.parts)
    if not parts:
        sys.exit('no parts in %s' % src)
    treble = parts[melody_staff]
    sky = skyline(treble)

    mel = stream.Part(id='Melody')
    mel.partName = 'Melody'
    rows = []

    for m in treble.getElementsByClass(stream.Measure):
        bar = float(m.barDuration.quarterLength)
        nm = stream.Measure(number=m.number)
        for el in m.getElementsByClass((meter.TimeSignature,)):
            nm.insert(0, el)
        if m.number == treble.getElementsByClass(stream.Measure)[0].number:
            ks = m.keySignature or treble.keySignature
            if ks is not None:
                nm.insert(0, ks)
            cl = m.clef
            if cl is not None:
                nm.insert(0, cl)

        picks = sky.get(m.number, [])
        cursor, holes = 0.0, []
        for (off, p, ql, _src) in picks:
            if off > cursor + 1e-6:
                gap = round(off - cursor, 4)
                if pad_holes:
                    nm.insert(cursor, note.Rest(quarterLength=gap))
                holes.append((cursor, gap))
            elif off < cursor - 1e-6:
                continue          # overlapping skyline note: keep the earlier one
            n = note.Note(p)
            n.quarterLength = ql
            nm.insert(off, n)
            cursor = round(off + ql, 4)
        if cursor < bar - 1e-6:
            gap = round(bar - cursor, 4)
            if pad_holes:
                nm.insert(cursor, note.Rest(quarterLength=gap))
            holes.append((cursor, gap))

        filled = sum(float(x.quarterLength) for x in nm.notes)
        rows.append({
            'measure': m.number,
            'bar_beats': bar,
            'melody_onsets': len(picks),
            'melody_filled': round(filled, 3),
            'hole_total': round(sum(g for _, g in holes), 3),
            'padded': pad_holes,
            'holes': [{'at': o, 'len': g} for o, g in holes],
            'overlong': filled > bar + 1e-6,
        })
        mel.append(nm)

    mscore = stream.Score()
    mscore.insert(0, mel)
    mscore.write('musicxml', out_base + '_melody_raw.musicxml')

    # accompaniment score: melody as reference part + everything else
    ascore = stream.Score()
    ascore.insert(0, mel)
    for i, p in enumerate(parts):
        if i == melody_staff:
            # Harmonic reduction, not a transcription: at every onset, stack the
            # non-melody pitches that are SOUNDING there (including ones held
            # from earlier) and give the stack a duration reaching the next
            # onset. The OMR's overlapping/overlong durations otherwise leave
            # measures that do not sum to their meter, which slides the chord
            # reader's beat grid and lands every symbol a bar early.
            rem = stream.Part(id='AccompRH')
            rem.partName = 'AccompRH'
            first = True
            for m in p.getElementsByClass(stream.Measure):
                bar = float(m.barDuration.quarterLength)
                nm = stream.Measure(number=m.number)
                if first:
                    ts = m.timeSignature or p.recurse().getElementsByClass(meter.TimeSignature).first()
                    if ts is not None:
                        nm.insert(0, meter.TimeSignature(ts.ratioString))
                    first = False
                # For CHORD NAMING the melody is not a foreign part: it shares
                # this staff with the right hand and usually doubles a chord
                # tone. Subtracting it strips the very thirds the reader needs,
                # which silently suppresses the dominants -- and then the tonic
                # bars after them look like "no change" and vanish too.
                claimed = set() if keep_melody else {
                    (round(o, 4), pp.midi) for (o, pp, _q, _s) in sky.get(m.number, [])}
                spans = []
                for n in m.recurse().notes:
                    off = round(float(n.offset), 4)
                    ql = float(n.quarterLength)
                    ps = n.pitches if isinstance(n, chord.Chord) else (n.pitch,)
                    for x in ps:
                        if (off, x.midi) not in claimed:
                            spans.append((off, min(off + ql, bar), x))
                onsets = sorted({o for o, _e, _p in spans if o < bar - 1e-6})
                cursor = 0.0
                for k, o in enumerate(onsets):
                    end = onsets[k + 1] if k + 1 < len(onsets) else bar
                    ql = round(end - o, 4)
                    if ql <= 0:
                        continue
                    if o > cursor + 1e-6:
                        nm.insert(cursor, note.Rest(quarterLength=round(o - cursor, 4)))
                    sounding = sorted({x.midi: x for st, en, x in spans
                                       if st <= o + 1e-6 < en}.values(),
                                      key=lambda x: x.midi)
                    if sounding:
                        c = chord.Chord(list(sounding))
                        c.quarterLength = ql
                        nm.insert(o, c)
                    else:
                        nm.insert(o, note.Rest(quarterLength=ql))
                    cursor = round(o + ql, 4)
                if cursor < bar - 1e-6:
                    nm.insert(cursor, note.Rest(quarterLength=round(bar - cursor, 4)))
                rem.append(nm)
            ascore.insert(0, rem)
        else:
            ascore.insert(0, p)
    ascore.write('musicxml', out_base + '_accomp.musicxml')

    bad = [r for r in rows if r['hole_total'] > 0 or r['overlong']]
    print('%s: %d bars, %d need eyes' % (src.split('/')[-1], len(rows), len(bad)))
    for r in rows:
        flag = ''
        if r['overlong']:
            flag = '  <-- OVERLONG'
        elif r['hole_total'] > 0:
            flag = '  <-- SHORT by %.2f' % r['hole_total']
        print('  m%-3s bar=%-4s onsets=%-2d melody=%-5s%s'
              % (r['measure'], r['bar_beats'], r['melody_onsets'],
                 r['melody_filled'], flag))
    if report:
        json.dump({'source': src, 'bars': rows}, open(report, 'w'), indent=1)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source')
    ap.add_argument('--out-base', required=True)
    ap.add_argument('--melody-staff', type=int, default=0,
                    help='index of the part holding the shared staff (default 0)')
    ap.add_argument('--report')
    ap.add_argument('--pad-holes', action='store_true',
                    help='fill holes with rests -- HIDES the defect from every '
                         'structural check; only for a score already reconciled')
    ap.add_argument('--keep-melody', action='store_true',
                    help='do not subtract the melody from the accompaniment '
                         'reduction (right for chord naming on a shared staff)')
    a = ap.parse_args()
    build(a.source, a.out_base, a.melody_staff, a.report, a.keep_melody,
          a.pad_holes)


if __name__ == '__main__':
    main()
