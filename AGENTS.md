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

## Verification

Run before committing:

```console
python -m unittest -v
python -m py_compile concise_musicxml.py concise_musicxml_gui.py test_concise_musicxml.py
```

For MusicXML notation changes, include tests for multiple events on one note,
events spanning measures, numbered overlapping spans, and interaction with
existing suffix markers where applicable.

## Style

- Target Python 3.10 or newer.
- Prefer small standard-library functions and explicit data structures.
- Use `pathlib.Path` for filesystem paths.
- Keep the compact output readable without sacrificing unambiguous parsing.
