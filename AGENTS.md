# AGENTS.md

## Project purpose

ConciseMusic converts MusicXML into the compact `concise-music-v1` text format
for use with language models. Preserve semantic musical intent; omit redundant
derived information and engraving-only metadata.

## Development rules

- Keep the command-line converter usable with the Python standard library.
- Treat the text format as a versioned public interface. Document syntax
  changes in `README.md` and cover them with focused tests.
- Keep `concise_music_parser.py` compatible with every canonical token emitted
  by the converter. Converter output must parse and render byte-for-byte.
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
- written key signature (`key=N` fifths) versus inferred tonal center or mode;
  conventional MusicXML `<mode>` must not be serialized into the key token.

## Architectural boundaries

- MusicXML is the authoritative persisted source for score identity.
- cmusic is a compact semantic view for LLM reasoning, not an authoritative
  intermediate database for MusicXML-to-MIDI rendering.
- Keep the cmusic parser typed, deterministic, and lossless for canonical
  cmusic. Do not weaken it because authoritative rendering uses another path.
- Grow the shared semantic score layer directly from MusicXML before cmusic
  token rendering. `import_musicxml()` returns the ordered `SemanticScore`,
  `SemanticPart`, `SemanticMeasure`, and `SemanticNoteEvent` tree consumed by
  `render_cmusic()`. Do not regress to a pre-rendered all-in-one event token or
  mistake this incremental model for a complete MusicXML object model.
- Keep ties and slurs in typed `TieRelation` and `SlurRelation` event fields.
  Rendering may normalize redundant playback ties, but the semantic import must
  retain the distinction between `<tie>` and `<tied>`.
- Keep articulation blocks in ordered typed `ArticulationGroup` values. Retain
  authored textual values, discard layout attributes, and preserve group/source
  order when rendering existing `art=` markers.
- Keep fermatas in ordered typed `Fermata` values. Preserve authored shape,
  discard placement and coordinates, and retain their marker position after
  technical indications.
- Represent grace identity and authored slash/steal/make-time behavior with
  `GraceSemantics`; do not reintroduce a parallel grace boolean. Preserve the
  existing marker position after time-modification semantics.
- Model technical indications with the focused `Technical*` variants and
  ordered `TechnicalGroup` values. Do not replace them with raw XML or a generic
  attribute dictionary; exclude layout properties during import.
- Performance plans may affect realization but must not invent, delete, or
  mutate source-event identity. LLMs interpret performance; they do not
  reconstruct notes already present in the score.
- MIDI controller and keyswitch conventions belong to renderer profiles and
  sample-library adapters, not to the score model or cmusic grammar.
- Keep authored MusicXML MIDI channel/program/unpitched values on the existing
  semantic instrument definition. Convert their 1-based numbering only in the
  realization adapter; never infer these mappings from names or staff position.
- Grace-note timing belongs to realization, not `SemanticNoteEvent` duration.
  Preserve every grace source identity and keep grace chords simultaneous while
  sequential grace notes receive distinct performed slots.

## Verification

Run before committing:

```console
python -m unittest -v
python -m py_compile concise_musicxml.py concise_music_parser.py concise_musicxml_gui.py neutral_midi.py semantic_audit.py test_concise_musicxml.py test_concise_music_parser.py test_concise_musicxml_gui.py test_neutral_midi.py
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

The relation audit must continue checking both MusicXML → semantic model and
semantic model → cmusic. Source-to-model checks use per-part note identity;
model-to-output checks use the strongest location and relation identity that
cmusic serializes. Do not replace these with aggregate-only counts.

Neutral MIDI must consume `SemanticScore` directly through a distinct
realization layer. Every semantic note/rest needs an explicit disposition and
every performed note needs source provenance. Never use source-note count equal
to MIDI-note count as a general invariant, and never parse cmusic in this path.

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
