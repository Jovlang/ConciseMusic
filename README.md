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
- Provides both a command-line tool and a Windows-friendly drag-and-drop GUI.
- Uses only the Python standard library for command-line conversion.

## Quick start

Python 3.10 or newer is required.

```console
python concise_musicxml.py score.musicxml -o score.cmusic
python concise_musicxml.py score.mxl
```

Without `-o`, the converted score is printed to standard output.

## Desktop GUI

Install the drag-and-drop dependency:

```console
python -m pip install -r requirements.txt
python concise_musicxml_gui.py
```

On Windows, you can launch the interface by double-clicking `launch_gui.bat`.
The GUI accepts multiple files, lets you choose the output directory, and
writes one `.cmusic` file per source. It remains usable through the file picker
if `tkinterdnd2` is unavailable.

## Concise format

Example:

```text
@score format=concise-music-v1 title="Example" source="score.musicxml"
@part P1 name="Piano"
m1 div=4 key=0:major time=4/4 clef1=G2 @0:tempo=120 | C4{s1>}/1 D4/1 [E4,G4]/1 F4{s1<}/1
```

The main conventions are:

- One score header, followed by each `@part` and its measures.
- `mN` begins a measure. Attributes occur before `|`; notes occur after it.
- `pitch/duration` represents a note. Duration is an exact fraction of a
  quarter note, so `/1` is a quarter and `/1/2` is an eighth.
- `r` is a rest, `_duration` is a silent gap, and `[C4,E4]/1` is a chord.
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
  `transposex2=dia:-4,chrom:-7,oct:-1`.
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

See [NOTATION_AUDIT.md](NOTATION_AUDIT.md) for semantic notation categories
that have been identified but are not yet represented.

## Tests

```console
python -m unittest -v
```

The regression suite includes paired semantic-collision and layout-normalizing
tests in addition to conversion fundamentals, voices, notation spans,
percussion identity, instrument changes, and grace/tuplet behavior.

## Project files

- `concise_musicxml.py` — converter and CLI.
- `concise_musicxml_gui.py` — graphical batch converter.
- `test_concise_musicxml.py` — unit tests.
- `NOTATION_AUDIT.md` — scoped review of currently omitted semantic notation.
