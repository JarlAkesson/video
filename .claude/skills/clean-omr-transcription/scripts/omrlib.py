"""Shared helpers for the clean-omr-transcription skill.

Book-agnostic. Nothing here knows about a particular songbook, path or song
list; callers pass files and options in. The CLIs in this directory are thin
wrappers around these functions.

The rules implemented here are documented in ../SKILL.md. Where a function
encodes a decision that could reasonably have gone the other way, the docstring
says which way and why, so a future caller can tell when the default is wrong
for a new book rather than silently inheriting it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from fractions import Fraction

import music21 as m21
from music21 import instrument, layout, metadata, note, stream

EPS = 1e-6

# Every repair is logged rather than applied silently: an OMR pipeline that
# quietly rewrites rhythm is untrustworthy even when it is right.
FIXLOG: list[tuple] = []


def reset_log() -> None:
    FIXLOG.clear()


def log(scope: str, kind: str, a: float = 0.0, b: float = 0.0) -> None:
    FIXLOG.append((scope, kind, float(a), float(b)))


def log_summary() -> dict:
    out: dict = {}
    for _scope, kind, _a, _b in FIXLOG:
        out[kind] = out.get(kind, 0) + 1
    return out


# ---------------------------------------------------------------------------
# Duration vocabulary
# ---------------------------------------------------------------------------

def _values(triplets: bool) -> list[float]:
    """Nameable note values: plain and dotted powers of two, optionally thirds.

    Triplets are opt-in because mixing them with binary values puts
    1/24-quarter differences into circulation. That is harmless when durations
    are laid end to end (a monophonic line), and harmful when some later pass
    re-derives durations from absolute offsets, where the crumbs make bars land
    a hair over or under the meter. Callers that flatten polyphony should leave
    triplets off; melody-only callers should turn them on.
    """
    base = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    out = set()
    for b in base:
        out.add(b)
        out.add(b * 1.5)
        if triplets:
            out.add(b * 2.0 / 3.0)
    return sorted(out)


BINARY = _values(False)
WITH_TRIPLETS = _values(True)
# Plain values, no dots. Used for padding rests, which are not in the source at
# all and so should never introduce a dot of their own.
UNDOTTED = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]


def nearest(ql: float, allowed: list[float]) -> float:
    if ql <= 0:
        return allowed[0]
    return min(allowed, key=lambda a: (abs(a - ql), a))


def floor_value(ql: float, allowed: list[float]) -> float:
    """Largest nameable value not exceeding ql. Used when clipping, where
    rounding up would defeat the point and leave the bar overlong."""
    cand = [a for a in allowed if a <= ql + 1e-9]
    return cand[-1] if cand else allowed[0]


def decompose(total: float, allowed: list[float]) -> list[float]:
    """Split a span into nameable chunks, largest first.

    A remainder smaller than the shortest value is dropped rather than rounded
    up: overshooting is what makes a padded bar longer than its meter.
    """
    out: list[float] = []
    rest = float(total)
    for _ in range(32):
        if rest <= 1e-6:
            break
        pick = None
        for a in reversed(allowed):
            if a <= rest + 1e-9:
                pick = a
                break
        if pick is None:
            break
        out.append(pick)
        rest -= pick
    return out or [nearest(total, allowed)]


def is_nameable(ql: float) -> bool:
    try:
        return m21.duration.Duration(quarterLength=ql).type not in (
            'complex', 'inexpressible', 'zero')
    except Exception:
        return False


def emit_span(container, offset, pitches, total, allowed,
              tie_in=False, tie_out=False):
    """Place a note/chord/rest of `total` length at `offset`, tying if split."""
    chunks = decompose(total, allowed)
    pos = offset
    for i, ch in enumerate(chunks):
        if pitches is None:
            el = note.Rest()
        elif len(pitches) > 1:
            el = m21.chord.Chord(list(pitches))
        else:
            el = note.Note(pitches[0])
        el.duration = m21.duration.Duration(quarterLength=ch)
        if pitches is not None:
            starts = (i == 0 and not tie_in)
            ends = (i == len(chunks) - 1 and not tie_out)
            if not starts and not ends:
                el.tie = m21.tie.Tie('continue')
            elif not starts:
                el.tie = m21.tie.Tie('stop')
            elif not ends:
                el.tie = m21.tie.Tie('start')
        container.insert(pos, el)
        pos += ch


def insert_rests(container, offset, gap, allowed):
    if gap > EPS:
        emit_span(container, offset, None, gap, allowed)


def span(container) -> float:
    """Sounding length, recomputed from elements every time.

    Stream.duration caches and the cache is not reliably invalidated by
    setElementOffset, so a measure could report its pre-repair length after the
    repair had already landed.
    """
    hi = 0.0
    for el in container.notesAndRests:
        hi = max(hi, float(el.offset) + float(el.duration.quarterLength))
    return hi


def has_tuplet(el) -> bool:
    return bool(getattr(el.duration, 'tuplets', ()))


# ---------------------------------------------------------------------------
# Quantisation
# ---------------------------------------------------------------------------

def tag_omr_tuplets(part):
    """Record which notes the OMR engine itself marked as tuplets.

    Must run BEFORE any duration is touched. The Tuplet object does not survive
    rescaling or rebuilding, but whether the ENGINE saw a bracket is the only
    real evidence a tuplet exists, so it is preserved as a flag instead.
    """
    n = 0
    # Rests included: a tuplet group routinely contains one (E-E-rest), and
    # skipping them splits the run so the group is no longer recognisable.
    for el in part.recurse().notesAndRests:
        flag = bool(getattr(el.duration, 'tuplets', ()))
        try:
            el.editorial['omr_tuplet'] = flag
        except Exception:
            pass
        n += flag
    return n


def is_tagged(el):
    try:
        return bool(el.editorial.get('omr_tuplet', False))
    except Exception:
        return False


def obvious_tuplet_groups(els, expected=None):
    """Runs that are unmistakably a tuplet. Returns [(start, end, [durations])].

    "Obvious" means the OMR engine tagged every element of the run AND their
    durations add up to a plain binary span while at least one of them is not
    itself binary. That is what a tuplet is: non-binary parts filling a binary
    whole.

    Members are NOT required to be equal or to be notes -- a group is often
    2/3 + 1/3, or ends on a rest -- so each keeps its own value; only the group
    as a whole has to make sense.

    The engine's tag alone is NOT enough. Audiveris also emits tuplets as a
    by-product of misreading a bar -- book 3's song 7 has three plain quarters
    tagged as a triplet -- so the bar must corroborate: with every duration
    snapped to the triplet-aware vocabulary, it has to already sum to its meter.
    A tuplet that only works if other notes are stretched to accommodate it is
    part of a misreading, not a tuplet.

    Everything weaker is left alone. Reaching for thirds whenever they make a bar
    add up sprinkles triplets through a piece that has none, which is worse than
    missing one: an invented tuplet looks deliberate.
    """
    if expected is not None:
        snapped_bar = sum(nearest(float(e.duration.quarterLength), WITH_TRIPLETS)
                          for e in els)
        if abs(snapped_bar - expected) > 0.01:
            return []
    groups = []
    i = 0
    while i < len(els):
        if not is_tagged(els[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(els) and is_tagged(els[j + 1]):
            j += 1
        run = els[i:j + 1]
        if len(run) >= 2:
            snapped = [nearest(float(e.duration.quarterLength), WITH_TRIPLETS) for e in run]
            total = sum(snapped)
            binary_total = abs(total - nearest(total, BINARY)) < 1e-6
            any_non_binary = any(not any(abs(a - d) < 1e-9 for a in BINARY) for d in snapped)
            if binary_total and any_non_binary:
                groups.append((i, j, snapped))
        i = j + 1
    return groups


def quantize_bar(durations, target, allowed, keep_mask=None):
    """Snap a bar's durations so they sum EXACTLY to target, or return None.

    Solved jointly rather than note by note. Rounding each note independently
    leaves a residual that then has to be taken out of some arbitrary note;
    scaling to the target first and then repairing the residual on whichever
    note is least sure of itself keeps the error where it belongs.

    keep_mask marks notes whose duration must not change -- used for notes that
    already carry a genuine tuplet from the OMR engine.
    """
    if not durations:
        return None
    total = sum(durations)
    if total <= EPS:
        return None
    keep_mask = keep_mask or [False] * len(durations)

    scale = target / total
    q = []
    for d, keep in zip(durations, keep_mask):
        q.append(d if keep else nearest(d * scale, allowed))

    def resid():
        return target - sum(q)

    for _ in range(64):
        r = resid()
        if abs(r) < 1e-6:
            return q
        best = None
        for i, (d, keep) in enumerate(zip(durations, keep_mask)):
            if keep:
                continue
            for alt in allowed:
                if abs(alt - q[i]) < 1e-9:
                    continue
                new_r = abs(r - (alt - q[i]))
                if new_r < abs(r) - 1e-9:
                    # prefer the smallest change to the least-certain note
                    cost = (new_r, abs(alt - d * scale))
                    if best is None or cost < best[0]:
                        best = (cost, i, alt)
        if best is None:
            return None
        q[best[1]] = best[2]
    return None


def relay_sequential(container, durations, allowed):
    """Rewrite a container's elements end to end with the given durations.

    Correct for a monophonic line, where elements are sequential by
    construction. Do not use on a polyphonic voice: collapsing its gaps shoves
    later notes past the barline.
    """
    els = sorted(container.notesAndRests, key=lambda n: (float(n.offset), -float(n.duration.quarterLength)))
    if len(els) != len(durations):
        return False
    payload = []
    for el, d in zip(els, durations):
        pitches = None if el.isRest else (list(el.pitches) if el.isChord else [el.pitch])
        payload.append((pitches, d, el))
        container.remove(el)
    cursor = 0.0
    for pitches, d, el in payload:
        if is_nameable(d):
            el.duration = m21.duration.Duration(quarterLength=d)
            container.insert(cursor, el)
        else:
            emit_span(container, cursor, pitches, d, allowed)
        cursor += d
    return True


def sanitize_offsets(container, allowed, grid=0.125):
    """Snap starts to a grid and durations to nameable values, without overlap.

    Offsets are preserved rather than collapsed, because a voice can carry real
    gaps. The cursor prevents overlap -- and when it pushes a start later the
    note is SHORTENED to match, otherwise every overlap spills past the barline
    and cascades through the rest of the part.
    """
    els = sorted(container.notesAndRests, key=lambda n: (float(n.offset), -float(n.duration.quarterLength)))
    if els:
        first = round(float(els[0].offset) / grid) * grid
        if first > 1e-9:
            insert_rests(container, 0.0, first, allowed)
        els = sorted(container.notesAndRests, key=lambda n: (float(n.offset), -float(n.duration.quarterLength)))
    cursor = 0.0
    for el in els:
        if has_tuplet(el):
            # A genuine tuplet already holds a valid value; re-snapping it to a
            # binary grid is exactly how triplets get flattened.
            start = max(float(el.offset), cursor)
            seg = float(el.duration.quarterLength)
            container.remove(el)
            container.insert(start, el)
            cursor = start + seg
            continue
        start = round(float(el.offset) / grid) * grid
        end = round((float(el.offset) + float(el.duration.quarterLength)) / grid) * grid
        if start < cursor - 1e-9:
            start = cursor
        if end <= start + 1e-9:
            end = start + allowed[0]
        seg = end - start
        pitches = None if el.isRest else (list(el.pitches) if el.isChord else [el.pitch])
        container.remove(el)
        if is_nameable(seg):
            el.duration = m21.duration.Duration(quarterLength=seg)
            container.insert(start, el)
        else:
            emit_span(container, start, pitches, seg, allowed)
        cursor = end


# ---------------------------------------------------------------------------
# Measure length
# ---------------------------------------------------------------------------

def _undot(ql: float) -> float:
    return float(Fraction(ql).limit_denominator(64) * Fraction(2, 3))


def _set_len(container, el, new_ql, allowed, mode='nearest'):
    new_ql = floor_value(new_ql, allowed) if mode == 'floor' else nearest(new_ql, allowed)
    if new_ql <= EPS:
        return None
    d = m21.duration.Duration(quarterLength=new_ql)
    if d.type not in ('complex', 'inexpressible'):
        el.duration = d
        return el
    start = el.offset
    pitches = None if el.isRest else (list(el.pitches) if el.isChord else [el.pitch])
    container.remove(el)
    emit_span(container, start, pitches, new_ql, allowed)
    return None


def rescale_degenerate(container, expected, scope=''):
    """Repair a bar whose durations collapsed to near zero during OMR.

    Audiveris occasionally emits intact pitches with nonsense durations
    (1/840, 1/3360 of a quarter) and offsets to match: the relative proportions
    survive, only the absolute scale is lost. Guarded hard -- fires only when
    the bar is more than eight times too short, which no real pickup is.
    """
    cur = span(container)
    if cur <= EPS or cur > expected / 8.0:
        return False
    scale = expected / cur
    for el in sorted(container.notesAndRests, key=lambda n: n.offset):
        # No need to carry the Tuplet object across: quarterLength is the
        # SOUNDING length, so music21 re-derives the tuplet from it (1/3 -> a
        # triplet). Re-attaching the old tuplet on top applies the ratio twice
        # and yields a duration the exporter cannot name.
        container.setElementOffset(el, float(el.offset) * scale)
        el.duration = m21.duration.Duration(
            quarterLength=max(float(el.duration.quarterLength) * scale, 0.125))
    log(scope, 'rescale-degenerate-bar', cur, expected)
    return True


def resolve_overlong(container, expected, allowed, scope='', allow_carry=True):
    """Bring a container down to at most `expected`, never deleting a note.

    Ordered rules; stop as soon as the bar fits. Returns notes carried past the
    barline for the caller to place in the next measure.
    """
    carried = []
    if expected is None:
        return carried

    for el in list(container.notesAndRests):
        if el.isRest and float(el.offset) >= expected - EPS:
            container.remove(el)
            log(scope, 'drop-rest-past-barline', el.offset, el.duration.quarterLength)

    for el in list(container.notesAndRests):
        if el.isRest and float(el.offset) + float(el.duration.quarterLength) > expected + EPS:
            new_ql = expected - float(el.offset)
            if new_ql > EPS:
                _set_len(container, el, new_ql, allowed, mode='floor')
                log(scope, 'truncate-rest-at-barline', el.offset, new_ql)
            else:
                container.remove(el)
    if span(container) <= expected + EPS:
        return carried

    if allow_carry:
        for el in list(container.notesAndRests):
            if (not el.isRest) and float(el.offset) >= expected - EPS:
                off = float(el.offset) - expected
                container.remove(el)
                carried.append((el, off))
                log(scope, 'carry-note-to-next-measure', off, el.duration.quarterLength)
    if span(container) <= expected + EPS:
        return carried

    excess = span(container) - expected
    for el in sorted(container.notesAndRests, key=lambda n: n.offset):
        cand = _undot(float(el.duration.quarterLength))
        if cand > EPS and abs(float(el.duration.quarterLength) - cand - excess) < 1e-6:
            shift = float(el.duration.quarterLength) - cand
            _set_len(container, el, cand, allowed)
            for later in sorted(container.notesAndRests, key=lambda n: n.offset):
                if float(later.offset) > float(el.offset) + EPS:
                    container.setElementOffset(later, float(later.offset) - shift)
            log(scope, 'undot', el.offset, cand)
            break
    if span(container) <= expected + EPS:
        return carried

    els = sorted(container.notesAndRests, key=lambda n: n.offset)
    for i in range(len(els)):
        run = els[i:]
        if len(run) < 2:
            break
        if len({round(float(e.duration.quarterLength), 6) for e in run}) != 1:
            continue
        run_start = float(run[0].offset)
        avail = expected - run_start
        if avail <= EPS:
            continue
        each = avail / len(run)
        if abs(each - float(run[0].duration.quarterLength)) < EPS:
            continue
        if not any(abs(a - each) < 1e-9 for a in allowed):
            continue
        off = run_start
        for e in run:
            container.setElementOffset(e, off)
            e.duration = m21.duration.Duration(quarterLength=each)
            off += each
        log(scope, 'compress-run-as-tuplet', run_start, each)
        break
    if span(container) <= expected + EPS:
        return carried

    for el in sorted(container.notesAndRests, key=lambda n: n.offset):
        end = float(el.offset) + float(el.duration.quarterLength)
        if end > expected + EPS and float(el.offset) < expected - EPS:
            _set_len(container, el, expected - float(el.offset), allowed, mode='floor')
            log(scope, 'clip-overhang', el.offset, expected - float(el.offset))
    if span(container) > expected + EPS:
        log(scope, 'UNRESOLVED', span(container), expected)
    return carried


def pad(container, expected, allowed):
    """Fill a short bar with rests.

    Padding rests are an editorial addition, not something the engraver wrote,
    so they are built from plain values: a 1.5-beat gap becomes a quarter plus
    an eighth rest rather than a dotted-quarter rest that looks deliberate. The
    exception is a completely empty bar, where a single full-measure rest is the
    conventional notation.
    """
    actual = span(container)
    if actual >= expected - EPS:
        return
    vocab = allowed if actual <= EPS else UNDOTTED
    insert_rests(container, actual, expected - actual, vocab)


def effective_time_signatures(part):
    """Carry the meter forward across measures, backfilling the first one found
    onto earlier bars that lack it (OMR often misses the opening header)."""
    measures = list(part.getElementsByClass('Measure'))
    first = next((mm.timeSignature for mm in measures if mm.timeSignature is not None), None)
    current = None
    out = []
    for mm in measures:
        if mm.timeSignature is not None:
            current = mm.timeSignature
        elif current is not None:
            mm.timeSignature = current
        elif first is not None:
            mm.timeSignature = first
            current = first
        out.append((mm, current.barDuration.quarterLength if current else None))
    return out


def normalize_part(part, allowed, monophonic=False, scope=''):
    """Make every measure exactly its meter, except a legal short pickup/final.

    A monophonic part has its durations snapped and re-laid end to end, which is
    what keeps tuplets intact; a short bar is then padded and a long one goes
    through the ordered overlong rules. Bars are never scaled to fit -- that
    invents dotted notes -- except where rescale_degenerate has just established
    that only the absolute scale was lost. Polyphonic parts keep their offsets
    and use the ordered rules throughout.
    """
    pairs = effective_time_signatures(part)
    n = len(pairs)
    has_pickup = False
    if pairs and pairs[0][1] is not None:
        c0 = list(pairs[0][0].voices) or [pairs[0][0]]
        has_pickup = max(span(c) for c in c0) < pairs[0][1] - EPS

    carry = []
    for i, (mm, expected) in enumerate(pairs):
        containers = list(mm.voices) or [mm]
        for el, off in carry:
            containers[0].insert(max(0.0, off), el)
        carry = []
        is_edge = (i == 0 or i == n - 1) and has_pickup
        for c in containers:
            if expected is None:
                continue
            degenerate = rescale_degenerate(c, expected, f'{scope} m{mm.number}')

            solved = False
            if monophonic and not is_edge:
                # Filler rests around the barline are not music. Clear them
                # first, or the bar looks longer than it is and every later
                # step tries to make room for junk.
                for el in list(c.notesAndRests):
                    if el.isRest and float(el.offset) >= expected - EPS:
                        c.remove(el)
                        log(f'{scope} m{mm.number}', 'drop-rest-past-barline',
                            el.offset, el.duration.quarterLength)
                for el in list(c.notesAndRests):
                    if el.isRest and float(el.offset) + float(el.duration.quarterLength) > expected + EPS:
                        new_ql = expected - float(el.offset)
                        if new_ql > EPS:
                            _set_len(c, el, new_ql, BINARY, mode='floor')
                            log(f'{scope} m{mm.number}', 'truncate-rest-at-barline',
                                el.offset, new_ql)
                        else:
                            c.remove(el)

                els = sorted(c.notesAndRests, key=lambda x: float(x.offset))
                durs = [float(e.duration.quarterLength) for e in els]
                keep = [False] * len(els)
                # Tuplet values are HELD where the engine marked a coherent
                # group, and are otherwise off the menu entirely: the binary
                # vocabulary means no triplet can be invented to make a bar add
                # up.
                for a, b, snapped in obvious_tuplet_groups(els, expected):
                    for k in range(a, b + 1):
                        durs[k] = snapped[k - a]
                        keep[k] = True

                if degenerate:
                    # Here the proportions survived and only the absolute scale
                    # was lost, so solving the bar by scaling is exactly right.
                    q = quantize_bar(durs, expected, BINARY, keep)
                else:
                    # Snap each value on its own -- NEVER scale the bar to fit
                    # its meter. Scaling rewrites rhythm that was read correctly:
                    # three quarters in a 4/4 bar become two dotted quarters
                    # instead of the bar simply being padded, and an overlong bar
                    # gets squashed instead of having its filler rest truncated.
                    # Invented dots are as wrong as invented tuplets.
                    q = []
                    for k, e in enumerate(els):
                        if keep[k]:
                            q.append(durs[k])
                            continue
                        # A REJECTED tuplet member must go back to its WRITTEN
                        # note value, not to whatever binary value is nearest its
                        # sounding length. A quarter inside a triplet sounds 2/3,
                        # and 2/3 snaps to a dotted eighth -- inventing a dot out
                        # of the engine's misreading. Dividing by the tuplet
                        # multiplier recovers the quarter it was drawn as.
                        tups = getattr(e.duration, 'tuplets', ())
                        d = durs[k]
                        if tups:
                            mult = float(tups[0].tupletMultiplier())
                            if mult > 0:
                                d = d / mult
                        q.append(nearest(d, BINARY))
                if q and relay_sequential(c, q, allowed):
                    if any(abs(x - y) > 1e-9 for x, y in zip(q, durs)):
                        log(f'{scope} m{mm.number}', 'snap-durations', sum(durs), expected)
                    solved = True

            if not solved:
                sanitize_offsets(c, allowed)
            vocab = BINARY if solved else allowed
            carry.extend(resolve_overlong(c, expected, vocab,
                                          f'{scope} m{mm.number}',
                                          allow_carry=(i < n - 1)))
            if not is_edge:
                pad(c, expected, vocab)

    if carry:
        last = list(part.getElementsByClass('Measure'))[-1]
        extra = stream.Measure(number=last.number + 1)
        expected = pairs[-1][1] if pairs else None
        for el, off in carry:
            extra.insert(max(0.0, off), el)
        if expected is not None:
            sanitize_offsets(extra, allowed)
            resolve_overlong(extra, expected, allowed, f'{scope} m{extra.number}', allow_carry=False)
            pad(extra, expected, allowed)
        part.append(extra)
        log(scope, 'carry-into-new-final-measure', len(carry), 0.0)
    return has_pickup


# ---------------------------------------------------------------------------
# Anacrusis and trailing rests
# ---------------------------------------------------------------------------

def last_music_measure(part):
    """Last measure containing a real note.

    The anacrusis arithmetic must be measured against the bar the music
    actually ends on. OMR often leaves one or more all-rest bars after the
    final chord, and using one of those as "the final measure" makes a genuine
    pickup fail its own corroboration test.
    """
    for mm in reversed(list(part.getElementsByClass('Measure'))):
        if any(not e.isRest for e in mm.recurse().notesAndRests):
            return mm
    return None


def _strippable_pickup(container):
    """Length measure 1 would have if its padding rests were removed, or None.

    None means "not a padded pickup": either there is nothing to strip, or a
    rest sits BETWEEN two notes, which makes the bar real music that happens to
    open the piece rather than a pickup with filler around it.
    """
    els = sorted(container.notesAndRests, key=lambda x: float(x.offset))
    notes = [e for e in els if not e.isRest]
    if not els or not notes:
        return None
    first = els.index(notes[0])
    last = len(els) - 1 - els[::-1].index(notes[-1])
    if any(e.isRest for e in els[first:last + 1]):
        return None
    if first == 0 and last == len(els) - 1:
        return None
    return sum(float(e.duration.quarterLength) for e in els[first:last + 1])


def _strip_padding(container):
    els = sorted(container.notesAndRests, key=lambda x: float(x.offset))
    notes = [e for e in els if not e.isRest]
    first = els.index(notes[0])
    last = len(els) - 1 - els[::-1].index(notes[-1])
    kept = els[first:last + 1]
    for e in els:
        if e not in kept:
            container.remove(e)
    cursor = 0.0
    for e in kept:
        container.remove(e)
        container.insert(cursor, e)
        cursor += float(e.duration.quarterLength)
    return cursor


def fix_anacrusis(part, allowed, final_hint=None, scope='', mode='auto'):
    """Turn a rest-padded opening bar into a real short pickup.

    An anacrusis is a SHORT bar immediately preceding bar 1: never a full bar
    with the pickup at the start and rests filling out to the barline, and never
    with a rest between the pickup and the downbeat it leads into.

    mode='auto' (default) gates on arithmetic: a real anacrusis plus the final
    measure completes exactly one bar. Without that test, "notes then rests" is
    indistinguishable from an ordinary opening bar closed by a rest, and
    "rests then notes" from an intro bar the composer wrote full.
    mode='always' converts on shape alone -- use when the house style is that
    every upbeat must be engraved as a short pickup bar, even where the source
    wrote it out in full. mode='never' disables the repair.

    `final_hint` is the final music-bearing measure's content length, measured
    before any padding was added.
    """
    measures = list(part.getElementsByClass('Measure'))
    if not measures:
        return None
    pairs = effective_time_signatures(part)
    expected = pairs[0][1] if pairs else None
    if expected is None:
        return None

    containers = list(measures[0].voices) or [measures[0]]
    cands = [_strippable_pickup(c) for c in containers]
    cands = [c for c in cands if c is not None]
    if not cands:
        return None
    candidate = max(cands)

    if mode == 'never':
        return None
    tail = final_hint if final_hint is not None else span(pairs[-1][0])
    if mode == 'auto' and abs((candidate + tail) - expected) > 0.01:
        # Shape alone cannot tell a padded pickup from a bar the composer really
        # wrote full (an opening gesture closed by a rest, or an intro bar of
        # rests before the vocal entry). Only the arithmetic distinguishes them,
        # so 'auto' declines rather than rewriting the engraver's barring.
        log(scope, 'anacrusis-rejected-by-arithmetic', candidate, tail)
        return None

    for c in containers:
        if _strippable_pickup(c) is not None:
            _strip_padding(c)
    # The closing bar of a piece with a pickup is legitimately short too; if
    # padding already filled it out, take that padding back off.
    for c in (list(measures[-1].voices) or [measures[-1]]):
        if _strippable_pickup(c) is not None:
            _strip_padding(c)
    log(scope, 'anacrusis-unpadded', candidate, expected)
    return candidate


def drop_trailing_rest_measures(score, min_run=2, scope=''):
    """Delete trailing measures holding nothing but rests.

    Applies only when more than one such bar follows the end of the song, and
    only where EVERY part agrees the bar is empty -- otherwise one silent staff
    would truncate music still sounding in another.
    """
    parts = list(score.parts) or [score]
    counts = []
    for p in parts:
        ms = list(p.getElementsByClass('Measure'))
        k = 0
        for mm in reversed(ms):
            if any(not e.isRest for e in mm.recurse().notesAndRests):
                break
            k += 1
        counts.append(k)
    run = min(counts) if counts else 0
    if run < min_run:
        return 0
    for p in parts:
        ms = list(p.getElementsByClass('Measure'))
        for mm in ms[len(ms) - run:]:
            p.remove(mm)
    log(scope, 'drop-trailing-rest-measures', run, 0.0)
    return run


# ---------------------------------------------------------------------------
# Tuplet brackets
# ---------------------------------------------------------------------------

def mark_tuplet_brackets(part):
    """Bracket each run of consecutive tuplet notes.

    music21 writes <time-modification> from the tuplet ratio on its own, but
    only emits the <tuplet> bracket when a tuplet carries type start/stop.
    Without this a triplet exports as three notes that merely happen to be
    thirds, with no bracket or number for the reader.
    """
    n = 0
    for mm in part.getElementsByClass('Measure'):
        for c in (list(mm.voices) or [mm]):
            els = sorted(c.notesAndRests, key=lambda x: float(x.offset))
            i = 0
            while i < len(els):
                if not has_tuplet(els[i]):
                    i += 1
                    continue
                j = i
                ratio = els[i].duration.tuplets[0].tupletMultiplier()
                while (j + 1 < len(els) and has_tuplet(els[j + 1])
                       and els[j + 1].duration.tuplets[0].tupletMultiplier() == ratio):
                    j += 1
                for k in range(i, j + 1):
                    tup = els[k].duration.tuplets[0]
                    tup.type = 'start' if k == i else ('stop' if k == j else None)
                n += 1
                i = j + 1
    return n


# ---------------------------------------------------------------------------
# Stripping
# ---------------------------------------------------------------------------

def strip_fermatas(part):
    for x in part.recurse().notes:
        x.expressions = [e for e in x.expressions if 'Fermata' not in type(e).__name__]


def strip_markings(part, dynamics=True, chord_symbols=True):
    classes = []
    if dynamics:
        classes.append('Dynamic')
    if chord_symbols:
        classes.append('ChordSymbol')
    if not classes:
        return
    for mm in part.getElementsByClass('Measure'):
        for el in list(mm.recurse().getElementsByClass(tuple(classes))):
            site = el.activeSite
            if site is not None:
                site.remove(el)


def unhide(part):
    for el in part.recurse().notesAndRests:
        try:
            el.style.hideObjectOnPrint = False
        except Exception:
            pass


def strip_instruments(part):
    for mm in part.getElementsByClass('Measure'):
        for inst in list(mm.getElementsByClass(instrument.Instrument)):
            mm.remove(inst)
    for inst in list(part.getElementsByClass(instrument.Instrument)):
        part.remove(inst)


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------

def remove_empty_voices(mm):
    for v in list(mm.voices):
        if not [e for e in v.recurse().notesAndRests if not e.isRest]:
            mm.remove(v)


def consolidate_voices(mm, max_voices=2):
    voices = list(mm.voices)
    if len(voices) <= max_voices:
        return
    voices.sort(key=lambda v: len([e for e in v.recurse().notesAndRests if not e.isRest]),
                reverse=True)
    keep, excess = voices[:max_voices], voices[max_voices:]

    def clashes(voice, a, b):
        for e in voice.notesAndRests:
            if e.isRest:
                continue
            s = float(e.offset)
            t = s + float(e.duration.quarterLength)
            if s < b - 1e-9 and t > a + 1e-9:
                return True
        return False

    for v in excess:
        for e in list(v.notesAndRests):
            if e.isRest:
                continue
            a = float(e.offset)
            b = a + float(e.duration.quarterLength)
            target = next((k for k in keep if not clashes(k, a, b)), keep[0])
            v.remove(e)
            target.insert(a, e)
        mm.remove(v)


def flatten_to_single_voice(mm, expected, allowed):
    """Collapse every voice of a measure into one, as chords with ties.

    A secondary voice that does not sound for its whole bar is stored by a
    notation program as notes plus INVISIBLE filler rests, which reappear on
    every round trip. One voice per staff is the only representation that
    survives. Pitches and onsets are preserved; independent stems are not.
    """
    segs = []
    for src in (list(mm.voices) or [mm]):
        for el in src.notesAndRests:
            if el.isRest:
                continue
            a = round(float(el.offset), 6)
            b = round(a + float(el.duration.quarterLength), 6)
            for p in (list(el.pitches) if el.isChord else [el.pitch]):
                segs.append((a, min(b, expected), p))
    segs = [s for s in segs if s[1] - s[0] > EPS]
    for v in list(mm.voices):
        mm.remove(v)
    for el in list(mm.notesAndRests):
        mm.remove(el)
    if not segs:
        insert_rests(mm, 0.0, expected, allowed)
        return

    bounds = sorted({0.0, float(expected)} | {a for a, _b, _p in segs} | {b for _a, b, _p in segs})
    bounds = [x for x in bounds if -EPS <= x <= expected + EPS]
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a <= EPS:
            continue
        sounding = [(s, e, p) for (s, e, p) in segs if s <= a + EPS and e >= b - EPS]
        if not sounding:
            insert_rests(mm, a, b - a, allowed)
            continue
        pitches = sorted({p.nameWithOctave: p for (_s, _e, p) in sounding}.values(),
                         key=lambda x: x.ps)
        starts = any(abs(s - a) < EPS for (s, _e, _p) in sounding)
        ends = any(abs(e - b) < EPS for (_s, e, _p) in sounding)
        emit_span(mm, a, list(pitches), b - a, allowed,
                  tie_in=not starts, tie_out=not ends)


def enforce_single_voice(part, allowed):
    for mm, expected in effective_time_signatures(part):
        if expected is None:
            continue
        flatten_to_single_voice(mm, expected, allowed)


# ---------------------------------------------------------------------------
# Melody
# ---------------------------------------------------------------------------

def pick_melody(score):
    """Return (melody_part, [accompaniment_parts]).

    Multiple parts named "Voice" mean spurious OMR splits of ONE vocal staff
    (stacked verse lyrics), not multiple melodies. The one with the most real
    notes is the tune -- the first one emitted can be nearly empty.
    """
    voice_parts, other = [], []
    for p in score.parts:
        (voice_parts if 'voice' in (p.partName or '').lower() else other).append(p)
    if voice_parts:
        voice_parts.sort(key=lambda p: len(list(p.recurse().notes)), reverse=True)
        return voice_parts[0], voice_parts[1:] + other
    if not other:
        return None, []
    return extract_top_line(other[0]), other[1:]


def extract_top_line(src_part):
    out = stream.Part()
    out.id = out.partName = 'Melody'
    for mm in src_part.getElementsByClass('Measure'):
        new = stream.Measure(number=mm.number)
        if mm.timeSignature:
            new.timeSignature = mm.timeSignature
        if mm.keySignature:
            new.keySignature = mm.keySignature
        for el in mm.notesAndRests:
            if el.isRest:
                new.insert(el.offset, note.Rest(quarterLength=el.duration.quarterLength))
            else:
                top = max(el.pitches, key=lambda p: p.ps)
                new.insert(el.offset, note.Note(top, quarterLength=el.duration.quarterLength))
        out.append(new)
    return out


def force_monophonic(part):
    """Reduce a vocal staff to one line, keeping every distinct attack.

    Built from note ONSETS, not from time slices: a slice-and-merge reduction
    welds consecutive same-pitch notes into one long note, which destroys
    repeated notes ("A, a, a"). Simultaneous notes collapse to the highest, an
    overlapping note is truncated at the next onset, and gaps become rests.
    """
    for mm in part.getElementsByClass('Measure'):
        voices = list(mm.voices)
        sources = voices if voices else [mm]
        events, rests = {}, []
        for src in sources:
            for el in list(src.notesAndRests):
                off = round(float(el.offset), 6)
                dur = float(el.duration.quarterLength)
                if el.isRest:
                    rests.append((off, dur, is_tagged(el)))
                    continue
                pitch = max(el.pitches, key=lambda p: p.ps) if el.isChord else el.pitch
                tag = is_tagged(el)
                prev = events.get(off)
                if prev is None or pitch.ps > prev[0].ps:
                    events[off] = (pitch, max(dur, prev[1] if prev else 0.0), tag)
                else:
                    events[off] = (prev[0], max(prev[1], dur), prev[2] or tag)
        for v in voices:
            mm.remove(v)
        for el in list(mm.notesAndRests):
            mm.remove(el)
        if not events and not rests:
            continue
        onsets = sorted(events)
        end_of_bar = max([o + events[o][1] for o in onsets]
                         + [o + d for o, d, _t in rests] + [0.0])
        covered = []
        for i, off in enumerate(onsets):
            pitch, dur, tag = events[off]
            limit = onsets[i + 1] if i + 1 < len(onsets) else end_of_bar
            if limit > off:
                dur = min(dur, limit - off)
            if dur <= 0:
                continue
            # No Tuplet is copied across: quarterLength is the SOUNDING length,
            # so music21 re-derives the tuplet from it. Assigning the source
            # note's Tuplet on top applies the ratio a second time and shrinks
            # the note to two thirds of what it should be.
            new = note.Note(pitch, quarterLength=dur)
            try:
                new.editorial['omr_tuplet'] = tag
            except Exception:
                pass
            mm.insert(off, new)
            covered.append((off, off + dur))
        for off, dur, tag in rests:
            a, b = off, off + dur
            # 1e-6, not 1e-9: onsets are rounded to 6 dp but note ends are not,
            # so a rest butting exactly against the previous note reads as a
            # hair of overlap and gets discarded -- which silently removes the
            # closing rest of a tuplet group and makes the group unrecognisable.
            if not any(ca < b - 1e-6 and cb > a + 1e-6 for ca, cb in covered):
                r = note.Rest(quarterLength=dur)
                try:
                    r.editorial['omr_tuplet'] = tag
                except Exception:
                    pass
                mm.insert(a, r)


# ---------------------------------------------------------------------------
# Time signatures
# ---------------------------------------------------------------------------

def propagate_time_signature(parts):
    """Give every part the song's meter.

    OMR may detect it on one staff only; a part left without one is never
    duration-checked, and a reader then defaults it to 4/4.
    """
    first = None
    for p in parts:
        for mm in p.getElementsByClass('Measure'):
            if mm.timeSignature is not None:
                first = mm.timeSignature
                break
        if first is not None:
            break
    if first is None:
        return None
    for p in parts:
        ms = list(p.getElementsByClass('Measure'))
        if ms and not any(mm.timeSignature is not None for mm in ms):
            ms[0].timeSignature = m21.meter.TimeSignature(first.ratioString)
    return first.ratioString


def infer_time_signature(parts, default='4/4'):
    if any(mm.timeSignature is not None for p in parts for mm in p.getElementsByClass('Measure')):
        return None
    counts = {}
    for p in parts:
        for mm in list(p.getElementsByClass('Measure'))[1:]:
            k = round(span(mm), 2)
            counts[k] = counts.get(k, 0) + 1
    if not counts:
        return None
    common = max(counts.items(), key=lambda kv: kv[1])[0]
    ts = {1.0: '1/4', 1.5: '3/8', 2.0: '2/4', 3.0: '3/4', 4.0: '4/4', 6.0: '6/8'}.get(
        round(common), default)
    for p in parts:
        ms = list(p.getElementsByClass('Measure'))
        if ms:
            ms[0].timeSignature = m21.meter.TimeSignature(ts)
    return ts


def dedupe_time_signatures(part):
    last = None
    for i, mm in enumerate(part.getElementsByClass('Measure')):
        if mm.timeSignature is None:
            continue
        rs = mm.timeSignature.ratioString
        if i > 0 and rs == last:
            mm.remove(mm.timeSignature)
        else:
            last = rs


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

NOTE_TOK = re.compile(r'<note\b.*?</note>|<backup>.*?</backup>|<forward>.*?</forward>', re.S)
NOTE_RE = re.compile(r'<note\b.*?</note>', re.S)
MEASURE_RE = re.compile(r'<measure number="([^"]+)"[^>]*>(.*?)</measure>', re.S)
PART_RE = re.compile(r'<part id="([^"]+)">(.*?)</part>', re.S)


def voice_of(blk):
    m = re.search(r'<voice>(\d+)</voice>', blk)
    return m.group(1) if m else '1'


def staff_of(blk):
    m = re.search(r'<staff>(\d+)</staff>', blk)
    return m.group(1) if m else '1'


def primary_voice_per_staff(pbody):
    """Lowest voice number used on each staff, across the whole part.

    A grand-staff part shares ONE voice-number space across both staves, so the
    left hand's own first voice is typically 3 or 5. Treating "voice 1" as the
    only primary strips the left hand of every rest it may keep.
    """
    seen = {}
    for blk in NOTE_TOK.findall(pbody):
        if not blk.startswith('<note'):
            continue
        st, vo = staff_of(blk), int(voice_of(blk))
        seen[st] = min(seen.get(st, vo), vo)
    return {st: str(v) for st, v in seen.items()}


def clean_xml(path):
    """Post-process written MusicXML so the guarantees hold in the delivered file.

    Removes Audiveris's false <multiple-rest> (a reader expands it and inflates
    the bar past its meter), turns rests in non-primary voices into <forward>,
    and strips print-object="no" so nothing is invisible.
    """
    with open(path, encoding='utf-8') as fh:
        xml = fh.read()
    xml = re.sub(r'\s*<measure-style>\s*<multiple-rest[^>]*>.*?</multiple-rest>\s*</measure-style>',
                 '', xml, flags=re.S)
    xml = re.sub(r'\s*<attributes>\s*</attributes>', '', xml)
    xml = re.sub(r'<rest measure="yes"\s*(?:/>|></rest>)', '<rest />', xml)

    def fix_part(pm):
        pid, pbody = pm.group(1), pm.group(2)
        primary = primary_voice_per_staff(pbody)

        def repl(m):
            blk = m.group(0)
            if not blk.startswith('<note') or '<rest' not in blk:
                return blk
            if voice_of(blk) == primary.get(staff_of(blk), '1'):
                return blk
            dm = re.search(r'<duration>(\d+)</duration>', blk)
            return f'<forward><duration>{dm.group(1)}</duration></forward>' if dm else ''

        return f'<part id="{pid}">' + NOTE_TOK.sub(repl, pbody) + '</part>'

    xml = PART_RE.sub(fix_part, xml)
    xml = xml.replace(' print-object="no"', '')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(xml)


def safe_write(score, path, attempts=5):
    """Write MusicXML and confirm the file matches the in-memory score.

    music21's exporter is not idempotent: it can inflate a PartStaff's measure
    count (observed 301 -> 418) with no error raised. Each retry re-writes from
    the in-memory score, never from the corrupted file, which only compounds it.
    Returns (ok, measure_counts).
    """
    reference = [len(list(p.getElementsByClass('Measure'))) for p in score.parts] or [
        len(list(score.getElementsByClass('Measure')))]
    got = None
    for _ in range(attempts):
        try:
            score.write('musicxml', path, makeNotation=False)
        except Exception:
            score.write('musicxml', path)
        clean_xml(path)
        parsed = m21.converter.parse(path)
        got = [len(list(p.getElementsByClass('Measure'))) for p in parsed.parts] or [
            len(list(parsed.getElementsByClass('Measure')))]
        if got == reference:
            return True, got
    return False, got


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def measure_spans(body, divisions):
    """(max_position, {(staff, voice): end}) in quarter lengths for one measure.

    Walks note/backup/forward exactly as a notation program does. Verification
    deliberately does not go through music21: re-parsing applies its own
    interpretation (multirest expansion, voice gap filling) and will both invent
    problems and hide real ones.
    """
    pos = hi = 0.0
    ends = {}
    for t in NOTE_TOK.finditer(body):
        blk = t.group(0)
        dm = re.search(r'<duration>(-?\d+)</duration>', blk)
        dur = (int(dm.group(1)) / divisions) if dm else 0.0
        if blk.startswith('<backup'):
            pos -= dur
            continue
        if blk.startswith('<forward'):
            pos += dur
        else:
            if '<chord' in blk:
                continue
            pos += dur
            key = (staff_of(blk), voice_of(blk))
            ends[key] = max(ends.get(key, 0.0), pos)
        hi = max(hi, pos)
    return hi, ends


def verify_xml(path, label=None, max_voices=2):
    """Check a written MusicXML file against every rule in SKILL.md that can be
    checked mechanically. Returns a list of problem strings."""
    label = label or path
    problems = []
    with open(path, encoding='utf-8') as fh:
        xml = fh.read()

    if 'print-object="no"' in xml:
        problems.append(f'{label}: contains print-object="no" (hidden element)')
    if '<multiple-rest' in xml:
        problems.append(f'{label}: contains a multiple-rest')

    for pm in PART_RE.finditer(xml):
        pid, pbody = pm.group(1), pm.group(2)
        primary = primary_voice_per_staff(pbody)
        divisions = 1
        tsn = tsd = None
        rows = []
        for num, body in MEASURE_RE.findall(pbody):
            dm = re.search(r'<divisions>(\d+)</divisions>', body)
            if dm:
                divisions = int(dm.group(1))
            tm = re.search(r'<time[^>]*>\s*<beats>(\d+)</beats>\s*<beat-type>(\d+)</beat-type>',
                           body, re.S)
            if tm:
                tsn, tsd = int(tm.group(1)), int(tm.group(2))
            expected = (tsn * 4.0 / tsd) if tsn else None
            hi, ends = measure_spans(body, divisions)
            rows.append((num, body, expected, hi, ends))

        has_pickup = bool(rows) and rows[0][2] is not None and rows[0][3] < rows[0][2] - EPS
        for i, (num, body, expected, hi, ends) in enumerate(rows):
            if expected is not None:
                if hi > expected + EPS:
                    problems.append(f'{label}: part {pid} m{num} OVERLONG {hi} > {expected}')
                elif hi < expected - EPS and not ((i == 0 or i == len(rows) - 1) and has_pickup):
                    problems.append(f'{label}: part {pid} m{num} short {hi} < {expected}')
            per_staff = {}
            for (st, _v) in ends:
                per_staff[st] = per_staff.get(st, 0) + 1
            for st, cnt in per_staff.items():
                if cnt > max_voices:
                    problems.append(f'{label}: part {pid} m{num} staff {st} has {cnt} voices')
            for nb in NOTE_RE.finditer(body):
                blk = nb.group(0)
                if '<rest' in blk and voice_of(blk) != primary.get(staff_of(blk), '1'):
                    problems.append(
                        f'{label}: part {pid} m{num} rest in non-primary voice '
                        f'{voice_of(blk)} (staff {staff_of(blk)})')
                    break

        # trailing all-rest measures
        run = 0
        for num, body, _e, _h, _n in reversed(rows):
            blocks = NOTE_RE.findall(body)
            if not blocks or any('<rest' not in b for b in blocks):
                break
            run += 1
        if run > 1:
            problems.append(f'{label}: part {pid} ends with {run} all-rest measures')
    return problems


def count_notes(path_or_xml, is_xml=False):
    xml = path_or_xml if is_xml else open(path_or_xml, encoding='utf-8').read()
    n = r = 0
    for b in NOTE_RE.findall(xml):
        if '<rest' in b:
            r += 1
        else:
            n += 1
    return n, r


def read_any(path):
    """Parse .musicxml/.mxl/.mid directly, or .mscz via the MuseScore CLI."""
    if str(path).lower().endswith('.mscz'):
        raise ValueError('parse .mscz with mscz_to_musicxml() first')
    return m21.converter.parse(path)


def find_musescore(explicit=None):
    if explicit:
        return explicit
    for cand in ('/Applications/MuseScore 4.app/Contents/MacOS/mscore',
                 '/Applications/MuseScore 3.app/Contents/MacOS/mscore',
                 'mscore', 'musescore'):
        try:
            if subprocess.run([cand, '--version'], capture_output=True).returncode == 0:
                return cand
        except Exception:
            continue
    return None


def mscz_to_musicxml(mscz_path, out_path, musescore=None):
    exe = find_musescore(musescore)
    if not exe:
        raise RuntimeError('MuseScore CLI not found; pass --musescore PATH')
    r = subprocess.run([exe, '-o', str(out_path), str(mscz_path)], capture_output=True, text=True)
    return r.returncode == 0


def to_mscz(xml_path, mscz_path, musescore=None):
    exe = find_musescore(musescore)
    if not exe:
        raise RuntimeError('MuseScore CLI not found; pass --musescore PATH')
    r = subprocess.run([exe, '-o', str(mscz_path), str(xml_path)], capture_output=True, text=True)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def slugify(title):
    import unicodedata
    t = re.sub(r'^\s*\d+\.\s*', '', title)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^A-Za-z0-9]+', '_', t).strip('_').lower()


def deliverable_name(book_abbr, book_number, song_number, title, version=1, ext='musicxml'):
    return f'{book_abbr}_{book_number}_{song_number:02d}_{slugify(title)}_v{version}.{ext}'


def set_metadata(score, title=None, composer=None):
    score.metadata = score.metadata or metadata.Metadata()
    if title:
        score.metadata.title = title
    if composer:
        score.metadata.composer = composer


def name_parts(score, melody_name='Melody', piano_name='Piano'):
    for p in score.parts:
        if p.id == 'Melody' or (p.partName or '') == 'Melody':
            p.partName, p.partAbbreviation = melody_name, 'Mel.'
        elif 'piano' in (p.partName or '').lower():
            p.partName, p.partAbbreviation = piano_name, 'Pno.'
