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

  --inversions solid
              Prefer the plain triad. A slash chord is kept only when the bass
              reading actually supports it: the bass part's measure must sum to
              the bar, and the named bass note must sound at the chord's onset.
              Book 6 song 2 named G/D from a bass bar holding a single 1-beat D
              in 2/4, and G/B from a bar whose bass summed to 4 beats in 2/4 --
              both were over-specified from junk, and a musician replaced both
              with plain triads while keeping the one inversion whose bass bar
              was complete. An inversion stripped by this test is RESTORED when
              it carries a stepwise bass line (see below), because voice leading
              is better evidence than one bar's bass reading.

  stepwise bass (always applied)
              A seventh in the bass must resolve down by step, and the chord
              that receives it is real even where the OMR read that bar badly.
              D/F# between A7/G and Em gives the bass G -> F# -> E; the slash
              is kept because of the line, not because of the bar.

  cadential 6-4 (always applied)
              A triad with its FIFTH in the bass, resolving to a chord rooted
              on that bass note WHERE THAT ROOT IS THE DOMINANT, is named for
              the bass: G/D before D7 in G major is the dominant arriving, so it
              is written D. The same G-over-D at a phrase end that goes to G is
              a tonic and stays G; C/G going to G is a subdominant and stays C.
              Literal bass spelling cannot tell these apart; the function of
              what follows can.

  --fill-beat-one
              Every bar gets a symbol on beat 1. A bar whose only chord sits on
              beat 2 leaves a reader with nothing to play at the downbeat and
              breaks the harmonic rhythm. Where beat 1 has no confident reading
              of its own, the following chord's root is stated plain (D before
              D7) and marked "editorial": it regularises the rhythm and is not
              claimed as a transcription of that beat.

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
    ap.add_argument('--inversions', choices=['solid', 'all', 'never'],
                    default='solid',
                    help="'solid' (default) keeps a slash chord only when the "
                         "bass bar is complete and the bass note sounds at the "
                         "onset; 'all' trusts every bass reading; 'never' emits "
                         "plain triads only")
    ap.add_argument('--no-fill-beat-one', dest='fill_beat_one',
                    action='store_false',
                    help='allow bars whose first symbol falls after beat 1')
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

    # ---- bass evidence, per bar ------------------------------------------
    bass_parts = [p for p in acc if p.partName != 'AccompRH']

    def bass_info(num, lo_beat):
        """(bass bar is complete, pitch classes sounding at this beat)."""
        total, sounding = 0.0, set()
        onset = (lo_beat - 1) * beat
        for bp in bass_parts:
            for m in bp.getElementsByClass(m21.stream.Measure):
                if m.number != num:
                    continue
                total += sum(float(x.quarterLength) for x in m.recurse().notesAndRests)
                for n in m.recurse().notes:
                    st = float(n.offset)
                    if st <= onset + 1e-6 < st + float(n.quarterLength):
                        sounding |= {x.pitchClass for x in n.pitches}
        span_ = max((float(m.barDuration.quarterLength)
                     for bp in bass_parts
                     for m in bp.getElementsByClass(m21.stream.Measure)
                     if m.number == num), default=0.0)
        return (span_ > 0 and abs(total - span_) < 1e-6), sounding

    # ---- cadential 6-4: a triad on its fifth, resolving to that bass ------
    # G/D before D7 is the dominant arriving, so it is named D. The same
    # G-over-D that goes to G is a phrase-ending tonic and stays G. Only what
    # FOLLOWS separates them, so this must run before inversions are stripped.
    cadential = set()
    for i, (bar, bt, root, qual, bs, fit) in enumerate(rows):
        if bs is None or (root + 7) % 12 != bs % 12:
            continue
        # It must resolve to the DOMINANT to be cadential. Requiring only
        # "next chord is rooted on the bass" also matches C/G -> G, which is a
        # subdominant going home to the tonic, and renaming that to G loses the
        # C entirely.
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        dominant_pc = key.pitchFromDegree(5).pitchClass
        if (nxt and nxt[2] % 12 == bs % 12 and bs % 12 == dominant_pc):
            rows[i] = (bar, bt, bs % 12, '', None, fit)
            cadential.add((bar, bt))

    # ---- inversion policy -------------------------------------------------
    orig_bass = {i: r[4] for i, r in enumerate(rows)}
    for i, (bar, bt, root, qual, bs, fit) in enumerate(rows):
        if bs is None or (bar, bt) in cadential:
            continue
        if a.inversions == 'never':
            rows[i] = (bar, bt, root, qual, None, fit)
        elif a.inversions == 'solid':
            complete, sounding = bass_info(bar, bt)
            if not (complete and (bs % 12) in sounding):
                rows[i] = (bar, bt, root, qual, None, fit)

    # ---- restore an inversion that carries a STEPWISE BASS LINE -----------
    # Bass evidence per bar is the wrong instrument for this. A seventh sitting
    # in the bass is obliged to resolve down by step, and the inversion that
    # receives it is real even when that bar's bass reading is junk: across
    # song 2's m9-m11 the bass runs G (the 7th of A7) -> F# -> E into Em, so
    # D/F# belongs there however badly the OMR read bar 10. Restore a stripped
    # bass when it forms three steps in a consistent direction with the chords
    # either side.
    def eff(i):
        r = rows[i]
        return (r[4] if r[4] is not None else r[2]) % 12

    stepwise = set()
    if a.inversions == 'solid':
        for i, (bar, bt, root, qual, bs, fit) in enumerate(rows):
            cand = orig_bass.get(i)
            if bs is not None or cand is None or i == 0 or i + 1 >= len(rows):
                continue
            prev_b, next_b, c = eff(i - 1), eff(i + 1), cand % 12
            down = ((prev_b - c) % 12 in (1, 2)) and ((c - next_b) % 12 in (1, 2))
            up = ((c - prev_b) % 12 in (1, 2)) and ((next_b - c) % 12 in (1, 2))
            if down or up:
                rows[i] = (bar, bt, root, qual, cand, fit)
                stepwise.add((bar, bt))

    # ---- beat 1 of every bar carries a symbol ------------------------------
    editorial = set()
    if a.fill_beat_one:
        by_bar = {}
        for r in rows:
            by_bar.setdefault(r[0], []).append(r)
        for bar, rs in by_bar.items():
            rs.sort(key=lambda r: r[1])
            if rs[0][1] <= 1 + 1e-6:
                continue
            _, _, root, qual, _, fit = rs[0]
            plain = qual[:-1] if qual.endswith('7') else qual   # D7 -> D
            rows.append((bar, 1.0, root, plain, None, fit))
            editorial.add((bar, 1.0))
    rows.sort(key=lambda r: (r[0], r[1]))

    for (bar, bt, root, qual, bs, fit) in rows:
        sym = A.spell(root, key) + qual
        bass = A.spell(bs, key) if bs is not None else None
        if bass and bass != A.spell(root, key):
            sym += '/' + bass
        warn = '   <-- provisional, check the bar' if fit < a.flag_fit else ''
        if (bar, bt) in editorial:
            warn = '   <-- editorial: beat-1 fill, not a reading of this beat'
        elif (bar, bt) in cadential:
            warn = '   <-- cadential 6-4 named for its bass'
        elif (bar, bt) in stepwise:
            warn = '   <-- inversion kept: stepwise bass line'
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
                               'provisional': f < a.flag_fit,
                               'editorial': (b, bt) in editorial,
                               'cadential_64': (b, bt) in cadential,
                               'stepwise_bass': (b, bt) in stepwise}
                              for (b, bt, r, q, bs, f) in rows]},
                  open(a.json, 'w'), indent=1)
        print('wrote', a.json)
    if a.mscz:
        n = A.write_mscz(a.mscz, rows, ts, a.pickup, a.replace)
        print('wrote %d chord(s) into %s' % (n, a.mscz))


if __name__ == '__main__':
    main()
