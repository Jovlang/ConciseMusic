# Semantic notation audit

This audit records authored musical information that `concise-music-v1`
currently omits. It is intentionally separate from the slur change: none of
the items below have been added to the format yet.

## High-priority performance and phrasing information

- **Articulations:** accent, strong accent/marcato, staccato, staccatissimo,
  tenuto, detached legato, spiccato, breath marks, caesuras, stress, and
  unstress. These affect performance and generally cannot be inferred from
  pitch and duration.
- **Ornaments:** trill marks, turns, mordents, schleifers, shakes, wavy lines,
  and tremolos. These can prescribe sounding notes that are absent from the
  written pitch sequence.
- **Fermatas:** including their semantic presence and shape where shape has a
  conventional duration meaning. Positioning attributes are engraving only.
- **Pedal directions:** start, stop, change, continue, and sostenuto markings.
  Line geometry and placement should remain omitted.
- **Octave shifts:** start/stop/continue plus shift size and direction. These
  alter the intended sounding register and are not recoverable from the
  notated pitch alone.

## Other non-derivable authored instructions

- **Arpeggiate / non-arpeggiate**, including numbered spans across voices.
- **Glissando and slide** start/stop markers and line type where it changes the
  requested performance; omit coordinates.
- **Technical indications:** fingering, string/fret, harmonic, open string,
  stopped, snap pizzicato, bowing, brass techniques, and related instructions.
- **Notehead semantics:** special notehead types can communicate playing
  techniques, especially for percussion and harmonics. Color and dimensions
  are layout.
- **Rehearsal/navigation and performance directions:** rehearsal marks, segno,
  coda, fine, D.C./D.S. playback/navigation semantics, and direction types not
  captured by the current tempo/dynamics/words/wedge subset.
- **Instrument changes and sound techniques:** MusicXML instrument switches,
  mute/pizzicato/channel/program changes, and percussion instrument identity.
- **Tuplet notation:** exact performed duration is retained, but explicit
  tuplet grouping and normal/actual-note intent are not. Whether this needs a
  compact marker depends on whether the format must preserve notation intent
  in addition to timing.

## Deliberate omissions

- Stems, beams, print positions, bezier control points, placement, orientation,
  fonts, colors, and other engraving/layout metadata.
- `<harmony>` chord symbols. Their omission remains intentional: they are
  analytical annotations rather than required note/performance content for
  this representation.
- Note type and dots when they merely restate the exact retained duration.

Before adding any audited category, its semantic subset and compact syntax
should be specified explicitly so layout attributes do not leak into the
format indiscriminately.

## Display-field leakage review

Rest `display-step` and `display-octave` values are now explicitly discarded;
they only control the vertical position of a rest glyph. The remaining emitted
fields were reviewed for common MusicXML layout attributes (`default-*`,
`relative-*`, placement, orientation, font, color, print, stem, and beam data),
and none of those attributes are serialized.

Unpitched notes now use their semantic `<instrument id>` references and a
part-level instrument catalog. Their normal display positions are discarded.
When a note genuinely has no usable instrument reference, `x?(D5)` retains the
display position only as an explicitly unknown fallback (or `x?` if even that
is absent). The fallback does not claim that position identifies an instrument;
two unknown events at the same position may still be semantically ambiguous in
the source and should be reported by downstream audits if identity matters.
