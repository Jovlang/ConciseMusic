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

    def test_multiple_notations_blocks_are_all_preserved(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><articulations><accent/></articulations></notations>
            <notations><slur type="start" number="4"/><technical><open-string/></technical></notations>
          </note></measure>""")
        self.assertIn("C4{s4>,art=accent,tech=open-string}/1", output)

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
        self.assertIn('@instrument I1 id="P1-I1" name="Timpani"', output)
        self.assertNotIn("F3@I1", output)

    def test_percussion_change_does_not_affect_rests(self):
        output = self.percussion_score(
            "<score-instrument id=\"P1-I1\"><instrument-name>Snare</instrument-name></score-instrument>",
            """<note><rest><display-step>D</display-step><display-octave>5</display-octave></rest>
              <instrument id="P1-I1"/><duration>4</duration></note>""",
        )
        self.assertIn("| r/1", output)
        self.assertNotIn("r@", output)
        self.assertNotIn("D5", output)

    def test_instrument_aliases_follow_definition_order_not_note_order(self):
        output = self.percussion_score(
            """<score-instrument id="second-played"><instrument-name>First definition</instrument-name></score-instrument>
              <score-instrument id="first-played"><instrument-name>Second definition</instrument-name></score-instrument>""",
            """<note><unpitched/><instrument id="first-played"/><duration>4</duration></note>
              <note><unpitched/><instrument id="second-played"/><duration>4</duration></note>""",
        )
        self.assertIn('@instrument I1 id="second-played"', output)
        self.assertIn('@instrument I2 id="first-played"', output)
        self.assertIn("| x@I2/1 x@I1/1", output)

    def test_unused_instrument_definitions_are_not_emitted(self):
        output = self.percussion_score(
            """<score-instrument id="used"><instrument-name>Used</instrument-name></score-instrument>
              <score-instrument id="unused"><instrument-name>Unused</instrument-name></score-instrument>""",
            '<note><unpitched/><instrument id="used"/><duration>4</duration></note>',
        )
        self.assertIn('@instrument I1 id="used" name="Used"', output)
        self.assertNotIn('id="unused"', output)

    def test_unpitched_chord_preserves_each_instrument_identity(self):
        output = self.percussion_score(
            """<score-instrument id="kick"><instrument-name>Kick</instrument-name></score-instrument>
              <score-instrument id="crash"><instrument-name>Crash</instrument-name></score-instrument>""",
            """<note><unpitched/><instrument id="kick"/><duration>4</duration></note>
              <note><chord/><unpitched/><instrument id="crash"/><duration>4</duration></note>""",
        )
        self.assertIn("| [x@I1,x@I2]/1", output)

    def test_blank_instrument_reference_uses_unknown_fallback(self):
        output = self.percussion_score(
            "",
            """<note><unpitched><display-step>A</display-step><display-octave>4</display-octave></unpitched>
              <instrument id="   "/><duration>4</duration></note>""",
        )
        self.assertIn("| x?(A4)/1", output)
        self.assertNotIn("@instrument", output)

    def test_namespaced_musicxml_uses_semantic_instrument(self):
        xml = """<score-partwise xmlns="http://www.musicxml.org/ns/musicxml" version="4.0">
          <part-list><score-part id="P1"><part-name>Percussion</part-name>
            <score-instrument id="P1-I1"><instrument-name>Tambourine</instrument-name>
              <instrument-sound>drum.tambourine</instrument-sound></score-instrument>
          </score-part></part-list>
          <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
            <note><unpitched><display-step>E</display-step><display-octave>5</display-octave></unpitched>
              <instrument id="P1-I1"/><duration>1</duration></note>
          </measure></part>
        </score-partwise>"""
        output = convert(ET.fromstring(xml))
        self.assertIn('@instrument I1 id="P1-I1" name="Tambourine" sound="drum.tambourine"', output)
        self.assertIn("| x@I1/1", output)
        self.assertNotIn("E5", output)

    def test_instrument_aliases_are_scoped_per_part(self):
        xml = """<score-partwise version="4.0"><part-list>
          <score-part id="P1"><part-name>One</part-name><score-instrument id="shared"><instrument-name>Snare</instrument-name></score-instrument></score-part>
          <score-part id="P2"><part-name>Two</part-name><score-instrument id="shared"><instrument-name>Clap</instrument-name></score-instrument></score-part>
          </part-list>
          <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
            <note><unpitched/><instrument id="shared"/><duration>1</duration></note></measure></part>
          <part id="P2"><measure number="1"><attributes><divisions>1</divisions></attributes>
            <note><unpitched/><instrument id="shared"/><duration>1</duration></note></measure></part>
        </score-partwise>"""
        output = convert(ET.fromstring(xml))
        self.assertIn('@part P1 name="One"\n@instrument I1 id="shared" name="Snare"', output)
        self.assertIn('@part P2 name="Two"\n@instrument I1 id="shared" name="Clap"', output)
        self.assertEqual(output.count("| x@I1/1"), 2)

    def test_articulations_are_preserved_without_placement(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><articulations><staccato placement="above"/><accent default-x="4"/>
              <other-articulation>heel click</other-articulation></articulations></notations></note>
        </measure>""")
        self.assertIn('C4{art=staccato+accent+other-articulation:"heel click"}/1', output)
        self.assertNotIn("above", output)
        self.assertNotIn("default-x", output)

    def test_fermatas_preserve_shape_not_engraving_position(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
            <notations><fermata type="inverted" placement="below">angled</fermata></notations></note>
        </measure>""")
        self.assertIn("D4{fer=angled}/1", output)
        self.assertNotIn("inverted", output)
        self.assertNotIn("below", output)

    def test_ornaments_tremolo_and_wavy_line_are_preserved(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><notations><ornaments>
            <trill-mark placement="above"/><wavy-line type="start" number="2" default-y="9"/>
            <tremolo type="single">3</tremolo><accidental-mark>sharp</accidental-mark>
          </ornaments></notations></note>
          <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><notations><ornaments>
            <wavy-line type="stop" number="2"/></ornaments></notations></note>
        </measure>""")
        self.assertIn("E4{orn=trill-mark+wav2>+trem:single:3+acc:sharp}/1", output)
        self.assertIn("F4{orn=wav2<}/1", output)
        self.assertNotIn("default-y", output)

    def test_pedal_and_octave_shift_directions_preserve_numbered_events(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <direction placement="below"><direction-type><pedal type="start" number="2" line="yes"/>
            <octave-shift type="down" size="8" number="3" default-x="2"/></direction-type></direction>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
          <direction><direction-type><pedal type="change" number="2"/>
            <octave-shift type="stop" size="8" number="3"/></direction-type></direction>
        </measure>""")
        self.assertIn("@0:ped2=start @0:oct3=down:8", output)
        self.assertIn("@1:ped2=change @1:oct3=stop:8", output)
        self.assertNotIn("placement", output)
        self.assertNotIn("line=yes", output)

    def test_same_offset_direction_order_is_preserved(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <direction><direction-type><pedal type="stop" number="1"/></direction-type></direction>
          <direction><direction-type><pedal type="start" number="1"/></direction-type></direction>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure>""")
        self.assertIn("@0:ped1=stop @0:ped1=start", output)

    def test_tuplet_ratio_and_numbered_span_are_preserved(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>6</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration>
            <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes>
              <normal-type>eighth</normal-type><normal-dot/></time-modification>
            <notations><tuplet type="start" number="2" bracket="yes"/></notations></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration>
            <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification></note>
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration>
            <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>
            <notations><tuplet type="stop" number="2"/></notations></note>
        </measure>""")
        self.assertIn("C4{tup2>,tm=3:2:eighth.}/1/3", output)
        self.assertIn("D4{tm=3:2}/1/3", output)
        self.assertIn("E4{tup2<,tm=3:2}/1/3", output)
        self.assertNotIn("bracket", output)

    def test_sequential_grace_notes_are_not_rendered_as_a_chord(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><grace slash="yes" steal-time-following="20"/><pitch><step>D</step><octave>4</octave></pitch></note>
          <note><grace make-time="10"/><pitch><step>E</step><octave>4</octave></pitch></note>
          <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure>""")
        self.assertIn("D4{g,gslash,gnext=20}/0 E4{g,gmake=10}/0 F4/1", output)
        self.assertNotIn("[D4", output)

    def test_grace_chord_remains_a_chord(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><grace/><pitch><step>C</step><octave>4</octave></pitch></note>
          <note><chord/><grace/><pitch><step>E</step><octave>4</octave></pitch></note>
          <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure>""")
        self.assertIn("[C4{g},E4{g}]/0 G4/1", output)

    def test_technical_indications_are_semantic_and_composable(self):
        with_technical = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><notations><technical>
            <fingering placement="above" font-size="10">2</fingering><string>3</string><fret>5</fret>
            <harmonic><natural/><touching-pitch/></harmonic><down-bow default-x="4"/>
            <other-technical color="#000000">sul pont.</other-technical>
          </technical></notations></note></measure>""")
        without_technical = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note></measure>""")
        self.assertIn(
            'E4{tech=fingering:2+string:3+fret:5+harmonic:natural+touching+down-bow+other-technical:"sul pont."}/1',
            with_technical,
        )
        self.assertNotEqual(with_technical, without_technical)
        self.assertNotIn("placement", with_technical)
        self.assertNotIn("font-size", with_technical)

    def test_technical_layout_variants_normalize(self):
        first = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><technical><fingering placement="above" default-x="1">1</fingering></technical></notations></note></measure>""")
        second = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><technical><fingering placement="below" default-x="99">1</fingering></technical></notations></note></measure>""")
        self.assertEqual(first, second)

    def test_nested_technical_semantics_do_not_collapse(self):
        first = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations><technical>
            <fingering alternate="yes" substitution="yes">2</fingering>
            <bend><bend-alter>1.5</bend-alter><release offset="2"/></bend>
            <hole><hole-closed location="right">half</hole-closed><hole-shape>round</hole-shape></hole>
          </technical></notations></note></measure>""")
        second = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations><technical>
            <fingering>2</fingering><bend><bend-alter>1</bend-alter></bend>
          </technical></notations></note></measure>""")
        self.assertIn("fingering:2(alt;sub)", first)
        self.assertIn("bend:alter=1.5+release@2", first)
        self.assertIn("hole:hole-closed=half@right+hole-shape=round", first)
        self.assertNotEqual(first, second)

    def test_glissando_and_slide_are_distinct_semantics(self):
        gliss = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><glissando type="start" number="1" line-type="wavy">white keys</glissando></notations></note>
          <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration>
            <notations><glissando type="stop" number="1">white keys</glissando></notations></note></measure>""")
        slide = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slide type="start" number="1" accelerate="yes" beats="3" first-beat="20">port.</slide></notations></note>
          <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slide type="stop" number="1">port.</slide></notations></note></measure>""")
        plain = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
          <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration></note></measure>""")
        self.assertIn('C4{gl1>:"white keys"}/1', gliss)
        self.assertIn('G4{gl1<:"white keys"}/1', gliss)
        self.assertIn('C4{slide1>:"port."(accel=yes;beats=3;first=20)}/1', slide)
        self.assertNotEqual(gliss, slide)
        self.assertNotEqual(gliss, plain)
        self.assertNotEqual(slide, plain)

    def test_overlapping_and_cross_measure_glissandi_with_slur(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations>
            <slur type="start" number="3"/><glissando type="start" number="1"/></notations></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><notations>
            <glissando type="start" number="2"/></notations></note></measure>
          <measure number="2"><note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><notations>
            <glissando type="stop" number="1"/></notations></note>
          <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><notations>
            <slur type="stop" number="3"/><glissando type="stop" number="2"/></notations></note></measure>""")
        self.assertIn("C4{s3>,gl1>}/1 D4{gl2>}/1", output)
        self.assertIn("m2 | E4{gl1<}/1 F4{s3<,gl2<}/1", output)

    def test_glissando_layout_variants_normalize(self):
        template = """<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><glissando type="start" number="1" {attrs}/></notations></note></measure>"""
        first = self.concise_notes(template.format(attrs='line-type="solid" default-x="1"'))
        second = self.concise_notes(template.format(attrs='line-type="dashed" default-x="9"'))
        self.assertEqual(first, second)

    def test_slide_layout_variants_normalize(self):
        template = """<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><slide type="start" number="1" accelerate="yes" beats="2" {attrs}/></notations></note></measure>"""
        first = self.concise_notes(template.format(attrs='line-type="solid" default-y="1"'))
        second = self.concise_notes(template.format(attrs='line-type="dotted" default-y="99"'))
        self.assertEqual(first, second)

    def test_arpeggiation_is_normalized_at_chord_level(self):
        arpeggiated = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><arpeggiate number="2" direction="up" placement="left"/></notations></note>
          <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration>
            <notations><arpeggiate number="2" direction="up"/></notations></note>
          <note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration>
            <notations><arpeggiate number="2"/></notations></note></measure>""")
        plain = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
          <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
          <note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration></note></measure>""")
        self.assertIn("[C4,E4,G4]{arp2^}/1", arpeggiated)
        self.assertEqual(arpeggiated.count("arp2"), 1)
        self.assertNotEqual(arpeggiated, plain)

    def test_non_arpeggiation_is_distinct_and_normalized(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><non-arpeggiate number="1" type="bottom" default-x="1"/></notations></note>
          <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration>
            <notations><non-arpeggiate number="1" type="top" default-x="2"/></notations></note></measure>""")
        self.assertIn("[C4,E4]{noarp1}/1", output)
        self.assertEqual(output.count("noarp1"), 1)
        self.assertNotIn("bottom", output)
        self.assertNotIn("top", output)

    def test_arpeggiation_layout_variants_normalize(self):
        template = """<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><arpeggiate number="1" direction="down" {attrs}/></notations></note></measure>"""
        first = self.concise_notes(template.format(attrs='placement="left" default-x="1"'))
        second = self.concise_notes(template.format(attrs='placement="right" default-x="99"'))
        self.assertEqual(first, second)

    def test_conflicting_arpeggiation_directions_remain_visible(self):
        output = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><arpeggiate number="1" direction="up"/></notations></note>
          <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration>
            <notations><arpeggiate number="1" direction="down"/></notations></note></measure>""")
        self.assertIn("[C4,E4]{arp1^,arp1v}/1", output)

    def pitched_switch_score(self, notes: str, definitions: str | None = None) -> str:
        definitions = definitions or """<score-instrument id="P1-I1"><instrument-name>Flute</instrument-name></score-instrument>
          <score-instrument id="P1-I2"><instrument-name>Piccolo</instrument-name></score-instrument>"""
        xml = f"""<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Player</part-name>
          {definitions}</score-part></part-list><part id="P1">{notes}</part></score-partwise>"""
        return convert(ET.fromstring(xml))

    def test_single_instrument_pitched_part_stays_compact(self):
        output = self.pitched_switch_score(
            """<measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
              <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note></measure>""",
            '<score-instrument id="solo"><instrument-name>Flute</instrument-name></score-instrument>',
        )
        self.assertIn('@instrument I1 id="solo" name="Flute"', output)
        self.assertIn("| C4/1 D4/1", output)
        self.assertNotIn("C4@", output)

    def test_pitched_instrument_switch_and_switch_back_are_stateful(self):
        output = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note>
          <note><pitch><step>E</step><octave>4</octave></pitch><instrument id="P1-I2"/><duration>1</duration></note>
          <note><pitch><step>F</step><octave>4</octave></pitch><instrument id="P1-I2"/><duration>1</duration></note></measure>
          <measure number="2"><note><pitch><step>G</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note></measure>""")
        self.assertIn("| C4@I1/1 D4/1 E4@I2/1 F4/1", output)
        self.assertIn("m2 | G4@I1/1", output)

    def test_simultaneous_voices_track_instruments_independently(self):
        output = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration><voice>1</voice></note>
          <backup><duration>1</duration></backup>
          <note><pitch><step>E</step><octave>4</octave></pitch><instrument id="P1-I2"/><duration>1</duration><voice>2</voice></note></measure>""")
        self.assertIn("| v1: C4@I1/1 ; v2: E4@I2/1", output)

    def test_pitched_and_unpitched_share_instrument_mapping(self):
        output = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note>
          <note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched>
            <instrument id="P1-I2"/><duration>1</duration></note></measure>""")
        self.assertIn("| C4@I1/1 x@I2/1", output)
        self.assertNotIn("D5", output)

    def test_undefined_pitched_instrument_reference_is_explicit(self):
        output = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><instrument id="undefined"/><duration>1</duration></note></measure>""")
        self.assertIn('@instrument I2 id="undefined"', output)
        self.assertIn("| C4@I1/1 D4@I2/1", output)

    def test_instrument_switch_is_a_semantic_collision_boundary(self):
        switched = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><instrument id="P1-I2"/><duration>1</duration></note></measure>""")
        unswitched = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note></measure>""")
        self.assertNotEqual(switched, unswitched)

    def test_instrument_switch_layout_variants_normalize(self):
        first = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note default-x="1"><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I2"/><duration>1</duration></note></measure>""")
        second = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note default-x="99" relative-y="8"><pitch><step>C</step><octave>4</octave></pitch><instrument id="P1-I2"/><duration>1</duration></note></measure>""")
        self.assertEqual(first, second)

    def test_missing_reference_in_multi_instrument_part_is_explicit_unknown(self):
        output = self.pitched_switch_score("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><instrument id="P1-I1"/><duration>1</duration></note></measure>""")
        self.assertIn("| C4@?/1 D4@I1/1", output)

    def test_advanced_trill_realization_is_preserved(self):
        explicit = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations><ornaments>
            <trill-mark start-note="upper" trill-step="half" two-note-turn="whole"
              accelerate="yes" beats="4" second-beat="25" last-beat="75" placement="above"/>
          </ornaments></notations></note></measure>""")
        default = self.concise_notes("""<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations><ornaments>
            <trill-mark/></ornaments></notations></note></measure>""")
        self.assertIn(
            "orn=trill-mark(start=upper;step=half;turn=whole;accel=yes;beats=4;second=25;last=75)",
            explicit,
        )
        self.assertNotEqual(explicit, default)
        self.assertNotIn("placement", explicit)

    def test_trill_layout_variants_normalize(self):
        template = """<measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations><ornaments>
            <trill-mark start-note="main" trill-step="whole" {attrs}/>
          </ornaments></notations></note></measure>"""
        first = self.concise_notes(template.format(attrs='placement="above" default-x="1" color="#111111"'))
        second = self.concise_notes(template.format(attrs='placement="below" default-x="99" color="#ffffff"'))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
