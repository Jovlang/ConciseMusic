import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from concise_music_v2 import V2ParseError, parse_v2, render_cmusic_v2
from concise_musicxml import import_musicxml, load_xml


def score(notes: str):
    root = ET.fromstring(f"""<score-partwise version="4.0"><part-list>
      <score-part id="P1"><part-name>Test</part-name></score-part></part-list>
      <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
      {notes}</measure></part></score-partwise>""")
    return import_musicxml(root)


class ConciseMusicV2Tests(unittest.TestCase):
    def test_nested_chord_and_markers_have_distinct_delimiters(self):
        semantic = score("""
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="1"/><slur type="stop" number="2"/></notations></note>
          <note><chord/><pitch><step>E</step><octave>3</octave></pitch><duration>1</duration></note>
        """)
        output = render_cmusic_v2(semantic)
        self.assertIn('chord /1 {', output)
        self.assertIn('E4 {slur-stop=1; slur-stop=2}', output)
        self.assertIn('E3', output)
        self.assertEqual(parse_v2(output).render(), output)

    def test_voice_staff_skip_and_directions_round_trip(self):
        root = ET.fromstring("""<score-partwise version="4.0"><part-list>
          <score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
          <part id="P1"><measure number="1"><attributes><divisions>2</divisions></attributes>
            <direction><sound tempo="90"/></direction><forward><duration>1</duration></forward>
            <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>2</voice><staff>2</staff></note>
          </measure></part></score-partwise>""")
        output = render_cmusic_v2(import_musicxml(root))
        self.assertIn('directions [at 0 value="tempo=90"]', output)
        self.assertIn('v2s2', output)
        self.assertIn('skip/1/2', output)
        self.assertEqual(parse_v2(output).render(), output)

    def test_parser_rejects_unknown_event(self):
        text = 'score format="concise-music-v2" { part P1 { m1 { v1s1 { wat } } } }'
        with self.assertRaisesRegex(V2ParseError, "unknown event"):
            parse_v2(text)

    def test_tie_and_slur_remain_readably_distinct(self):
        semantic = score("""
          <note><tie type="start"/><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="2"/></notations></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
            <notations><tied type="start" number="2"/></notations></note>
        """)
        output = render_cmusic_v2(semantic)
        self.assertIn("playback-tie-start", output)
        self.assertIn("tie-start=2", output)
        self.assertIn("slur-start=2", output)
        self.assertEqual(parse_v2(output).render(), output)

    def test_western_sunrise_round_trip_and_soft_size_target_when_available(self):
        path = Path.home() / "Downloads" / "Western Sunrise v2 - Full score - 01 .musicxml"
        if not path.exists():
            self.skipTest("external Western Sunrise source is unavailable")
        output = render_cmusic_v2(import_musicxml(load_xml(path), path.name))
        self.assertEqual(parse_v2(output).render(), output)
        self.assertLess(len(output.encode("utf-8")), path.stat().st_size * 0.10)


if __name__ == "__main__":
    unittest.main()
