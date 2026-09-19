import unittest
from fractions import Fraction
from pathlib import Path

from concise_music_parser import ParseError, parse, parse_file
from concise_musicxml import convert, load_xml


FIXTURES = Path(__file__).parent / "tests" / "fixtures"


class ConciseMusicParserTests(unittest.TestCase):
    def test_golden_fixture_round_trips_byte_for_byte(self):
        path = FIXTURES / "semantic_golden.cmusic"
        original = path.read_text(encoding="utf-8")
        score = parse_file(path)

        self.assertEqual(score.render(), original)
        self.assertEqual(score.format, "concise-music-v1")
        self.assertEqual(len(score.parts), 1)

    def test_converter_output_is_accepted_without_normalization(self):
        output = convert(load_xml(FIXTURES / "semantic_golden.musicxml"))
        self.assertEqual(parse(output).render(), output)

    def test_western_sunrise_round_trips_when_full_score_artifact_is_available(self):
        path = Path(__file__).parent / "Western Sunrise v2 - Full score - 01.cmusic"
        if not path.exists():
            self.skipTest("external Western Sunrise cmusic artifact is not available")
        original = path.read_text(encoding="utf-8")
        score = parse(original)

        self.assertEqual(score.render(), original)
        self.assertEqual(len(score.parts), 3)
        self.assertEqual(sum(len(part.measures) for part in score.parts), 306)

    def test_structured_access_to_measures_voices_notes_and_directions(self):
        document = """@score format=concise-music-v1 title=\"Parser test\"
@part P1 name=\"Piano\"
m1 div=4 key=0 @1/2:text=\"a tempo\" | v1: C4{s1>,art=accent}/1/2 [E4,G4{s1<}]@I2{arp1^}/1 ; v2s2: _1/2 r/1/2
"""
        score = parse(document)
        measure = score.parts[0].measures[0]

        self.assertEqual(measure.number, "1")
        self.assertEqual(measure.attributes, ("div=4", "key=0"))
        self.assertEqual(measure.directions[0].offset, Fraction(1, 2))
        self.assertEqual(measure.directions[0].value, 'text="a tempo"')
        self.assertEqual([voice.identifier for voice in measure.voices], ["1", "2s2"])
        self.assertEqual(measure.voices[0].events[0].notes[0].symbol, "C4")
        chord = measure.voices[0].events[1]
        self.assertTrue(chord.is_chord)
        self.assertEqual([note.symbol for note in chord.notes], ["E4", "G4"])
        self.assertEqual(chord.common_instrument, "I2")
        self.assertEqual(chord.common_markers[0].markers, ("arp1^",))
        self.assertEqual(score.render(), document)

    def test_quotes_and_microtonal_fractions_do_not_confuse_delimiters(self):
        document = """@score format=concise-music-v1
@part P1
m1 | C(+1/2)4{ly1=\"a/b,{c}; x\",tech=other:\"tap, then lift\"}/1/2
"""
        score = parse(document)
        event = score.parts[0].measures[0].voices[0].events[0]

        self.assertEqual(event.duration, Fraction(1, 2))
        self.assertEqual(event.notes[0].symbol, "C(+1/2)4")
        self.assertEqual(
            event.notes[0].marker_groups[0].markers,
            ('ly1="a/b,{c}; x"', 'tech=other:"tap, then lift"'),
        )
        self.assertEqual(score.render(), document)

    def test_marker_commas_are_not_chord_separators(self):
        document = """@score format=concise-music-v1
@part P1
m1 | [E4{s1<,s2<},E3]/1
"""
        score = parse(document)
        chord = score.parts[0].measures[0].voices[0].events[0]

        self.assertEqual([note.symbol for note in chord.notes], ["E4", "E3"])
        self.assertEqual(chord.notes[0].marker_groups[0].markers, ("s1<", "s2<"))
        self.assertEqual(score.render(), document)

    def test_empty_measure_and_empty_voice_are_valid(self):
        document = """@score format=concise-music-v1
@part P1
m1 |
m2 | v1: 
"""
        score = parse(document)

        self.assertEqual(score.parts[0].measures[0].voices, ())
        self.assertEqual(score.parts[0].measures[1].voices[0].events, ())
        self.assertEqual(score.render(), document)

    def test_instrument_definitions_and_unknown_fallbacks_round_trip(self):
        document = """@score format=concise-music-v1
@part P1 name=\"Percussion\"
@instrument I1 id=\"P1-I1\" name=\"Snare Drum\" sound=\"drum.snare-drum\"
m1 | x@I1/1 x?(D5)/1 x?/1 C4@?/1
"""
        score = parse(document)

        self.assertEqual(score.parts[0].instruments[0].alias, "I1")
        symbols = [event.notes[0].symbol for event in score.parts[0].measures[0].voices[0].events]
        self.assertEqual(symbols, ["x", "x?(D5)", "x?", "C4"])
        self.assertEqual(score.render(), document)

    def test_rejects_invalid_documents_with_line_numbers(self):
        invalid_documents = (
            "@score format=concise-music-v2\n",
            "@score format=concise-music-v1\nm1 | C4/1\n",
            "@score format=concise-music-v1\n@part P1\nm1 | C4\n",
            "@score format=concise-music-v1\n@part P1\nm1 | [C4,E4/1\n",
            "@score format=concise-music-v1\n@part P1\nm1 | v1: C4/1 ; r/1\n",
            '@score format=concise-music-v1 title="unfinished\n',
        )
        for document in invalid_documents:
            with self.subTest(document=document), self.assertRaises(ParseError) as context:
                parse(document)
            self.assertGreaterEqual(context.exception.line, 1)


if __name__ == "__main__":
    unittest.main()
