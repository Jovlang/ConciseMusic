# ConciseMusic

ConciseMusic converts MusicXML into a compact, deterministic text format made
for LLM context windows. It preserves the authored musical structure needed to
reason about a score while omitting bulky engraving and layout data.

## Features

- Reads `.xml`, `.musicxml`, and compressed `.mxl` scores.
- Preserves parts, measures, voices, staves, pitches, exact durations, rests,
  chords, ties, numbered slurs, lyrics, key and time signatures, clefs, tempo,
  dynamics, repeats, and endings.
- Keeps ties and slurs distinct, including overlapping or nested slurs.
- Includes a standard-library parser with a structured, byte-stable AST for
  reading generated `concise-music-v1` files.
- Provides both a command-line tool and a Windows-friendly drag-and-drop GUI.
- Uses only the Python standard library for command-line conversion.

## Quick start

Python 3.10 or newer is required.

```console
python concise_musicxml.py score.musicxml -o score.cmusic
python concise_musicxml.py score.mxl
```

Without `-o`, the converted score is printed to standard output.

## Parsing concise music

Use the parser as a library when an application needs reliable access to the
format rather than ad-hoc whitespace or regular-expression splitting:

```python
from pathlib import Path

from concise_music_parser import parse_file

score = parse_file(Path("score.cmusic"))
for part in score.parts:
    for measure in part.measures:
        for voice in measure.voices:
            for event in voice.events:
                print(event)
```

The AST exposes score/part metadata, instrument definitions, measures, exact
fractional direction offsets and durations, voices, silent gaps, notes, chord
members, instrument references, and ordered marker groups. Its scanner is aware
of quoted strings and nested `()`, `[]`, and `{}` groups, so punctuation inside
lyrics, custom technical text, microtonal pitches, and chord suffixes is not
misread as a separator.

Canonical converter output must render byte-for-byte unchanged:

```console
python concise_music_parser.py score.cmusic --roundtrip
```

Malformed input raises `ParseError` with its source line. The parser only
accepts `format=concise-music-v1`; a future format version must be implemented
explicitly rather than being guessed.

## Desktop GUI

Install the drag-and-drop dependency:

```console
python -m pip install -r requirements.txt
python concise_musicxml_gui.py
```

On Windows, you can launch the interface by double-clicking `launch_gui.bat`.
The GUI accepts multiple files, lets you choose the output directory, and has
three output modes: **cmusic**, **MIDI**, or **Both**. Both outputs are rendered
from the same imported `SemanticScore`; MIDI generation never reparses cmusic.
It remains usable through the file picker if `tkinterdnd2` is unavailable.

## Neutral MIDI

The neutral MIDI path consumes the imported `SemanticScore` directly; it never
parses cmusic:

```python
from concise_musicxml import import_musicxml, load_xml
from neutral_midi import render_midi

score = import_musicxml(load_xml(Path("score.musicxml")), "score.musicxml")
result = render_midi(score)
Path("score.mid").write_bytes(result.data)
```

Or use the standard-library CLI:

```console
python neutral_midi.py score.musicxml -o score.mid
```

`result.realization` contains provenance-bearing `PerformedNote` objects and a
disposition for every semantic note/rest. `result.audit` verifies that every
source event is accounted for and every generated note points back to one or
more `SourceEventId` values. Tied score notes may therefore map many-to-one to a
performed note without losing their authored identities.

Initial neutral policies are deliberately conservative:

- Standard MIDI format 1, 480 ticks per quarter; one conductor track and one
  note track per semantic part.
- Authored `midi-channel`, `midi-program`, and `midi-unpitched` values are kept
  on semantic instrument definitions. Values are converted from MusicXML's
  1-based numbering only during realization.
- Authored channels are honored. Otherwise channels are assigned
  deterministically per part/staff/voice/instrument lane; unpitched instruments
  default to percussion channel 10 and pitched lanes avoid that channel.
- Written pitches are converted to sounding MIDI pitch using available
  chromatic/octave transposition. Microtones and ambiguous diatonic-only or
  doubled transpositions fail explicitly.
- Velocity is always 64. Authored MIDI programs produce deterministic program
  changes; programs are never inferred from names. No humanization, CC curves,
  keyswitches, or sample-library behavior is generated.
- Authored tempo and conventional time signatures are encoded; defaults are
  120 quarter-note BPM and 4/4. Unsupported metronome units and nonstandard
  meters fail explicitly.
- Matching ties merge score events into one continuous performed note while
  retaining every source identity.
- Ornaments remain one neutral performed note and are marked as unexpanded in
  the disposition. Grace groups take time from the beginning of the following
  principal note: authored `steal-time-following` percentages are honored;
  otherwise the group receives the smaller of an eighth-note or one quarter of
  the principal duration. Sequential grace notes divide that span evenly and
  grace-chord members share a slot. `make-time` and `steal-time-previous`
  currently fail explicitly.
- Unpitched percussion uses the referenced instrument's authored
  `midi-unpitched` mapping, never its display position. Missing references or
  mappings fail explicitly.
- Playback follows written linear measure order. Repeat barlines and navigation
  directives are not expanded. Measure-repeat/multirest/slash shorthand fails
  when concrete note content would need reconstruction.
- Pedal and octave-shift directions fail until dedicated realization policies
  exist. Dynamics and wedges do not alter the neutral velocity.

## Concise format

Example:

```text
@score format=concise-music-v1 title="Example" source="score.musicxml"
@part P1 name="Piano"
m1 div=4 key=0 time=4/4 clef1=G2 @0:tempo=120 | C4{s1>}/1 D4/1 [E4,G4]/1 F4{s1<}/1
```

The main conventions are:

- One score header, followed by each `@part` and its measures.
- `mN` begins a measure. Attributes occur before `|`; notes occur after it.
- `pitch/duration` represents a note. Duration is an exact fraction of a
  quarter note, so `/1` is a quarter and `/1/2` is an eighth.
- `r` is a rest, `_duration` is a silent gap, and `[C4,E4]/1` is a chord.
- `key=N` is the written key signature expressed as MusicXML fifths:
  `key=3` means three sharps, `key=-2` means two flats, and `key=0` means no
  key-signature accidentals. It does **not** assert a tonal center or mode.
  MusicXML `<mode>` is normalized away; tonal center and modality are derived
  musical analysis to be inferred from the score. Staff-specific signatures
  use `key1=N`, `key2=N`, and so on.
- Multiple voices use `v1: ... ; v2: ...`. A non-default staff is appended to
  the voice identifier, such as `v1s2`. The label may be omitted only for the
  canonical voice 1 on staff 1.
- Unpitched percussion uses a part-local semantic instrument alias such as
  `x@I1`. Its definition appears after the part header as
  `@instrument I1 id="P1-I1" name="Snare Drum" sound="drum.snare-drum"`.
  Aliases follow score-definition order and are scoped to their part. Staff
  display position is discarded. If MusicXML provides no instrument reference,
  `x?(D5)` is an explicitly unknown fallback retaining only the display
  locator; `x?` means neither identity nor a locator was available.
- Pitched instrument changes use the same mapping. In a multi-instrument voice,
  `C4@I1/1 D4/1 E4@I2/1` establishes `I1`, keeps it for `D4`, then switches to
  `I2`. Each voice has independent state. Single-instrument parts need no
  per-note markers, and an ambiguous missing reference is explicit as `@?`.
- Note suffixes use braces: `{t1>}` and `{t1<}` are numbered notated ties;
  `{soundtie>}` is a playback-only tie; `{s1>}` and `{s1<}` are numbered slur
  start/stop; and `{g}` is a grace note. Matching MusicXML `<tie>` and `<tied>`
  elements normalize to one notated tie marker.
- Timed directions use `@quarter-offset:value`, such as `@0:tempo=120`.

Additional semantic markers include:

- `art=staccato+accent`, `fer=normal`, and `orn=trill-mark` for articulations,
  fermatas, and ornaments. Tremolos and numbered wavy lines are retained within
  the ornament marker.
- `tup1>` / `tup1<` for numbered tuplet spans and `tm=3:2:eighth` for the
  performed-to-normal note ratio.
- `{g,gslash,gprev=20}` for grace-note identity, slash, and timing behavior.
- Timed `ped1=start`, `ped1=stop`, and `oct1=down:8` directions for pedal and
  octave-shift events. Numbered spans remain distinguishable.
- `tech=fingering:2+string:3+fret:5`, `tech=harmonic:natural`, and related
  properties preserve technical playing instructions and custom text.
- `gl1>` / `gl1<` and `slide1>` / `slide1<` are distinct numbered note
  relationships. Authored text and slide realization timing are retained.
- `[C4,E4,G4]{arp1^}/1` is an upward arpeggiated chord;
  `[C4,E4,G4]{noarp1}/1` explicitly forbids arpeggiation. Repeated per-note
  MusicXML markers are normalized once at event level.
- Explicit trill realization appears compactly, for example
  `orn=trill-mark(start=upper;step=half;accel=yes;beats=4)`.
- Rehearsal/navigation directions are structured as `rehearsal="B"`,
  `segno=S1`, `jump=DS:S1`, `tocoda=C1`, `coda=C1`, and `fine` at their exact
  measure offsets.
- Measure semantics include `measure-repeat=start:1`, `multirest=8`,
  `beat-repeat=start:eighth`, and `slash=start:quarter`.
- Nonstandard or staff-specific signatures use normalized escape forms such as
  `keyx2=F:1:sharp+B:0.5`, `timex2=3/8+2/8|5/8`, and
  `transposex2=dia:-4,chrom:-7,oct:-1`. `keyx` records the authored accidental
  set itself and likewise omits a generic major/minor mode label.
- Lyrics retain verse, syllabic state, elision, and extension, for example
  `{ly2="a‿mor",syl2=begin,ext2>}`.
- Semantically distinct noteheads use `{head=diamond}`, `{head=x}`, or
  `{head=diamond(paren)}`. Color, font, size, and glyph styling are discarded.

## Design scope

The guiding rule is to preserve authored musical information that cannot be
reconstructed unambiguously from the remaining representation. Stems, beams,
fonts, print coordinates, bezier geometry, and similar engraving data are
omitted. MusicXML `<harmony>` chord symbols are intentionally omitted as
analytical annotations.

cmusic is an LLM-facing semantic serialization, not the authoritative source
for expressive playback. MusicXML-derived score identity should remain in a
shared semantic score model; a future performance plan may interpret that
model without reconstructing its notes from cmusic. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the pipeline boundary and minimal path to
a shared authoritative AST.

The upstream semantic representation is available independently of rendering:

```python
from pathlib import Path

from concise_musicxml import import_musicxml, load_xml, render_cmusic

score = import_musicxml(load_xml(Path("score.musicxml")), "score.musicxml")
for part in score.parts:
    for measure in part.measures:
        for event in measure.events:
            print(
                event.provenance,
                event.content,
                event.onset,
                event.duration,
                event.ties,
                event.slurs,
            )

cmusic = render_cmusic(score)
```

`convert(root, source)` remains the compatibility API and is exactly
`render_cmusic(import_musicxml(root, source))`.

Notated ties, playback ties, numbered slur endpoints, ordered articulation
groups, authored fermata shapes, and grace slash/timing realization are typed
semantic values in this upstream model. Technical playing indications use
focused typed variants for harmonics, bends, fingerings/flags, nested
components, numbered hammer/pull relations, and custom semantic text. Other
note-notation categories remain ordered compact markers until a concrete
consumer requires a typed migration.

See [NOTATION_AUDIT.md](NOTATION_AUDIT.md) for semantic notation categories
that have been identified but are not yet represented.

## Ordering guarantees

Deterministic order is part of the serialized format:

- Note suffix categories follow the extractor order defined in
  `NOTE_MARKER_EXTRACTORS`; markers within a category retain MusicXML source
  order across every `<notations>` block.
- Direction events are ordered by musical offset, with source order retained
  when offsets are equal.
- Chord members retain note source order. Sequential zero-duration grace notes
  remain sequential unless MusicXML explicitly marks a chord.
- Voices are emitted in stable identifier order.
- Instrument aliases follow score-instrument definition order; referenced IDs
  without definitions follow first-reference order.

Intentional normalization, such as repeated chord arpeggiation markers, keeps
the first occurrence and only adds later information when it is semantically
distinct.

## Tests

```console
python -m unittest -v
```

The regression suite includes paired semantic-collision and layout-normalizing
tests in addition to conversion fundamentals, voices, notation spans,
percussion identity, instrument changes, and grace/tuplet behavior.

`semantic_audit.py` checks supported tie/slur relationships across both
architectural boundaries:

- MusicXML → semantic model, using exact per-part source-note identity;
- semantic model → cmusic, using part, measure, relation kind, number, and
  endpoint type.

It parses cmusic with the grammar-aware parser rather than splitting marker or
chord commas heuristically. The command also reports compression statistics:

```console
python semantic_audit.py score.musicxml score.cmusic
```

The repository golden fixture asserts byte-for-byte stable output across a
representative combination of independent note semantics.

## Project files

- `concise_musicxml.py` — converter and CLI.
- `concise_music_parser.py` — parser, structured AST, renderer, and validation CLI.
- `concise_musicxml_gui.py` — graphical batch converter.
- `neutral_midi.py` — neutral realization, provenance audit, MIDI encoder, and CLI.
- `test_concise_musicxml.py` — unit tests.
- `test_concise_music_parser.py` — parser and byte-exact round-trip tests.
- `test_neutral_midi.py` — neutral realization, provenance, and MIDI tests.
- `ARCHITECTURE.md` — source-of-truth and future performance-rendering boundaries.
- `NOTATION_AUDIT.md` — scoped review of currently omitted semantic notation.
