---
name: analyze-music
description: Use when a score's basic_analysis.json (from the basic_analysis skill) is ready and needs its harmonic layer inferred, producing the final music_analysis.json — chord symbols or roman numerals per measure/beat — for downstream vocal planning. Does not read lyrics or alter the score.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [basic-analysis-json]
effort: medium
---

# Skill 2: `analyze_music`

## Purpose

Take `basic_analysis.json` (produced by the `basic_analysis` skill: tempo, meter, key, measure count, parts, phrases, melody candidates) and infer its harmonic layer, emitting the complete `music_analysis.json` that an LLM can reason over without reading raw MusicXML.

This skill is harmonic-analysis-only. It should not read lyrics and should not alter the score. It depends on `basic_analysis` having already run; if `basic_analysis.json` isn't available, run that skill first.

## Inputs

```text
basic_analysis.json
```

(and the original `arranged_music.xml`, for direct note/beat access when computing harmony)

Optional config:

```json
{
  "preferred_vocal_range": ["C4", "A5"],
  "target_style": "gentle children's song",
  "language_hint": "English"
}
```

## Tools

### music21

Use `music21` to:

- parse MusicXML
- extract measures, notes, rests, voices, and durations
- chordify the arrangement to infer harmonic context

## Core responsibilities

1. Infer harmonic context, preferably as chord symbols or roman numerals.
   - Respect standard functional root motion: tonic (I) → predominant (ii/IV) → dominant (V/vii°) → tonic.

   **Dominant function**
   - When a melody note is a clean chord tone of both a predominant chord (ii, IV) and the dominant (V), prefer the dominant if using it would complete a stronger cadential progression (e.g. turning IV-ii-I into IV-V-I) or land the dominant at a structurally important arrival point, such as the retransition back into a returning phrase/section. A real authentic cadence (V-I) at these moments is usually more idiomatic than a plagal-style predominant-to-tonic resolution, and reusing the same dominant chord for every internal cadence keeps the piece's cadential vocabulary unified.
   - Never resolve a dominant chord (V, vii°) directly to a predominant chord (ii, IV). A dominant should move to tonic (or, if prolonged, to another dominant-function chord); if a predominant sonority is needed after it, treat the intervening melody notes as passing/neighbor tones over the surrounding chord instead of introducing a new predominant harmony. Before doing so, actively check whether a held or repeated note that looks like it wants a new predominant chord is actually the dominant's own minor 7th (V7) instead.
   - Reserve dominant-function substitutes (vii°, and similar passing/leading-tone chords) for internal, non-final moments. At true structural cadences — especially the final cadence of the piece — prefer the actual V chord, so the bass gets the strong descending-5th root motion (5→1) into the tonic instead of the weaker stepwise approach a substitute chord gives.
   - The same choice applies to applied/secondary dominants: prefer the real applied dominant (e.g. V7/V) over its diminished substitute (e.g. viiø7/V) whenever the substitute's root motion would oscillate back to where it started (e.g. 5-#4-5) — the real applied dominant gives much stronger motion instead (e.g. 5-2-5). Only prefer the diminished substitute when it lets the bass move by step in one direction (e.g. 3-#4-5); never when it means oscillating.
   - Prefer opening a piece on I when the first measure is harmonically ambiguous — the opening should establish the tonic, so read scale degree 5 on the downbeat as I's 5th rather than automatically as V's root, and harmonize any later repeat of that same figure as I too, for consistency. But don't force this: where the melody plainly spells out V (its 3rd or 7th sounding, or the tonic triad fitting only via decoration), open on V and let it resolve.
   - Avoid letting a V chord sit across a phrase boundary. A tonic or tonic-substitute chord can legitimately span from the end of one phrase into the start of the next, but a dominant essentially never should — it needs to resolve within its own phrase, not linger unresolved into the next one. If ending a phrase on V (a half cadence) would otherwise require carrying that same V into the following phrase before it resolves, prefer keeping the harmony on tonic through that boundary instead, even if that means less harmonic movement, rather than letting the dominant bleed across it.
   - At any structurally important arrival point, not only the piece's very ending, check whether the melody outlines a cadential shape rather than just sitting still — root-5th-root (tonic-dominant-tonic), or the classic scale-degree-5-up-a-fourth-to-1 melodic cadence — and harmonize it that way (V-I, or V7-I where the 7th is genuinely supported) instead of defaulting to a static tonic just because every note also happens to fit the tonic triad.
   - In a measure of cadential significance — typically a phrase's last measure — when the dominant ties with a rival chord on triad evidence, re-score it as V7 wherever the melody sounds the 7th: a note that looked decorative under plain V is often the genuine 7th, which might settle the tie. Prefer the dominant when it also gives the phrase a real cadence and reuses a mid-measure split already established elsewhere, so the harmonic rhythm stays consistent.
   - When a dominant is prolonged across more than one measure before it resolves, keep it as a plain triad for most of that span and only add the 7th in the measure(s) immediately before the cadence. Save the extra tension for the last moment before resolution — that's where raising the stakes counts — rather than spreading the same color evenly across the whole prolongation, which gives it away too early and blunts the effect.

   **Predominant Function**
   - Once a ii (or ii° in minor) chord is used, let it lead to V — never let it resolve directly back to I/i, whether once or repeatedly (ii-I-ii-I oscillation is the same mistake, just repeated); ii-I is fine only when I is a brief passing chord on the way to V, not the resolution itself. Whenever ii/ii° fits, always check V7 directly against the same notes before settling: its tones are ii/ii°'s root and 3rd plus two more (5th and minor 7th), so V7 often fits better, explaining a note directly as its own 5th or minor 7th instead of needing it to resolve or depart. Prefer V7 whenever this happens — it also turns the following I into a real, repeatable authentic cadence (V7-I). Separately, even where ii is correct, prefer IV over ii if the melody centers on ii's 3rd and 5th rather than its root: those same two notes are IV's root and 3rd, and IV's root motion into I (a descending 4th) is stronger than ii's (a plain step). Also prefer IV whenever the melody moves scale-degree 7 down to 6 over a predominant — that whole-step resolution (rather than the half step an ordinary 4-3 suspension gives) is the signature of the key's leading tone suspending specifically over IV, not ii.
   - Avoid oscillating back and forth between two predominant chords (e.g. IV-ii-IV-ii). This kind of back-and-forth doesn't progress anywhere and reads as awkward voice leading. When consecutive melody notes could each be harmonized by more than one predominant chord (e.g. a note that is a chord tone of both ii and IV), prefer holding a single sustained predominant harmony across the whole span over swapping chords back and forth.
   - Across a two-measure predominant span, prefer ii-IV-V-I over ii-ii-V-I wherever IV fits the second measure's melody as well as ii does — the predominant keeps progressing into the dominant instead of stalling on one chord. This is a single forward move, not the back-and-forth swapping the previous bullet rules out.
   - Actively reach for ii and vi as part of a real predominant chain (e.g. vi-ii-V-I), not just as occasional substitutes for IV when the notes happen to force it. A full diatonic circle-of-fifths motion through the predominant area is often more idiomatic — especially in simple folk/dance material — than repeatedly falling back on I and IV alone; check for this opportunity deliberately rather than only reaching for ii/vi when a note fails to fit anything else.
   - In minor keys, check the subtonic (VII) as an alternative to ii°/iv when equally well-supported — especially right after III, where III-VII-i (descending 5ths, then a step up to i) is a classic backdoor progression, stronger than a ii°-iv-i sequence with no clear narrative.
   - In a measure directly following a tonic (I) measure, when I and IV fit its melody equally well (common, since the tonic's root is also IV's 5th), prefer IV — I-IV-V-I gives real predominant-to-dominant motion instead of just repeating the tonic before V arrives.

   **Harmonic Rhythm**
   - Land chord changes on strong beats — beat 1 or 3 in 4/4 and 3/4 — over weak or fractional positions, even if that means reading the on-beat note as a suspension or appoggiatura resolving to the real chord tone right after: check whether the chord can still land right on the strong beat this way before delaying its arrival to a weaker beat. This applies with particular force at a phrase's own cadential resolution — don't let the arrival chord be the one exception that lands late just because delaying it looks cleaner in isolation.
   - Keep the harmonic rhythm regular (e.g. one chord change per measure, landing on the downbeat) rather than letting chord changes fall at irregular, arbitrary points mid-measure, or worse, mid-beat. Reserve mid-measure chord changes for deliberate, consistently-placed harmonic acceleration into a cadence (e.g. splitting the measure right before a cadential resolution), not as a default way to accommodate every melody note.
   - "Regular" is judged by position within the phrase, not per measure: mid-measure splits belong in a phrase's cadential second half, with its first half held one chord per measure. An alternation that recurs at the same phrase position throughout is regular by definition — don't flag it as uneven, and don't flatten it to one chord per measure for uniformity's sake. Before finalizing, line the phrases up and compare slot by slot; the real irregularity is a split appearing in one phrase's slot but not in the matching slot of its parallel phrases, or the same melodic figure split in one place and held in another.
   - "Regular" doesn't mean slow: in lively, dance-style tunes, default to a faster, evenly-spaced harmonic rhythm (roughly one chord per strong beat) over long static pedal points, even where a single sustained chord would technically work. Weigh the richest well-supported progression against the sparsest one that merely fits, and favor the richer one for this kind of material — fewest chords is a tiebreaker, not the goal.
   - In a piece that's otherwise one-chord-per-measure (or one-per-strong-beat), be suspicious of a chord that runs longer than a measure but splits off at a beat other than the next downbeat (e.g. bleeding from measure 2 into the first half of measure 3) — this is usually a sign a cleaner reading exists. Check whether extending the following chord (e.g. adding a 9th) lets it cover the whole measure on its own instead of starting mid measure.
   - When the note sitting on a strong beat is a tone shared by both the outgoing and incoming chord (e.g. a note that's the dominant's root and also the tonic's 5th), don't default to reading it as the outgoing chord held over. Check whether assigning it to the incoming chord instead lands the resolution right on that strong beat — if so, prefer that reading. Weigh this with extra force once a consistent per-measure rhythm is already established nearby (e.g. a change on beat 3 in the surrounding measures): extend that same rhythm to the ambiguous measure by default, rather than letting a shared tone become an excuse to hold one chord longer than its neighbors.
   - Before explaining a strong-beat note as a departure/passing tone to keep the chord held, check whether it's instead a direct, undecorated fit for a different chord — and prefer that reading when it also fits the established harmonic rhythm (e.g. lines up with a beat-3 change already used nearby), even if the departure reading technically verifies too. A common specific case: a held note that looks like a 2-1 suspension resolving down to the tonic root is often actually V's own 5th resolving to I — check this before defaulting to the suspension reading.

   **Regarding Dissonance**
   - A melody note that isn't a genuine tone of the prevailing or incoming chord can be read as a suspension, passing tone, or appoggiatura — but only if it resolves by step, on the very next note, onto a genuine tone of that chord. That resolution is the actual test; don't reach for the label just because a note is inconvenient to explain. A note a 4th above a chord's root is a classic, idiomatic suspension resolving down to the chord's 3rd (the textbook "4-3" shape) — recognize it deliberately, and use it as a tool for introducing a real predominant into an otherwise-static passage (e.g. reading a held 5th-scale-degree note as a suspended 4th over an incoming ii/IV, instead of defaulting to a static tonic or an unrelated dominant), not only as an excuse to explain away a note that doesn't fit. Apply the identical shape consistently at every later instance with the same interval-and-resolution pattern — don't solve the first occurrence with a suspension and a later, identically-shaped one with a different device (e.g. a mid measure chord change).
   - For simple/nursery-style tunes, avoid assigning a chord that is dissonant with the melody note sounding above it — prefer the diatonic triad whose chord tones actually contain the melody note over one that only fits via an added 6th/9th or other color tone. This matters most for dominant chords: a clashing or colored dominant undercuts the cadential effect it's supposed to create. If no clean chord-tone fit spans a full measure, split the measure at the melodic change and assign each half its own (still consonant) chord rather than stretching one chord under a dissonant note. Exception: in minor/modal folk-style pieces, don't let this rule block a real V at a cadential moment just because the melody holds the tonic's minor 3rd (or another characteristic modal scale degree) against the chord's raised leading tone — that particular clash is a recognized, idiomatic feature of this style, not a fault, and is worth accepting when it completes a stronger cadential/harmonic-rhythm pattern (e.g. a regular i-V-i alternation).
   - Before splitting a measure or reaching for a different chord to avoid a dissonant-looking melody note, check whether extending the candidate chord — most often adding a 7th to the dominant (V7) — turns that note into a genuine chord tone instead. A note that clashes against a plain triad may already be the chord's 7th. And once the main clash is resolved that way, a lingering color tone (e.g. a 9th) is often worth accepting rather than splitting, because it lets the whole measure sit under one clean, regularly-placed chord — which is usually a better trade than breaking the harmonic rhythm to avoid minor extension-tone dissonance.
   - Before letting one chord hold an entire measure or phrase-segment, check the note on its *last* strong beat too, not just its opening note(s) — that note needs to be a genuine chord tone, not a decorative one left stranded by a chord that's being held over from earlier. If the obvious first-fit chord fails this check, look for a different single chord that covers both the opening notes and this strong-beat note as real chord tones (often a closely-related predominant, e.g. ii instead of IV). When more than one closely-related chord could equally well explain a measure's main notes this way, also weigh how gently each candidate handles any chromatic or dissonant passing/neighbor tone nearby: a half-step or other dissonance landing on a chord's root is far more exposed than the identical clash landing on that chord's 3rd or 5th, since the root is the chord's most structurally prominent tone. When candidates are otherwise equally well-supported, prefer whichever one lets the passing tone brush a less exposed chord tone rather than its root.

   **General**
   - Don't assume one key covers the whole piece, and don't let the key signature settle it — a modulation between relatives needs no signature change. An accidental that acts as a raised 7th, resolving up a half step to a local tonic, establishes that minor key outright; reading the passage in the relative major instead would make the same note a raised 5th, which has no such function. If the piece's final cadence then confirms a different tonic, that's a real key change, not a tonicized vi or III: label each section in its own key and identify what joins them. A separate pivot chord belonging to both keys (e.g. VI in the minor doubling as IV in the relative major) is one option, but a deceptive V-III can carry the modulation by itself — the dominant resolves onto the relative major instead of i, and III is already the incoming tonic. Prefer whichever option gives the more consistent harmonic rhythm; don't insert a pivot chord that forces a mid-measure split the surrounding measures don't have.
   - When a melody note is a clean chord tone of more than one diatonic chord, don't default to whichever chord is already sustained out of inertia. Weigh the alternatives on their own merits: which gives the strongest root motion (e.g. a descending fifth) into the chord that follows. Also check whether the melody note simply doubles the candidate chord's own root, especially right at the moment of harmonic change — that produces a thin, under-supported texture even when nothing else is wrong with the choice, so prefer an equally-valid alternative that instead lands the melody on a different chord tone (3rd or 5th).
   - In a minor-key piece, once i has already held for one or more consecutive measures, actively check the relative major (III) before defaulting to i again for the next ambiguous measure — this check is required even when i already fits, not only when a note fails to fit it. If III is equally well-supported by the melody, prefer it for the color contrast.
   - For any chord-to-chord move, check the candidate chord's root against the melody's motion, not just chord-tone consonance. If a chord's root is the same pitch as the melody note over it and both move in the same direction into the next chord's root/melody note, that's parallel unisons/octaves between "bass" and melody — reject the chord even if every melody note is a clean chord tone. This applies throughout the progression, not just at cadences.
   - If the piece's phrase lengths are otherwise inconsistent — e.g. most phrases share one length but a pair of shorter phrases sits joined by a full-stop cadence in between — and the melody at that seam resolves stepwise onto a non-tonic scale degree (often scale degree 6, landing on vi), check whether reading the approach as that chord's own secondary dominant (e.g. V/vi), rather than the main key's dominant resolving deceptively, removes the seam and merges the two short phrases into one matching the rest of the piece. Only make this call when it's actually fixing a real inconsistency in the piece's phrase structure — not as a routine substitute for an ordinary deceptive cadence.
   - An anacrusis does not automatically get its own chord. The piece's very first anacrusis — the pickup before any harmony has been established at all — should not be assigned a chord entry; the first harmony entry belongs at the true downbeat it leads into. Any other anacrusis, occurring mid-phrase, should instead be read as continuing whatever chord was already sounding beforehand (a decorative/non-chord tone over that preceding harmony), not as belonging to the chord it resolves into — the harmony only actually changes at the point where the anacrusis resolves onto its target note.
   - After harmonizing measure by measure, zoom out and check the cadential shape of the whole piece. A piece with no V chord anywhere is a red flag, even if every individual measure's chord looked well-justified in isolation — measure-level correctness doesn't guarantee a purposeful, arc-shaped harmonic structure overall. It is very important that a piece has a purposeful, arc-shaped harmonic structure. Reserve full plagal treatment for the places that genuinely don't support V, rather than letting it become the piece's only cadence type by default.
   - Give special scrutiny to the piece's actual final measure(s): if they read as a static tonic with some note explained away as a passing/neighbor decoration, check whether that "decorative" note is actually a genuine tone of V (most often its 5th) instead. If so, prefer the real V-I authentic cadence there — even if it lands the chord change on an unusual beat (e.g. beat 4, not just 1 or 3) — over ending the piece on an unsupported tonic pedal.
   - Before finalizing, check every carried-over chord (one simply continued from the previous measure, not freshly derived from its own notes) using the Bash tool with music21 rather than eyeballing it — carried-over chords are exactly where mistakes hide, since nothing prompted a fresh look. Confirm each strong-beat melody note is a genuine tone of that chord or resolves by step into one on the next note; a note that is neither is a hard sign the chord is wrong for that measure.
2. Emit `music_analysis.json`.

## Melodic improvement suggestions

Occasionally the melody as received seems to contain a genuine pitch mistake — not a hard-to-harmonize note, but one that blocks a clean harmonic structure no matter how it's approached. Only ever question a note's pitch, never its rhythm/duration; a full-blown reinterpretation is out of scope here. Only flag one when both hold: (1) it's causing a real structural problem, not routine dissonance — e.g. a phrase that can't cadence where a phrase of that length clearly should, or the one note breaking an otherwise-exact repeated phrase — and (2) a small stepwise correction (up or down by a single scale step) resolves it cleanly, landing the note on a chord tone that fits the surrounding harmony the way the rest of the phrase does. State the original pitch, the correction, and the specific structural problem it fixes; leave the source score untouched and apply the fix only within this analysis, noting it as a warning.

## Output

Write `music_analysis.json` matching `schemas/music_analysis.schema.json`.

Example:

```json
{
  "score": {
    "tempo_bpm": 96,
    "meter": "4/4",
    "key": "C major",
    "measure_count": 16,
    "parts": [
      {
        "id": "P1",
        "name": "piano",
        "range": ["C3", "G5"],
        "role_guess": "accompaniment",
        "density_score": 0.72
      },
      {
        "id": "P2",
        "name": "flute",
        "range": ["C4", "A5"],
        "role_guess": "melody_candidate",
        "density_score": 0.31
      }
    ],
    "phrases": [
      {
        "id": "A1",
        "measures": [1, 4],
        "cadence_guess": "half cadence",
        "melody_candidate_part": "P2"
      }
    ],
    "harmony": [
      {
        "measure": 1,
        "beat": 1.0,
        "chord_guess": "I"
      }
    ],
    "melody_candidates": [
      {
        "source_part": "P2",
        "measures": [1, 8],
        "note_count": 32,
        "singability_score": 0.86,
        "range": ["C4", "G5"]
      }
    ]
  },
  "warnings": []
}
```

## Why this output is useful

The next skill needs to decide where and how to sing. It needs compact facts:

- which part probably carries the tune
- where phrases start and end
- whether the melody fits a singable range
- how many melody notes are available
- whether accompaniment conflicts with the vocal register

## Suggested CLI

```bash
./bin/analyze_music basic_analysis.json --out music_analysis.json
```

## Failure modes

Return a nonzero exit code and diagnostic JSON if:

- `basic_analysis.json` is missing or doesn't validate
- the underlying MusicXML cannot be re-read for note/beat access
- lyrics are empty

If chords are uncertain, emit warnings instead of failing.
