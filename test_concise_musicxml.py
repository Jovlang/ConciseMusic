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

    def percussion_score(self, definitions: str, notes: str) -> str:
        xml = f"""<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>Percussion</part-name>{definitions}</score-part></part-list>
          <part id="P1"><measure number="1"><attributes><divisions>4</divisions></attributes>{notes}</measure></part>
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

    def test_whole_measure_rest_discards_display_position(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
          <note><rest measure="yes"><display-step>D</display-step><display-octave>5</display-octave></rest>
            <duration>16</duration><voice>1</voice></note>
        </measure>""")
        self.assertIn("| r/4", output)
        self.assertNotIn("r@", output)

    def test_ordinary_rest_discards_display_position(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>4</divisions></attributes>
          <note><rest><display-step>B</display-step><display-octave>4</display-octave></rest>
            <duration>2</duration><voice>1</voice></note>
        </measure>""")
        self.assertIn("| r/1/2", output)
        self.assertNotIn("B4", output)

    def test_rest_duration_voice_and_staff_survive(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>4</divisions><staves>2</staves></attributes>
          <note><rest><display-step>F</display-step><display-octave>3</display-octave></rest>
            <duration>8</duration><voice>7</voice><staff>2</staff></note>
        </measure>""")
        self.assertIn("| v7s2: r/2", output)

    def test_note_pitch_is_unaffected_by_rest_display_fix(self):
        output = self.concise_notes("""<measure number="1">
          <attributes><divisions>4</divisions></attributes>
          <note><pitch><step>D</step><alter>1</alter><octave>5</octave></pitch>
            <duration>4</duration><voice>1</voice></note>
        </measure>""")
        self.assertIn("| D#5/1", output)

    def test_two_staff_piano_rest_measure_stays_structurally_distinct(self):
        output = self.concise_notes("""<measure number="2">
          <attributes><divisions>4</divisions><staves>2</staves></attributes>
          <note><rest measure="yes"><display-step>D</display-step><display-octave>5</display-octave></rest>
            <duration>16</duration><voice>1</voice><staff>1</staff></note>
          <backup><duration>16</duration></backup>
          <note><rest measure="yes"><display-step>F</display-step><display-octave>3</display-octave></rest>
            <duration>16</duration><voice>2</voice><staff>2</staff></note>
        </measure>""")
        self.assertIn("| v1: r/4 ; v2s2: r/4", output)
        self.assertNotIn("r@", output)

    def test_unpitched_note_uses_instrument_id_and_definition(self):
        output = self.percussion_score(
            """<score-instrument id="P1-I1"><instrument-name>Snare Drum</instrument-name>
              <instrument-sound>drum.snare-drum</instrument-sound></score-instrument>""",
            """<note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched>
              <instrument id="P1-I1"/><duration>4</duration></note>""",
        )
        self.assertIn('@instrument I1 id="P1-I1" name="Snare Drum" sound="drum.snare-drum"', output)
        self.assertIn("| x@I1/1", output)
        self.assertNotIn("xD5", output)

    def test_different_instruments_at_different_positions_remain_distinct(self):
        output = self.percussion_score(
            """<score-instrument id="P1-I1"><instrument-name>Snare</instrument-name></score-instrument>
              <score-instrument id="P1-I2"><instrument-name>Hi-Hat</instrument-name></score-instrument>""",
            """<note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched>
                <instrument id="P1-I1"/><duration>4</duration></note>
              <note><unpitched><display-step>G</display-step><display-octave>5</display-octave></unpitched>
                <instrument id="P1-I2"/><duration>2</duration></note>""",
        )
        self.assertIn("x@I1/1 x@I2/1/2", output)
        self.assertNotIn("D5", output)
        self.assertNotIn("G5", output)

    def test_different_instruments_at_same_position_remain_distinct(self):
        output = self.percussion_score(
            """<score-instrument id="P1-I1"><instrument-name>Side Stick</instrument-name></score-instrument>
              <score-instrument id="P1-I2"><instrument-name>Snare</instrument-name></score-instrument>""",
            """<note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>
                <instrument id="P1-I1"/><duration>4</duration></note>
              <note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>
                <instrument id="P1-I2"/><duration>4</duration></note>""",
        )
        self.assertIn("x@I1/1 x@I2/1", output)
        self.assertNotIn("C5", output)

    def test_same_instrument_at_different_positions_has_same_identity(self):
        output = self.percussion_score(
            "<score-instrument id=\"P1-I9\"><instrument-name>Tom</instrument-name></score-instrument>",
            """<note><unpitched><display-step>E</display-step><display-octave>4</display-octave></unpitched>
                <instrument id="P1-I9"/><duration>4</duration></note>
              <note><unpitched><display-step>A</display-step><display-octave>5</display-octave></unpitched>
                <instrument id="P1-I9"/><duration>4</duration></note>""",
        )
        self.assertIn("x@I1/1 x@I1/1", output)
        self.assertNotIn("E4", output)
        self.assertNotIn("A5", output)

    def test_unpitched_note_without_instrument_uses_explicit_fallback(self):
        output = self.percussion_score(
            "",
            """<note><unpitched><display-step>F</display-step><display-octave>4</display-octave></unpitched>
              <duration>4</duration></note>
              <note><unpitched/><duration>2</duration></note>""",
        )
        self.assertIn("x?(F4)/1 x?/1/2", output)
        self.assertNotIn("xF4", output)

    def test_referenced_but_undefined_instrument_retains_xml_identity(self):
        output = self.percussion_score(
            "",
            """<note><unpitched><display-step>B</display-step><display-octave>4</display-octave></unpitched>
              <instrument id="missing-definition"/><duration>4</duration></note>""",
        )
        self.assertIn('@instrument I1 id="missing-definition"', output)
        self.assertIn("| x@I1/1", output)
        self.assertNotIn("B4", output)

    def test_pitched_percussion_is_unaffected(self):
        output = self.percussion_score(
            "<score-instrument id=\"P1-I1\"><instrument-name>Timpani</instrument-name></score-instrument>",
            """<note><pitch><step>F</step><octave>3</octave></pitch>
              <instrument id="P1-I1"/><duration>4</duration></note>""",
        )
        self.assertIn("| F3/1", output)
        self.assertNotIn("x@I1/1", output)

    def test_percussion_change_does_not_affect_rests(self):
        output = self.percussion_score(
            "<score-instrument id=\"P1-I1\"><instrument-name>Snare</instrument-name></score-instrument>",
            """<note><rest><display-step>D</display-step><display-octave>5</display-octave></rest>
              <instrument id="P1-I1"/><duration>4</duration></note>""",
        )
        self.assertIn("| r/1", output)
        self.assertNotIn("r@", output)
        self.assertNotIn("D5", output)


if __name__ == "__main__":
    unittest.main()
