#!/usr/bin/env python3
"""Name the chord in every bar, then drop repeats -- instead of letting the
previous chord decide whether the next one is looked for at all.

Also enforces the two rules that `analyse()` leaves to the caller and that a
caller reliably forgets:

  --min-fit   OFF by default, and it should usually stay off. Fit looks like a
              usable filter and is not: checked against a hand-corrected song 1,
              the chords the user KEPT scored 8.44-13.8 and the ones deleted
              scored 7.57-12.8. A cut at 10 would have deleted three correct
              chords (the bar-1 and bar-13 dominants, the bar-10 Em) while
              keeping four wrong ones. Fit flags a bar for review; it cannot
              decide it. What actually separated right from wrong was phrase
              structure and harmonic function, neither of which the scorer sees.

  --restate-on-repeat
              Re-state the harmony where the melody repeats an earlier bar. A
              running diff suppresses the returning tonic at the head of a new
              phrase: song 1's bars 5-8 restate bars 1-4, and the whole phrase
              came out bare because its first chord equalled the last one
              emitted four bars earlier. Chord changes follow phrase structure,
              not a running diff.

`accompaniment_chords.analyse()` threads the previously emitted chord into
`segment()` AND skips any window whose root matches it. On a song that sits on
its tonic between cadences those two rules compound: once D is emitted, the
segmenter is biased toward hearing D again, the D windows are suppressed as
"no change", and the dominant between them is never surfaced. Book 6 song 1
lost every chord in bars 3-6 that way, including an A dominant and the tonic
returns around it.

Reading each bar with prev=None and de-duplicating afterwards gets the same
"report only changes" output without letting suppression hide a real change.
Scoring, spelling, dominant folding and the .mscz writer are the tool's own.
"""
import argparse
import json
import sys

sys.path.insert(0, '.claude/skills/transcribe_harmony/scripts')
import accompaniment_chords as A          # noqa: E402
import music21 as m21                     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('score')
    ap.add_argument('--key', required=True)
    ap.add_argument('--melody-ref')
    ap.add_argument('--json')
    ap.add_argument('--mscz')
    ap.add_argument('--pickup', action='store_true')
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--min-fit', type=float, default=0.0,
                    help='drop chords below this fit. Default 0 (keep all): fit '
                         'does NOT separate right from wrong -- see the module '
                         'docstring. Use it to triage, not to decide.')
    ap.add_argument('--flag-fit', type=float, default=10.0,
                    help='mark chords below this as provisional (default 10)')
    ap.add_argument('--pickup-chord', action='store_true',
                    help='allow a chord symbol on the pickup bar (suppressed by '
                         'default: the harmony starts at the first full bar)')
    ap.add_argument('--restate-on-repeat', action='store_true',
                    help='re-state the chord when the melody bar repeats an '
                         'earlier bar, even if the harmony has not moved')
    ap.add_argument('--keep-inversions', action='store_true',
                    help='treat a changed bass as a change worth reporting')
    a = ap.parse_args()

    sc = m21.converter.parse(a.score)
    parts = list(sc.parts)
    mel = next((p for p in parts if p.partName == 'Melody'), parts[0])
    acc = [p for p in parts if p is not mel]
    key = m21.key.Key(a.key.split()[0], a.key.split()[1] if len(a.key.split()) > 1 else 'major')
    ts = sc.recurse().getElementsByClass(m21.meter.TimeSignature).first() \
        or m21.meter.TimeSignature('4/4')
    beat = ts.beatDuration.quarterLength

    melbars = {m.number for m in mel.getElementsByClass(m21.stream.Measure)}
    per = {}
    for p in acc:
        for m in p.getElementsByClass(m21.stream.Measure):
            per.setdefault(m.number, []).append(m)

    # Melody fingerprint per bar, so a repeated bar can force a restatement.
    # Prefer --melody-ref: repeats are only detectable on a RECONCILED melody,
    # and the melody carried inside the accompaniment score is the raw skyline.
    fp_part = mel
    if a.melody_ref:
        ref = m21.converter.parse(a.melody_ref)
        if ref.parts:
            fp_part = ref.parts[0]
    fingerprint, seen = {}, {}
    for m in fp_part.getElementsByClass(m21.stream.Measure):
        fingerprint[m.number] = tuple(n.pitch.midi for n in m.recurse().notes)

    rows, prev, dropped = [], None, []
    for num in sorted(per):
        if num not in melbars:
            continue
        ms = per[num]
        span = max(m.barDuration.quarterLength for m in ms)
        if not a.pickup_chord and num == min(melbars):
            first = mel.getElementsByClass(m21.stream.Measure).first()
            if first is not None and float(first.barDuration.quarterLength) > sum(
                    float(n.quarterLength) for n in first.recurse().notes) + 1e-6:
                continue
        fp = fingerprint.get(num)
        repeats = bool(a.restate_on_repeat and fp and fp in seen and seen[fp] != num)
        if fp and fp not in seen:
            seen[fp] = num
        first_in_bar = True
        for lo, root, qual, bs, sc_ in A.segment(ms, span, beat, key, None):
            root, qual = A.as_dominant(root, qual, key)
            ident = (root, qual, bs) if a.keep_inversions else (root, qual)
            if sc_ < a.min_fit:
                dropped.append((num, lo / beat + 1, A.spell(root, key) + qual, sc_))
                continue
            if prev is not None and ident == prev and not (repeats and first_in_bar):
                first_in_bar = False
                continue
            rows.append((num, lo / beat + 1, root, qual, bs, sc_))
            prev = ident
            first_in_bar = False

    for (bar, bt, root, qual, bs, fit) in rows:
        sym = A.spell(root, key) + qual
        bass = A.spell(bs, key) if bs is not None else None
        if bass and bass != A.spell(root, key):
            sym += '/' + bass
        warn = '   <-- provisional, check the bar' if fit < a.flag_fit else ''
        print('  m%-3s beat %-3s %-9s fit %s%s' % (bar, round(bt, 2), sym, round(fit, 2), warn))
    print('%d chord(s)' % len(rows))
    for (bar, bt, sym, fit) in dropped:
        print('  dropped m%-3s beat %-3s %-9s fit %s (below --min-fit %g)'
              % (bar, round(bt, 2), sym, round(fit, 2), a.min_fit))

    if a.json:
        json.dump({'key': a.key, 'meter': ts.ratioString,
                   'chords': [{'measure': b, 'beat': bt,
                               'symbol': A.spell(r, key) + q,
                               'bass': A.spell(bs, key) if bs is not None else None,
                               'fit': round(f, 2),
                               'provisional': f < a.flag_fit}
                              for (b, bt, r, q, bs, f) in rows]},
                  open(a.json, 'w'), indent=1)
        print('wrote', a.json)
    if a.mscz:
        n = A.write_mscz(a.mscz, rows, ts, a.pickup, a.replace)
        print('wrote %d chord(s) into %s' % (n, a.mscz))


if __name__ == '__main__':
    main()
