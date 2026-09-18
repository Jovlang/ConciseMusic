# Semantic notation audit

This audit describes the current boundary of `concise-music-v1`. The converter
is not claimed to be semantically lossless.

## Retained semantic notation

- Pitches, exact timing, chords, rests, voices/staves, transposition chromatic
  offset, keys, meters, clefs, repeats/endings, tempo, dynamics, words, wedges,
  lyrics, ties, numbered slurs, and grace-note ordering/timing attributes.
- Articulations, fermata shape, ornament type, accidental marks, tremolo
  type/strokes, and numbered wavy lines.
- Trill realization attributes: start note, trill step, two-note turn,
  acceleration, beats, first/second beat, and last beat. These are treated as
  performance semantics. Placement, color, and glyph styling remain layout.
- Numbered pedal and octave-shift events at exact offsets.
- Tuplet ratio, optional normal note type, and numbered start/stop grouping.
- Technical indications, including authored text and semantic nested details
  for fingering alternatives/substitutions, harmonics, bends, holes, arrows,
  harmon mutes, and hammer-on/pull-off spans.
- Numbered glissando and slide relations, authored text, and slide bend-sound
  timing. Line style and geometry are omitted.
- Chord-level arpeggiate/non-arpeggiate identity, direction, and number, with
  redundant per-note chord markers normalized.
- Part-local instrument catalogs, unpitched identity, and voice-local stateful
  instrument changes for pitched events. Missing identity in a multi-instrument
  context is emitted as unknown rather than guessed.

## 1. Semantic and still unsupported

Known MusicXML distinctions that can still collide include:

- Tie semantics encoded only with notation-level `<tied>` and no playback
  `<tie>` element.
- Notehead types used as playing techniques, notehead parentheses, and semantic
  notehead text.
- Full lyric structure: verse numbers, syllabic state, elision, extension, and
  humming/laughing distinctions. Lyric text itself is retained.
- Rehearsal marks; segno/coda symbols and navigation; principal-voice spans;
  damp/damp-all; harp-pedal diagrams; scordatura; accordion registration;
  percussion directions; and semantic `<other-direction>` values.
- Direction brackets/dashes when they define a semantic span rather than a
  visual enclosure.
- Complex metronome relations and beat-unit dots. Simple per-minute tempo is
  retained.
- Playback `<sound>` semantics other than tempo, including D.C./D.S./Fine/To
  Coda routing, pizzicato, MIDI channel/program/controller changes, pan,
  elevation, and continuous pedal values.
- Full transposition semantics beyond chromatic offset: diatonic spelling,
  octave change, and double-transposition flags.
- Nontraditional/microtonal key definitions and composite/interchangeable or
  senza-misura time signatures.
- Measure-repeat, multiple-rest, slash, and beat-repeat semantics from
  `<measure-style>`.
- Figured bass and bass-alteration semantics. `<harmony>` remains an explicit
  product decision described below.

## 2. Derived or intentionally redundant

- Note type and augmentation dots when exact quarter-note duration already
  determines performed timing.
- Stem direction and ordinary beam elements under the format's pitch/rhythm
  analysis scope.
- Playback duration duplicated by notated type, except where tuplet/grace
  intent requires an explicit semantic marker.
- Rest display position when the event is already identified as a rest.
- Unpitched display position when semantic instrument identity is available.

## 3. Engraving/layout only

The converter intentionally drops print/default/relative coordinates, bezier
controls, placement, orientation, line geometry/style where it has no defined
performance meaning, fonts, colors, glyph choices, staff spacing, page/system
layout, stem/beam drawing, bracket drawing, and arpeggio/glissando placement.

Layout-normalization tests cover technical marks, glissandi/slides,
arpeggiation, trill realization, and instrument switching. Scores differing
only in these tested layout attributes produce identical concise output.

## 4. Ambiguous or intentionally deferred

- Courtesy, cautionary, editorial, and parenthesized accidentals: pitch alter
  is retained, but editorial intent is not yet modeled.
- Notehead shape can be purely graphical or a performance technique depending
  on repertoire; it remains deferred rather than copied indiscriminately.
- Beam grouping can communicate metrical analysis beyond raw duration, despite
  often being derivable. The current format intentionally omits it.
- Fermata upright/inverted values are treated as placement; fermata shape is
  retained. Repertoire-specific contrary meanings are not modeled.
- Trill visual line style and glyph selection are treated as engraving; only
  the allowlisted realization attributes above are semantic.
- An unpitched event without a usable instrument reference uses `x?(D5)` (or
  `x?`). Display position is retained only as an explicitly unknown fallback
  and never treated as identity. Two such unknown events may still collide.
- `<harmony>` chord symbols are intentionally omitted as analytical
  annotations, per the format's design requirement, even when authored.

Every future addition should include paired semantic-collision tests and
layout-normalization tests before moving a field between these classifications.
