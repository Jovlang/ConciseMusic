import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from concise_musicxml import convert
from concise_musicxml_gui import plan_outputs


SCORE = """<?xml version="1.0"?>
<score-partwise version="4.0">
 <work><work-title>Tiny</work-title></work>
 <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
 <part id="P1"><measure number="1">
  <attributes><divisions>4</divisions><key><fifths>0</fifths><mode>major</mode></key>
   <time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
  <direction><sound tempo="120"/></direction>
  <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice></note>
  <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><tie type="start"/></note>
  <note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice></note>
  <note><rest/><duration>8</duration><voice>1</voice></note>
 </measure></part>
</score-partwise>"""


class ConverterTests(unittest.TestCase):
    def test_compact_score(self):
        output = convert(ET.fromstring(SCORE))
        self.assertIn('@score format=concise-music-v1 title="Tiny"', output)
        self.assertIn('@part P1 name="Piano"', output)
        self.assertIn('m1 div=4 key=0:major time=4/4 clef1=G2 @0:tempo=120', output)
        self.assertIn('C4/1 [E4{>},G4]/1 r/2', output)

    def test_microtonal_accidental(self):
        score = SCORE.replace(
            "<step>C</step><octave>4</octave>",
            "<step>C</step><alter>0.5</alter><octave>4</octave>",
            1,
        )
        self.assertIn("C(+1/2)4/1", convert(ET.fromstring(score)))

    def test_duplicate_output_names_are_disambiguated(self):
        jobs = plan_outputs(
            [Path("first/song.musicxml"), Path("second/song.mxl")], Path("output")
        )
        self.assertEqual([job[1].name for job in jobs], ["song.cmusic", "song_2.cmusic"])

    def concise_notes(self, measures: str) -> str:
        xml = f"""<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>Test</part-name></score-part></part-list>
          <part id="P1">{measures}</part>
        </score-partwise>"""
        return convert(ET.fromstring(xml))

    def test_simple_slur(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="1"/></notations></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="1"/></notations></note>
        </measure>""")
        self.assertIn("C4{s1>}/1 D4{s1<}/1", output)

    def test_slur_across_barline(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="2"/></notations></note>
        </measure><measure number="2">
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="2"/></notations></note>
        </measure>""")
        self.assertIn("m1 div=1 | C4{s2>}/1\nm2 | D4{s2<}/1", output)

    def test_nested_numbered_slurs(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="1"/></notations></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="2"/></notations></note>
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="2"/></notations></note>
          <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="1"/></notations></note>
        </measure>""")
        self.assertIn("C4{s1>}/1 D4{s2>}/1 E4{s2<}/1 F4{s1<}/1", output)

    def test_overlapping_numbered_slurs(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="1"/></notations></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start" number="2"/></notations></note>
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="1"/></notations></note>
          <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="2"/></notations></note>
        </measure>""")
        self.assertIn("C4{s1>}/1 D4{s2>}/1 E4{s1<}/1 F4{s2<}/1", output)

    def test_tie_and_slur_remain_distinct(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <tie type="start"/><notations><slur type="start" number="3"/></notations></note>
        </measure>""")
        self.assertIn("C4{>,s3>}/1", output)

    def test_multiple_slur_events_on_one_note(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="stop" number="1"/><slur type="start" number="2"/>
              <slur type="start" number="3"/></notations></note>
        </measure>""")
        self.assertIn("C4{s1<,s2>,s3>}/1", output)

    def test_missing_slur_number_defaults_to_one(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slur type="start"/></notations></note>
        </measure>""")
        self.assertIn("C4{s1>}/1", output)


if __name__ == "__main__":
    unittest.main()
