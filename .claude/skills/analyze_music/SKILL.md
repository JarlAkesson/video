---
name: analyze-music
description: Use when an arranged MusicXML score needs to be parsed into music_analysis.json — extracting tempo, meter, key, parts, phrases, melody candidates, and harmony — for downstream vocal planning. Does not read lyrics or alter the score.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [musicxml-file]
effort: medium
---

# Skill 1: `analyze_music`

## Purpose

Turn `arranged_music.xml` into a compact musical representation that an LLM can reason over without reading raw MusicXML.

This skill is music-analysis-only. It should not read lyrics and should not alter the score.

## Inputs

```text
arranged_music.xml
```

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
- list parts and instruments
- extract measures, notes, rests, voices, and durations
- infer key and meter
- read tempo markings
- chordify the arrangement to infer harmonic context
- find candidate melody lines
- compute ranges and singability features

## Core responsibilities

1. Parse the score.
2. Extract global metadata: tempo, meter, key, measure count.
   - Don't trust the written barlines by default. Explicitly check the actual note-duration pattern at the start of the piece against the anacrusis shape every time — a short note or repeated pair of identical short notes (lighter-weight than what follows, or marked staccato) leading into a longer, more stable note — and treat a match as a possible mis-notated anacrusis (upbeat) rather than a downbeat. Do this check regardless of whether the opening measure contains a rest: a rest is one way an anacrusis gets mis-notated, but a measure that is already rhythmically "full" (no rest, adds up to the full bar) is just as capable of opening with this short-into-long shape, and its being metrically complete is not evidence the barline is already correct. Cross-check the hypothesis against the harmonic reading (step 6): re-derive the harmony under both the literal barring and the shifted-by-the-pickup barring, and prefer whichever produces the more idiomatic result — chord tones landing on strong beats instead of weak ones, fewer forced mid-measure splits, and cadences/climaxes resolving onto harmonically logical chords (tonic, dominant) rather than requiring an odd substitute. If the melody contains a chromatic/leading-tone accidental, this is a decisive test: prefer the barring in which that note resolves forward onto the following downbeat, not one that strands it mid-measure after its resolution has already happened.
   - The piece's very first upbeat does not get its own measure number, even when it's a genuine, correctly-notated pickup (e.g. filled out with rests before it). Measure numbering starts at 1 with the first full measure; refer to the opening anacrusis separately (as the pickup/upbeat).
3. Extract part-level metadata: instrument names, ranges, density, likely role.
4. Identify melody candidates.
5. Estimate phrase boundaries.
   - Determine phrase boundaries from the melody's own signals first — rests, matching rhythmic/motivic units, repeated contours — independently of the harmonic analysis in step 6. Don't let wherever a chord happens to resolve dictate where a phrase ends: if the harmony doesn't fit neatly into melody-defined boundaries, it's the harmony that needs revisiting (e.g. keeping tonic through a boundary a dominant would otherwise cross), not the phrase grouping. A dominant crossing a clear, melody-defined boundary is only acceptable as a rare, well-motivated exception — typically because the melody leaves no other way to harmonize the note there — not a default reason to redraw the phrases around it.
6. Infer harmonic context, preferably as chord symbols or roman numerals.
   - Respect standard functional root motion: tonic → predominant → dominant → tonic.
   - Never resolve a dominant chord (V, vii°) directly to a predominant chord (ii, IV). A dominant should move to tonic (or, if prolonged, to another dominant-function chord); if a predominant sonority is needed after it, treat the intervening melody notes as passing/neighbor tones over the surrounding chord instead of introducing a new predominant harmony.
   - Avoid letting a V chord sit across a phrase boundary. A tonic or tonic-substitute chord can legitimately span from the end of one phrase into the start of the next, but a dominant essentially never should — it needs to resolve within its own phrase, not linger unresolved into the next one. If ending a phrase on V (a half cadence) would otherwise require carrying that same V into the following phrase before it resolves, prefer keeping the harmony on tonic through that boundary instead, even if that means less harmonic movement, rather than letting the dominant bleed across it.
   - At any structurally important arrival point, not only the piece's very ending, check whether the melody outlines a cadential shape rather than just sitting still — root-5th-root (tonic-dominant-tonic), or the classic scale-degree-5-up-a-fourth-to-1 melodic cadence — and harmonize it that way (V-I, or V7-I where the 7th is genuinely supported) instead of defaulting to a static tonic just because every note also happens to fit the tonic triad.
   - An anacrusis does not automatically get its own chord. The piece's very first anacrusis — the pickup before any harmony has been established at all — should not be assigned a chord entry; the first harmony entry belongs at the true downbeat it leads into. Any other anacrusis, occurring mid-phrase, should instead be read as continuing whatever chord was already sounding beforehand (a decorative/non-chord tone over that preceding harmony), not as belonging to the chord it resolves into — the harmony only actually changes at the point where the anacrusis resolves onto its target note.
   - For simple/nursery-style tunes, avoid assigning a chord that is dissonant with the melody note sounding above it — prefer the diatonic triad whose chord tones actually contain the melody note over one that only fits via an added 6th/9th or other color tone. This matters most for dominant chords: a clashing or colored dominant undercuts the cadential effect it's supposed to create. If no clean chord-tone fit spans a full measure, split the measure at the melodic change and assign each half its own (still consonant) chord rather than stretching one chord under a dissonant note. Exception: in minor/modal folk-style pieces, don't let this rule block a real V at a cadential moment just because the melody holds the tonic's minor 3rd (or another characteristic modal scale degree) against the chord's raised leading tone — that particular clash is a recognized, idiomatic feature of this style, not a fault, and is worth accepting when it completes a stronger cadential/harmonic-rhythm pattern (e.g. a regular i-V-i alternation).
   - Before reaching for a new harmonic function or a chord extension (7th, color tone) to explain a melody note, first check whether a plain triad already active nearby — usually the tonic or subdominant — simply contains that note outright. A held 5th or 3rd over an already-established tonic is often just that tonic prolonged, colored by a neighboring predominant (I-IV-I), not a sign a new chord has arrived. Only escalate to extensions or substitute readings once no combination of plain, nearby triads explains the notes cleanly, and if fixing one problem starts requiring a fancier chord, stop and recheck whether a simpler plain-triad reading of the surrounding harmony was available all along.
   - Before splitting a measure or reaching for a different chord to avoid a dissonant-looking melody note, check whether extending the candidate chord — most often adding a 7th to the dominant (V7) — turns that note into a genuine chord tone instead. A note that clashes against a plain triad may already be the chord's 7th. And once the main clash is resolved that way, a lingering color tone (e.g. a 9th) is often worth accepting rather than splitting, because it lets the whole measure sit under one clean, regularly-placed chord — which is usually a better trade than breaking the harmonic rhythm to avoid minor extension-tone dissonance.
   - When a dominant is prolonged across more than one measure before it resolves, keep it as a plain triad for most of that span and only add the 7th in the measure(s) immediately before the cadence. Save the extra tension for the last moment before resolution — that's where raising the stakes counts — rather than spreading the same color evenly across the whole prolongation, which gives it away too early and blunts the effect.
   - Avoid oscillating back and forth between two predominant chords (e.g. IV-ii-IV-ii). This kind of back-and-forth doesn't progress anywhere and reads as awkward voice leading. When consecutive melody notes could each be harmonized by more than one predominant chord (e.g. a note that is a chord tone of both ii and IV), prefer holding a single sustained predominant harmony across the whole span over swapping chords back and forth.
   - Keep the harmonic rhythm regular (e.g. one chord change per measure, landing on the downbeat) rather than letting chord changes fall at irregular, arbitrary points mid-measure. When a melody note within the measure doesn't fit the prevailing chord as a plain chord tone, prefer reading it as a suspension, passing tone, or appoggiatura over that chord rather than triggering an early/off-beat harmony change. Reserve mid-measure chord changes for deliberate, consistently-placed harmonic acceleration into a cadence (e.g. splitting the measure right before a cadential resolution), not as a default way to accommodate every melody note.
   - "Regular" doesn't mean slow: in lively, dance-style tunes, default to a faster, evenly-spaced harmonic rhythm (roughly one chord per beat or two) over long static pedal points, even where a single sustained chord would technically work. Weigh the richest well-supported progression against the sparsest one that merely fits, and favor the richer one for this kind of material — fewest chords is a tiebreaker, not the goal.
   - Land chord changes on strong beats — beat 1 or 3 in 4/4 and 3/4 — over weak or fractional positions, even if that means reading the on-beat note as an appoggiatura resolving to the real chord tone right after. Consistent, strong-beat harmonic rhythm matters more than avoiding occasional appoggiaturas. When a held note is dissonant against its harmonic context, apply this same principle: first check whether the chord itself can still land right on the strong beat, with the dissonance read as a suspension/appoggiatura that resolves down by step *within* that same chord — before reaching for a reading that delays the chord's arrival to a weaker beat, or that invents an extra chord (e.g. an added 7th) just to make the held note consonant. Apply this device consistently at every later instance of the same shape, rather than resolving the first one on-beat and then letting a later, otherwise-identical case drift onto a weak beat or acquire an unearned extension — consistency across matching moments matters more than finding the single richest label for each one individually.
   - When the note sitting on a strong beat is a tone shared by both the outgoing and incoming chord (e.g. a note that's the dominant's root and also the tonic's 5th), don't default to reading it as the outgoing chord held over. Check whether assigning it to the incoming chord instead lands the resolution right on that strong beat — if so, prefer that reading.
   - Before letting one chord hold an entire measure or phrase-segment, check the note on its *last* strong beat too, not just its opening note(s) — that note needs to be a genuine chord tone, not a decorative one left stranded by a chord that's being held over from earlier. If the obvious first-fit chord fails this check, look for a different single chord that covers both the opening notes and this strong-beat note as real chord tones (often a closely-related predominant, e.g. ii instead of IV).
   - When a melody note is a clean chord tone of both a predominant chord (ii, IV) and the dominant (V), prefer the dominant if using it would complete a stronger cadential progression (e.g. turning IV-ii-I into IV-V-I) or land the dominant at a structurally important arrival point, such as the retransition back into a returning phrase/section. A real authentic cadence (V-I) at these moments is usually more idiomatic than a plagal-style predominant-to-tonic resolution, and reusing the same dominant chord for every internal cadence keeps the piece's cadential vocabulary unified.
   - Actively reach for ii and vi as part of a real predominant chain (e.g. vi-ii-V-I), not just as occasional substitutes for IV when the notes happen to force it. A full diatonic circle-of-fifths motion through the predominant area is often more idiomatic — especially in simple folk/dance material — than repeatedly falling back on I and IV alone; check for this opportunity deliberately rather than only reaching for ii/vi when a note fails to fit anything else.
   - Once a ii chord is used, let it lead to V — do not let ii directly back to I be the point of resolution. Unlike IV, which can idiomatically resolve straight to I (plagal motion), ii exists to prepare the dominant; "ii-I" as a resting point is a red flag that V got skipped. That said, ii-I is fine when I is only a brief passing chord on the way to V, not the resolution itself — e.g. ii-I-V-I, where the first I is just a quick step through a chord tone before the dominant arrives and completes a real authentic cadence. Before finalizing a progression, check root motion legality and consistency with the harmonic rhythm already established elsewhere in the piece before reaching for a mid-measure split to fix a dissonant note — if the piece has been using one chord per full measure, prefer absorbing a non-fitting note as a decorative/passing tone within the expected whole-measure chord (matching the established root-motion and rhythmic pattern) over introducing a one-off split.
   - For any chord-to-chord move, check the candidate chord's root against the melody's motion, not just chord-tone consonance. If a chord's root is the same pitch as the melody note over it and both move in the same direction into the next chord's root/melody note, that's parallel unisons/octaves between "bass" and melody — reject the chord even if every melody note is a clean chord tone. This applies throughout the progression, not just at cadences.
   - Reserve dominant-function substitutes (vii°, and similar passing/leading-tone chords) for internal, non-final moments. At true structural cadences — especially the final cadence of the piece — prefer the actual V chord, so the bass gets the strong descending-5th root motion (5→1) into the tonic instead of the weaker stepwise approach a substitute chord gives.
   - When a melody note is a clean chord tone of more than one diatonic chord, don't default to whichever chord is already sustained out of inertia. Weigh the alternatives on their own merits: which gives the strongest root motion (e.g. a descending fifth) into the chord that follows, and — especially in a minor-key piece — whether a relative-major substitute (III for i, or similarly a major-mode substitute elsewhere) is equally well-supported by the melody and would add worthwhile color contrast instead of prolonging the same tonic chord by default. Also check whether the melody note simply doubles the candidate chord's own root, especially right at the moment of harmonic change — that produces a thin, under-supported texture even when nothing else is wrong with the choice, so prefer an equally-valid alternative that instead lands the melody on a different chord tone (3rd or 5th).
   - After harmonizing measure by measure, zoom out and check the cadential shape of the whole piece. A piece with no V chord anywhere is a red flag, even if every individual measure's chord looked well-justified in isolation — measure-level correctness doesn't guarantee a purposeful, arc-shaped harmonic structure overall. It is very important that a piece has a purposeful, arc-shaped harmonic structure. Reserve full plagal treatment for the places that genuinely don't support V, rather than letting it become the piece's only cadence type by default.
   - When a piece has more than one phrase-ending cadence, actively look for a chance to vary the cadence type across them (authentic, plagal, deceptive, half) rather than resolving every phrase the same way, and reserve the strongest, fullest-color authentic cadence specifically for the piece's true final structural cadence. A cadence choice that would be perfectly fine on its own can still be the wrong pick if it makes an internal phrase indistinguishable from the ending — check the whole piece's cadence sequence, not just whether each individual cadence works in isolation.
   - If the piece's phrase lengths are otherwise inconsistent — e.g. most phrases share one length but a pair of shorter phrases sits joined by a full-stop cadence in between — and the melody at that seam resolves stepwise onto a non-tonic scale degree (often scale degree 6, landing on vi), check whether reading the approach as that chord's own secondary dominant (e.g. V/vi), rather than the main key's dominant resolving deceptively, removes the seam and merges the two short phrases into one matching the rest of the piece. Only make this call when it's actually fixing a real inconsistency in the piece's phrase structure — not as a routine substitute for an ordinary deceptive cadence.
7. Emit `music_analysis.json`.

## Color and variation

The bullets under step 6 above cover the functionally-required reading of the melody — the chords that are actually implied. Once that reading is solid, it's also worth noting optional color/variation choices that go beyond strict function, especially on a repeated phrase where a small harmonic twist keeps the repeat from feeling like a flat copy. These are enrichments layered on top of the functional analysis, not something the bare melody demands, so surface them separately (e.g. as a note/warning) rather than folding them into `chord_guess` as if they were required.

- When a stable chord (often the tonic) sits right before a plain diatonic move that has no connective pull between the two chords, consider coloring the departing chord with an added 7th so it functions as an applied/secondary dominant of what follows. The added tone should resolve down a half step onto a chord tone the melody is already heading toward (often the root or 5th of the next chord) — that gives the progression a directed pull instead of two chords just sitting next to each other. This works especially well on the second pass of a repeated phrase, where the first statement can stay on the plain, functionally-clear chord and the repeat gets the extra color.
- If the harmonic rhythm is consistent and simple throughout (e.g. one chord per measure everywhere), consider varying it between phrases rather than only within them: keep it steady inside each phrase, but let some phrases move faster than others (e.g. a second chord on beat 3 of each measure) to add motion without touching the ones that stay simple. Look first for "decorative" notes already treated as passing/neighbor tones — if one is a clean tone of a different, legally-reachable chord (checking root-motion and dominant/predominant resolution rules as usual), promoting it to a real chord change is an easy, well-supported way to do this. Leave a phrase's final, cadence-resolving measure untouched even when its neighbors get the faster treatment — splitting the arrival itself undercuts the sense of arrival the added movement elsewhere is building toward.
- When promoting a decorative note to a real chord, don't default to whichever predominant (usually IV) is already used elsewhere for the same scale degrees — check whether ii or vi fits as well or better (often less thin, and ii is then legally bound toward V), and spread different predominant colors across a repeated phrase pair rather than reusing the same one everywhere.
- Actively look for chances to color a plain move into a predominant (e.g. I-ii, I-vi) with that predominant's own secondary dominant, especially where a note is already held or repeated right before it. Check whether that note works as a non-root tone (the 3rd or 5th) of the secondary dominant rather than settling for it as plain decoration under the departing chord — landing it on its own strong beat if possible. Deliberately avoid using it as the secondary dominant's root: that would double it against the melody and create parallel motion into the target chord's root right after. Only do this when it strengthens the cadential shape and harmonic arc of a piece.

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
./bin/analyze_music arranged_music.xml --out music_analysis.json
```

## Failure modes

Return a nonzero exit code and diagnostic JSON if:

- MusicXML cannot be parsed
- no usable note material is found
- lyrics are empty
- tempo cannot be determined and no default is supplied

If key, chords, or phrases are uncertain, emit warnings instead of failing.
