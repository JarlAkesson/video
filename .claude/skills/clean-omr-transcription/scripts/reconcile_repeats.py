#!/usr/bin/env python3
"""Reconcile bars that repeat, against the best-read copy already in the file.

Run this BEFORE measuring anything against the scan. These songbooks are
strophic: the same phrase is stated three or four times and the OMR damages
each copy independently, so the correct reading of a damaged bar is usually
already in the file. On book 6 song 1 this recovers four of the eight bars the
user had to fix by hand, and correctly declines the other four.

Two repairs, in this order:

  MODEL   A complete bar whose pitches CONTAIN the short bar's pitches as a
          subsequence and which has MORE notes -- it supplies the note the OMR
          dropped, and its rhythm with it. (m7 = 66,66,64 against m3 =
          66,66,64,64.)

  DOT     No model, but restoring one dot makes the bar sum AND produces a
          rhythm that a complete bar elsewhere already uses. (m9 short by 0.25;
          dotting its first note yields 0.75,0.25,0.5,0.5, which is m1.)

Why a model must have MORE notes: bars 11 and 12 of song 1 share the pitches
71,69,67, but bar 12 is a different bar (0.5,0.5,1) and bar 11's true reading
needs a fourth note that the OMR never saw. Copying an equal-length "twin"
would have silently written the wrong rhythm -- worse than leaving it short.
Equal-length matches are therefore refused, and only a support-backed dot may
change a rhythm without adding a note.

Completeness is measured over NOTES ONLY, because music21 re-pads incomplete
measures with rests when it writes, so a written file cannot be asked whether a
bar was short. That also means a bar whose trailing rest is genuine (a phrase
end) reads as short here; it will simply find no model and be reported.

--apply performs the repairs and prints each one. Exit status is non-zero while
unreconciled bars remain, so this gates a loop.
"""
import argparse
import json
import sys

# A model repair rewrites pitches as well as rhythm, so it needs enough shared
# material to be evidence. Two notes is the floor; one-note bars matched
# everything.
MIN_NOTES_FOR_MODEL = 2

from music21 import converter, note, stream


def extends(small, big):
    """big is small plus exactly one note at the end.

    A looser subsequence test is unsafe: a one-note bar is a subsequence of
    almost anything, which matched song 1's genuine phrase-end bars (a quarter
    plus a real rest) against unrelated four-note bars and would have rewritten
    them. Requiring a prefix, and exactly one missing note, is the case this
    repair is actually evidence for -- the OMR dropped the last note of a
    repeated figure.
    """
    return len(big) == len(small) + 1 and tuple(big[:len(small)]) == tuple(small)


def rows_of(part):
    rows = []
    for m in part.getElementsByClass(stream.Measure):
        ns = [n for n in m.recurse().notes]
        filled = sum(float(n.quarterLength) for n in ns)
        bar = float(m.barDuration.quarterLength)
        rows.append({
            'measure': m.number, 'bar': bar,
            'pitches': tuple(n.pitch.midi for n in ns),
            'rhythm': tuple(float(n.quarterLength) for n in ns),
            'notes_fill': round(filled, 4),
            'complete': abs(filled - bar) < 1e-6,
            'obj': m,
        })
    return rows


def dot_candidates(row, support_rhythms, min_support):
    """Rhythms reachable by dotting exactly one note, that others already use."""
    short_by = round(row['bar'] - row['notes_fill'], 4)
    out = []
    for i, q in enumerate(row['rhythm']):
        if abs(q * 0.5 - short_by) > 1e-6:
            continue
        cand = list(row['rhythm'])
        cand[i] = q * 1.5
        n = support_rhythms.get(tuple(cand), 0)
        if n >= min_support:
            out.append((tuple(cand), i, n))
    return sorted(out, key=lambda t: -t[2])


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('-o', '--output')
    ap.add_argument('--rhythm-support', type=int, default=1,
                    help='complete bars that must already use a rhythm before a '
                         'dot repair may produce it (default 1)')
    ap.add_argument('--keep-pickup', dest='skip_pickup', action='store_false',
                    help='treat the first measure as a normal bar')
    ap.add_argument('--json')
    a = ap.parse_args()

    sc = converter.parse(a.score)
    part = sc.parts[0] if sc.parts else sc
    rows = rows_of(part)
    if rows and a.skip_pickup:
        # The pickup is short by design; it is not a damaged bar.
        rows = rows[1:]
    complete = [r for r in rows if r['complete']]
    support = {}
    for r in complete:
        support[r['rhythm']] = support.get(r['rhythm'], 0) + 1

    report, applied, left = [], 0, 0
    for r in rows:
        if r['complete'] or not r['pitches']:
            continue
        if len(r['pitches']) < MIN_NOTES_FOR_MODEL:
            models = []
        else:
            models = [c for c in complete
                      if extends(r['pitches'], c['pitches'])]
        shapes = {(c['pitches'], c['rhythm']) for c in models}
        entry = {'measure': r['measure'], 'short_by': round(r['bar'] - r['notes_fill'], 4)}

        if len(shapes) == 1:
            model = models[0]
            entry.update(kind='model', model_bar=model['measure'],
                         rhythm=list(model['rhythm']))
            print('m%-3d MODEL  from m%-3d  %s -> %s'
                  % (r['measure'], model['measure'],
                     list(r['rhythm']), list(model['rhythm'])))
            if a.apply:
                for el in list(r['obj'].recurse().notesAndRests):
                    el.activeSite.remove(el)
                for pmidi, ql in zip(model['pitches'], model['rhythm']):
                    n = note.Note(midi=pmidi)
                    n.quarterLength = ql
                    r['obj'].append(n)
                applied += 1
        elif len(shapes) > 1:
            entry.update(kind='ambiguous',
                         models=[m['measure'] for m in models])
            print('m%-3d AMBIGUOUS  models %s disagree -- settle against the scan'
                  % (r['measure'], [m['measure'] for m in models]))
            left += 1
        else:
            cands = dot_candidates(r, support, a.rhythm_support)
            if len(cands) == 1:
                cand, idx, n = cands[0]
                entry.update(kind='dot', note_index=idx, rhythm=list(cand),
                             support=n)
                print('m%-3d DOT    note %d  %s -> %s  (%d bar(s) use it)'
                      % (r['measure'], idx, list(r['rhythm']), list(cand), n))
                if a.apply:
                    ns = [x for x in r['obj'].recurse().notes]
                    for x, ql in zip(ns, cand):
                        x.quarterLength = ql
                    for x in list(r['obj'].recurse().getElementsByClass(note.Rest)):
                        x.activeSite.remove(x)
                    applied += 1
            else:
                entry.update(kind='unresolved',
                             dot_options=[list(c[0]) for c in cands])
                print('m%-3d NEEDS THE SCAN  short by %.4g, %s'
                      % (r['measure'], r['bar'] - r['notes_fill'],
                         'no model, no supported dot' if not cands
                         else '%d dot repairs equally supported' % len(cands)))
                left += 1
        report.append(entry)

    if a.apply and applied:
        out = a.output or a.score
        sc.write('musicxml', out)
        print('wrote %s' % out)
    if a.json:
        json.dump(report, open(a.json, 'w'), indent=1)
    print('%d short bar(s): %d repaired, %d for the scan'
          % (len(report), applied, left))
    sys.exit(1 if left else 0)


if __name__ == '__main__':
    main()
