# ConciseMusic architecture

## Source of truth

MusicXML is the authoritative persisted source for score identity. A future
authoritative in-memory score model should be populated directly from MusicXML
and retain stable source-event identity plus the properties required to render
the score faithfully:

- part and semantic instrument identity;
- measure, staff, and voice;
- written and concert pitch where applicable;
- notated onset and duration;
- chord membership;
- ties, slurs, articulations, and other retained performance semantics.

cmusic is a compact, deterministic semantic **view** of that model for language
model input and score analysis. It is not a replacement database for MusicXML.

```text
MusicXML -> authoritative semantic score AST -> cmusic renderer -> LLM
                                      |                           |
                                      |                    performance plan
                                      |                           |
                                      +---------------------------+
                                                                  |
                                                     performance realization
                                                                  |
                                                                 MIDI
```

The cmusic parser remains a supported public boundary. It provides a typed
syntax AST, validation, and deterministic canonical rendering:

```text
render(parse(canonical_cmusic)) == canonical_cmusic
```

That AST is appropriate for tools which receive cmusic as input. It must not be
made the authoritative note source for MusicXML-to-MIDI rendering merely to
reuse the serialization. The nesting-aware parser correctly handles cases such
as `[E4{s1<,s2<},E3]/1`, but avoiding a naive-parser bug does not justify an
unnecessary serialize/reparse stage in the authoritative rendering path.

## Performance interpretation

An LLM may interpret phrasing, character, balance, tempo shape, dynamics,
vibrato, articulation realization, and similar performance decisions. It
should not reconstruct pitches, chord members, voices, notated onsets, or
notated durations already present in the authoritative score.

A performance plan overlays the score and may derive performed onset,
performed duration, velocity, controller curves, articulation selection, and
other realization data. Applying a plan must not silently delete, invent, or
change the identity of source score events.

For the current generic orchestral experiment, the default profile is:

```ini
CC1  = primary dynamics / dynamic-layer crossfade
CC2  = vibrato amount or intensity
CC11 = expression / secondary phrase shaping
```

This is a renderer profile, not a universal MIDI convention. Piano should
normally use velocity for attack and dynamic character. Sample-library-specific
controller and keyswitch behavior belongs in adapters downstream of the
musical interpretation.

## Incremental semantic layer

The upstream seam is implemented by `SemanticScore`, `SemanticPart`, and
`SemanticMeasure`, which own ordered `SemanticNoteEvent` instances.
`NoteProvenance` and the typed `WrittenPitch`, `Rest`, `Unpitched`, and
`UnknownNote` content variants retain note identity. `import_musicxml()` returns
this reusable tree; `render_cmusic()` consumes it, and `convert()` is their thin
composition.

`semantic_note_event()` converts each MusicXML note into the event
representation before cmusic rendering. Parts, measures, instruments, and
events remain in source order, while the renderer continues to apply the
documented deterministic voice and direction ordering.
Pitch, rest/unpitched identity, instrument reference, part/measure/staff/voice
provenance, exact onset and duration, chord membership, and grace identity are
therefore no longer stored primarily as one pre-rendered `Event.token`.

This is deliberately not yet a complete MusicXML object model. Ties and slurs
are typed as `TieRelation` and `SlurRelation` on each semantic event. This keeps
notated and playback ties distinct and retains numbered slur endpoint identity
before serialization. Articulations are typed as ordered `ArticulationGroup`
values containing `Articulation` indications; grouping across multiple
`<notations>` blocks and semantic text remain intact while layout attributes
are discarded. Fermatas are typed as ordered `Fermata` shapes; placement and
coordinates remain excluded. Technical playing semantics are represented by
focused variants for harmonics, bends, value/flag indications,
component-structured indications, and numbered hammer/pull relations, grouped
in source order by `TechnicalGroup`. Other supported notation categories remain
ordered compact strings around a typed `GraceSemantics` value. Grace identity,
slash, and authored steal/make-time parameters are available without reading
cmusic; ornaments, tuplets, slides, and time-modification markers remain in the
ordered `pre_grace_markers` compatibility field, while noteheads and lyrics
remain in `notation_markers`. Measure attributes and timed directions are owned
by `SemanticMeasure` but retain their existing deterministic compact
representations. These boundaries preserve behavior while identifying the
remaining migration seams.

The smallest safe continuation remains incremental:

1. Select the next typed category based on a concrete performance consumer;
   ornaments and explicit trill realization are the strongest remaining
   note-level performance candidate.
2. Continue with other notation categories only when a concrete consumer needs
   their typed semantics.
3. Only then add a performance-plan overlay and generic performance
   representation. MIDI and library-specific adapters consume the authoritative
   records plus that overlay, never reparsed cmusic when MusicXML is available.

`semantic_audit.py` verifies ties and slurs from MusicXML to the imported model
at exact source-note granularity, then from the model to cmusic at the strongest
identity serialized by the format. This catches endpoint relocation even when
aggregate counts happen to match.

Do not create a parallel comprehensive object model inside the cmusic parser.
Its AST models the public compact language, including its intentional
normalizations. The future authoritative AST models imported score identity.
The two may share small value types later, but they have different contracts.

Expressive MIDI is intentionally outside the current implementation scope.

## Neutral realization and MIDI

`neutral_midi.py` demonstrates that `SemanticScore` is independently useful:

```text
SemanticScore -> realize_neutral() -> NeutralRealization -> encode_midi()
```

`PerformedNote` is distinct from `SemanticNoteEvent` and carries one or more
`SourceEventId` values. `EventDisposition` records direct realization,
tie-merging, or intentional silence. `audit_realization()` checks source-event
accounting and rejects performed notes without semantic provenance.

The encoder is a standard-library Standard MIDI File adapter, not a score
model. Neutral policy is deterministic and non-expressive. The later
`PerformancePlan` layer can replace or augment realization without changing
the semantic score or forcing cmusic to become an authoritative database.
