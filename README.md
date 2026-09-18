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
  the voice identifier, such as `v1s2`.
- Note suffixes use braces: `{>}` and `{<}` are tie start/stop; `{s1>}` and
  `{s1<}` are numbered slur start/stop; `{g}` is a grace note; and
  `{ly="text"}` is a lyric. Multiple markers can occur together.
- Timed directions use `@quarter-offset:value`, such as `@0:tempo=120`.

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

The test suite covers conversion fundamentals, microtonal accidentals, output
name collisions, slurs across barlines, nested and overlapping slurs, multiple
slur events on one note, and combined ties and slurs.

## Project files

- `concise_musicxml.py` — converter and CLI.
- `concise_musicxml_gui.py` — graphical batch converter.
- `test_concise_musicxml.py` — unit tests.
- `NOTATION_AUDIT.md` — scoped review of currently omitted semantic notation.
