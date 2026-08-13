# Rare repairs: bars that resist the ordered fixes

Load when `normalize_measures.py` logs `UNRESOLVED`, or when its repair counts
look wrong (dozens of carries in one song where a clean run has a handful).

The repairs themselves are implemented in `scripts/omrlib.py`; this file is
about reading their output and deciding what a stubborn bar means.

## What the repair names mean

Reported by `normalize_measures.py` under `fixes:`. A handful per song is
normal; a flood is a signal.

| Name | Meaning |
|---|---|
| `drop-rest-past-barline` | Filler rest for a bar whose barline the OMR lost. Most overlong bars are only this, and it costs nothing. |
| `truncate-rest-at-barline` | A rest straddling the bar end, cut back. |
| `carry-note-to-next-measure` | A real note starting past the barline, moved rather than cut. |
| `undot` | A spurious augmentation dot — a staccato dot or a scan speck — removed because it exactly accounted for the excess. |
| `compress-run-as-tuplet` | An equal-duration run squeezed to fit: a tuplet the OMR lost. |
| `clip-overhang` | Last resort. The note stays; only its tail shortens. |
| `quantize-bar` | The bar was solved jointly and re-laid; normal and cheap. |
| `rescale-degenerate-bar` | See below. Rare and worth checking. |
| `UNRESOLVED` | Nothing worked. Decide by hand — never by deleting a note. |

## Degenerate bars

Audiveris occasionally emits a whole measure with intact pitches but nonsense
durations — 1/840, 1/3360, 1/5040 of a quarter, with offsets to match. The
relative proportions survive; only the absolute scale is lost, so scaling the
bar back up to the meter recovers it.

Guarded to fire only when the bar is more than eight times too short, which no
real pickup ever is. **Validate rather than trust it**: if the affected page
repeats music that another page recognised cleanly, the rescale should
reproduce that reading note for note. In book 3's "Vallvisa" it did, including
the sextuplets — which is the only reason to believe it.

## Carry cascades

If `carry-note-to-next-measure` explodes, the cause is upstream, not the carry
rule. Look for a pass that pushes a note's start later — to a cursor, to avoid
an overlap — **without also shortening it**. The note keeps its full length
from a later position, spills past the barline, gets carried, and the next bar
overflows in turn, all the way down the part. The fix belongs in that pass.

## Dots that should not be there

Same failure as an invented tuplet, and it hides better because dotted notes are
everywhere in this repertoire. Three rules keep them honest:

1. **Never scale a bar to fit its meter.** Solving a short bar by stretching its
   notes turns three quarters in 4/4 into two dotted quarters; solving a long one
   by squashing them does the mirror image. Pad a short bar with rests, and fix a
   long one by truncating the filler rest that overruns the barline. Scaling is
   correct in exactly one place -- a degenerate bar, where the proportions
   survived and only the absolute scale was lost.
2. **A rejected tuplet member reverts to its WRITTEN value**, not to whatever
   binary value is nearest its sounding length. A quarter inside a triplet sounds
   2/3, and 2/3 snaps to a dotted eighth -- so throwing out a bad tuplet quietly
   converts it into a bad dot. Divide by the tuplet multiplier instead. In book 3
   this made songs 4, 7 and 11 land exactly on their meter, which is what
   confirmed the reading.
3. **Padding rests use plain values.** A padded rest is editorial, not something
   the engraver wrote, so a 1.5-beat gap is a quarter plus an eighth rest, never
   a dotted-quarter rest that looks deliberate. A wholly empty bar is the
   exception: one full-measure rest is conventional there.

`normalize_measures.py` audits this automatically (`census_stream` before,
`census_xml` after) and reports any increase as `INVENTED`. Legitimate movement
is downward -- the `undot` repair removing a spurious augmentation dot, a
rejected tuplet, a duplicate voice collapsing. An increase is a defect.

One false positive is known and handled: a degenerate bar has no readable
ornaments until it is rescaled, so the baseline is taken AFTER
`rescale_degenerate_bars`, and the rescale snaps to real note values (thirds
only where the engine tagged a tuplet). Without both of those the recovery
itself reads as invention.

## Tuplets that should not be there

An invented tuplet is worse than a missing one: it looks deliberate. Two
independent things must hold before one is written, and `obvious_tuplet_groups`
enforces both.

1. **The engine tagged the run.** Never let the bar solver reach for thirds on
   its own to make a measure add up -- unconstrained, it invented 46 tuplets
   across book 3, in songs whose sources contain none.
2. **The bar corroborates**: with every duration snapped to the triplet-aware
   vocabulary, it already sums to its meter. Audiveris emits `<time-modification>`
   as a by-product of misreading a bar -- in book 3's song 7 it tagged three
   plain quarters as a triplet, leaving the bar a beat short. A tuplet that only
   works if other notes are stretched to fit around it is part of a misreading.

Applied to book 3 this keeps 24 tuplet notes (all in "Vallvisa", corroborated
against a page that repeats the same music cleanly) and rejects the 10 tagged
elsewhere. Check a render against the source before trusting any of them.

## Tuplets that come out lumpy

A sextuplet landing as `.375 .375 .25 .375 .375 .25` means triplet values were
excluded from the duration vocabulary. Check that `--no-triplets` is off, and
that nothing downstream rebuilds bars from a binary-only set — the single-voice
flattening used for accompaniment does exactly that, which is why melody-only
runs keep tuplets and mixed runs need care.

Watch also for the reverse failure: a `Tuplet` object copied onto a `Duration`
built from an already-sounding `quarterLength` applies the ratio **twice**,
shrinking the note to two thirds. `quarterLength` is the sounding length;
music21 re-derives the tuplet from it. Never re-attach.
