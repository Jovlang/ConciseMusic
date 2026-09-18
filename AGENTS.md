# AGENTS.md

## Project purpose

ConciseMusic converts MusicXML into the compact `concise-music-v1` text format
for use with language models. Preserve semantic musical intent; omit redundant
derived information and engraving-only metadata.

## Development rules

- Keep the command-line converter usable with the Python standard library.
- Treat the text format as a versioned public interface. Document syntax
  changes in `README.md` and cover them with focused tests.
- Preserve authored musical information that cannot be reconstructed reliably
  from pitch, timing, and the other retained events.
- Keep ties and slurs semantically distinct. Retain MusicXML numbers for
  notations whose spans may overlap.
- Do not add layout properties such as coordinates, fonts, colors, placement,
  orientation, stem direction, beam geometry, or bezier controls.
- Do not add MusicXML `<harmony>` chord symbols. Their omission is intentional.
- Avoid adding notation categories wholesale. Define their semantic subset and
  compact representation first, excluding engraving attributes.
- Maintain deterministic output for identical input.
- Keep GUI conversion logic in the core converter rather than duplicating it.

## Converter structure

- `note_suffix()` is an ordered renderer, not a general MusicXML parser. Add or
  modify note semantics in the focused extractor responsible for that category.
- `NOTE_MARKER_EXTRACTORS` defines serialized marker order. Reordering it is a
  format change and must not occur during structural cleanup.
- Every notation extractor must use `notation_elements()` or an equivalent
  centralized traversal that reads **all** `<notations>` blocks on a note.
  MusicXML permits multiple blocks; reading only the first loses semantics.
- Extractors should return compact semantic marker data or strings. Keep XML
  traversal, semantic normalization, and final rendering visibly separated.
- Do not introduce a generic MusicXML object model, schema mirror, framework,
  or class hierarchy for hypothetical features.

## Ordering contracts

- Note marker categories follow `NOTE_MARKER_EXTRACTORS` order.
- Multiple notation blocks and multiple markers within one category retain
  source order unless a documented normalization deliberately deduplicates them.
- Equal-offset directions retain source order.
- Chord members retain note source order. Grace notes remain sequential unless
  MusicXML explicitly marks them as chord members.
- Voices use stable identifier order.
- Instrument aliases follow score-instrument definition order; undefined
  referenced IDs follow first-reference order.
- Intentional deduplication must retain deterministic first-occurrence order and
  preserve later conflicting semantic information.

## Semantic boundaries

Keep these distinctions explicit during implementation and review:

- playback `<tie>` versus notated `<tied>`, and ties versus slurs;
- pitched notes versus unpitched percussion;
- percussion identity versus staff display position;
- note-level semantics versus timed direction events;
- authored performance semantics versus engraving/layout attributes;
- sequential grace notes versus grace chords;
- instrument identity from XML IDs versus names, display position, or inference.

## Verification

Run before committing:

```console
python -m unittest -v
python -m py_compile concise_musicxml.py concise_musicxml_gui.py semantic_audit.py test_concise_musicxml.py
```

For MusicXML notation changes, include tests for multiple events on one note,
events spanning measures, numbered overlapping spans, and interaction with
existing suffix markers where applicable.

Every semantic feature should have both:

- a collision test proving musically distinct inputs remain distinct; and
- a normalization test proving layout-only variants serialize identically.

The representative fixture at `tests/fixtures/semantic_golden.musicxml` must
match `semantic_golden.cmusic` byte-for-byte. Do not update the golden output
merely to silence a failure; understand and approve the difference first.

For available full scores, run:

```console
python concise_musicxml.py input.musicxml -o candidate.cmusic
python semantic_audit.py input.musicxml candidate.cmusic
```

Structural refactors require byte-for-byte comparison with output generated
before the refactor. Record source/output byte sizes and compression ratio as
informational metrics; never trade semantics for a smaller output.

If a structural refactor exposes an existing semantic bug, document it and
handle it as a separate behavioral change with its own regression test.

## Style

- Target Python 3.10 or newer.
- Prefer small standard-library functions and explicit data structures.
- Use `pathlib.Path` for filesystem paths.
- Keep the compact output readable without sacrificing unambiguous parsing.
