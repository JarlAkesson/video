#!/usr/bin/env python3
"""Judge the bass line a music_analysis.json implies. Prints only what is wrong.

Chords get chosen one bar at a time, so the bass they add up to never gets
looked at. A harmonisation can be note-perfect bar by bar and still leap
aimlessly between roots: note-fit ranks chords, it does not rank readings.

Checks:

  5th/8ve  Parallels against the melody, measured AT the harmony change: last
           melody note under one chord vs first under the next. Both voices
           must move the same way. Fifths are a fault anywhere. Octaves only
           count where an inversion is involved and no rest separates them --
           against a root-position chord an octave just means the melody is on
           the root, which is what melodies do, most of all at a V-I cadence.

  inv      An inversion is licensed when it joins stepwise bass motion holding
           one direction. It fails on a held bass (not motion) or an
           oscillation, bass leaving and returning to one note (I-V6-I, A-G#-A),
           where root position gives the stronger fourth-leap between roots.
           One held bass is always legal and needs no other justification: the
           cadential six-four, I64 over degree 5 resolving to V before the bass
           drops to 1. Other pedals stay a fault -- use them sparingly.
           Where NEITHER side steps, contour says nothing -- root motion by
           thirds or fourths is just root motion -- and the case is "n/a".

  land     A directional chain should arrive at a root-position chord. Only the
           chain's END is tested; inversions inside it are what it is made of.

  deg6     IV6 puts degree 6 in the bass, giving 1-6-5 into a cadence. ii6 puts
           degree 4 there for the stronger 1-4-5, and lets the melody's degree 4
           sound as a 3rd instead of doubling a root.

Usage: bass_line.py FILES [--all] [--show] [--json]
"""

import argparse
import glob
import json
import os
import sys

import music21 as m21

STRONG = {'4/4': [0.0, 2.0], '3/4': [0.0, 2.0], '2/4': [0.0, 1.0],
          '6/8': [0.0, 1.5], '3/8': [0.0], '2/2': [0.0, 2.0]}
PERFECT = (0, 7)


def parse_key(text):
    p = text.replace('-flat', '-').replace('-sharp', '#').split()
    return m21.key.Key(p[0], p[1] if len(p) > 1 else 'major')


def rn(symbol, key):
    try:
        return m21.roman.RomanNumeral(symbol, key)
    except Exception:
        return None


def signed_step(a, b):
    """Smallest signed semitone motion a->b (-6..+6); bass notes carry no octave."""
    d = (m21.pitch.Pitch(b).pitchClass - m21.pitch.Pitch(a).pitchClass) % 12
    return d - 12 if d > 6 else d


def chain_end(bass, i):
    """Last index of the directional chain bass[i] sits in (leaps included)."""
    d = signed_step(bass[i - 1], bass[i]) if i > 0 else 0
    if d == 0 and i + 1 < len(bass):
        d = signed_step(bass[i], bass[i + 1])
    if d == 0:
        return i
    j = i
    while j + 1 < len(bass):
        dn = signed_step(bass[j], bass[j + 1])
        if dn == 0 or (dn > 0) != (d > 0):
            break
        j += 1
    return j


def cadential_64(chords, bass, tonic, i):
    """Is chords[i] a cadential six-four -- I64 over a held degree-5 bass into V?

    The one pedal that is always idiomatic: the bass takes scale degree 5 and
    holds it while I64 resolves to V, then drops to 1. Spell it I64 (or Cad64);
    V64 is a different chord, with degree 2 in the bass.
    """
    if i + 1 >= len(chords):
        return False
    c, nx = chords[i], chords[i + 1]
    if c.inversion() != 2 or nx.inversion() != 0 or bass[i] != bass[i + 1]:
        return False
    def deg(name):
        return (m21.pitch.Pitch(name).pitchClass - tonic) % 12
    return deg(bass[i]) == 7 and deg(c.root().name) == 0 and deg(nx.root().name) == 7


def inversion_ok(bass, is_inv, i, cad=frozenset()):
    """True / False / None (not assessed)."""
    if i in cad:
        return True                                  # cadential six-four
    if i == 0 or i + 1 >= len(bass):
        return False
    d1 = signed_step(bass[i - 1], bass[i])
    d2 = signed_step(bass[i], bass[i + 1])
    if d1 == 0 or d2 == 0:
        return False                                 # held bass is not motion
    if abs(d1) not in (1, 2) and abs(d2) not in (1, 2):
        return None                                  # not stepwise
    if bass[i - 1] == bass[i + 1]:
        return False                                 # oscillation
    return (d1 > 0) == (d2 > 0)


def find_score(json_path):
    d = os.path.dirname(json_path) or '.'
    slug = os.path.basename(json_path).replace('_music_analysis.json', '')
    for g in sorted(glob.glob(os.path.join(d, '*.musicxml'))):
        if os.path.basename(g).startswith(slug):
            return g
    return None


def melody_spans(score_path, entries):
    """(first, last) melody note under each harmony, plus the note+rest stream.

    Bars are keyed by position, which is what the analyses are written against.
    """
    ms = list(m21.converter.parse(score_path).parts[0].getElementsByClass('Measure'))
    if ms and ms[0].number == 0:
        ms = ms[1:]                                  # anacrusis carries no chord
    seq = [(i, float(e.offset) + 1, e) for i, mm in enumerate(ms, 1)
           for e in sorted(mm.notesAndRests, key=lambda z: float(z.offset))]
    notes = [(i, b, e.pitches[0]) for i, b, e in seq if not e.isRest]
    spans = []
    for k, e in enumerate(entries):
        lo = (e['measure'], e['beat'])
        hi = ((entries[k + 1]['measure'], entries[k + 1]['beat'])
              if k + 1 < len(entries) else (10 ** 6, 0))
        u = [n for n in notes if lo <= (n[0], n[1]) < hi]
        spans.append((u[0], u[-1]) if u else (None, None))
    return spans, seq


def parallels(score_path, entries, bass, is_inv):
    if not score_path:
        return []
    spans, seq = melody_spans(score_path, entries)
    out = []
    for k in range(len(entries) - 1):
        last, nxt = spans[k][1], spans[k + 1][0]
        if last is None or nxt is None or bass[k] == bass[k + 1]:
            continue
        i1 = (last[2].pitchClass - m21.pitch.Pitch(bass[k]).pitchClass) % 12
        i2 = (nxt[2].pitchClass - m21.pitch.Pitch(bass[k + 1]).pitchClass) % 12
        if i1 != i2 or i1 not in PERFECT:
            continue
        if (signed_step(bass[k], bass[k + 1]) > 0) != (nxt[2].midi - last[2].midi > 0) \
                or nxt[2].midi == last[2].midi:
            continue                                 # oblique or contrary motion
        if i1 == 0:
            if not (is_inv[k] or is_inv[k + 1]):
                continue                             # melody is just on the root
            if any(e.isRest for i, b, e in seq
                   if (last[0], last[1]) < (i, b) < (nxt[0], nxt[1])):
                continue                             # broken octaves
        out.append(f"{'8ve' if i1 == 0 else '5th'} m{last[0]}b{last[1]:g}>m{nxt[0]}b{nxt[1]:g} "
                   f"{bass[k]}/{last[2].name}>{bass[k+1]}/{nxt[2].name}")
    return out


def analyse(path):
    score = json.load(open(path, encoding='utf-8'))['score']
    key = parse_key(score['key'])
    tonic = m21.pitch.Pitch(key.tonic.name).pitchClass

    entries = [e for e in sorted(score['harmony'], key=lambda h: (h['measure'], h['beat']))
               if rn(e['chord_guess'], key) is not None]
    chords = [rn(e['chord_guess'], key) for e in entries]
    bass = [c.bass().name for c in chords]
    is_inv = [c.inversion() != 0 for c in chords]
    inv = [i for i, v in enumerate(is_inv) if v]

    cad = {i for i in inv if cadential_64(chords, bass, tonic, i)}
    ok, bad, na, land, deg6 = [], [], [], [], []
    for i in inv:
        tag = f"m{entries[i]['measure']}{entries[i]['chord_guess']}"
        r = inversion_ok(bass, is_inv, i, cad)
        (na if r is None else ok if r else bad).append(tag)
        j = chain_end(bass, i)
        if is_inv[j]:
            land.append(f"{tag}>m{entries[j]['measure']}{entries[j]['chord_guess']}")
        if ((m21.pitch.Pitch(bass[i]).pitchClass - tonic) % 12 == 9
                and chords[i].inversion() == 1 and chords[i].scaleDegree == 4):
            deg6.append(tag)

    pen = (m21.pitch.Pitch(bass[-2]).pitchClass - tonic) % 12 if len(bass) >= 2 else None
    return {
        'file': os.path.basename(path).replace('_music_analysis.json', ''),
        'chords': len(bass), 'bass': bass, 'inversions': len(inv), 'inv_ok': ok,
        'inv_bad': bad, 'inv_na': na, 'chain_not_landed': land, 'deg6': deg6,
        'parallels': parallels(find_score(path), entries, bass, is_inv),
        'cadence_ok': pen == 7,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+')
    ap.add_argument('--all', action='store_true', help='list clean songs too')
    ap.add_argument('--show', action='store_true', help='print the bass line')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    paths = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or [f])
    out = []
    for p in paths:
        try:
            out.append(analyse(p))
        except Exception as e:
            print(f'{os.path.basename(p)}: {e}', file=sys.stderr)

    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    faults = 0
    for r in out:
        bits = (r['parallels'] + [f'inv {x}' for x in r['inv_bad']]
                + [f'unlanded {x}' for x in r['chain_not_landed']]
                + [f'deg6 {x}' for x in r['deg6']])
        if bits:
            faults += 1
        elif not args.all and not args.show:
            continue
        note = '; '.join(bits) or 'ok'
        if r['inv_na']:
            note += '  n/a ' + ','.join(r['inv_na'])
        print(f"{r['file'][7:][:26]:26s} {note}")
        if args.show:
            print('   ' + ' '.join(r['bass']))
    quiet = [r['file'][7:] for r in out if not r['cadence_ok']]
    print(f"{len(out)} songs, {faults} flagged"
          + (f"; no dominant before the final chord: {', '.join(quiet)}" if quiet else ''))
    return 1 if faults else 0


if __name__ == '__main__':
    raise SystemExit(main())
