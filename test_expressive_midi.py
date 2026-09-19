import json
import unittest
from fractions import Fraction
from unittest.mock import patch
from xml.etree import ElementTree as ET

from concise_musicxml import import_musicxml
from expressive_midi import (
    PerformancePlanError,
    apply_performance_plan,
    generate_performance_plan,
    input_size_diagnostics,
    parse_performance_plan,
    render_expressive_midi,
    serialize_semantic_score_diagnostic,
)
from neutral_midi import SourceEventId


def semantic_score():
    root = ET.fromstring("""<score-partwise version="4.0"><part-list>
      <score-part id="P1"><part-name>Strings</part-name></score-part></part-list>
      <part id="P1">
        <measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
          <direction><sound tempo="100"/></direction>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><notations><slur type="start" number="1"/></notations></note>
        </measure>
        <measure number="2">
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><notations><slur type="stop" number="1"/></notations></note>
        </measure>
      </part></score-partwise>""")
    return import_musicxml(root)


def plan_data():
    return {
        "summary": "Broader second measure",
        "sections": [
            {
                "start_measure": 2,
                "end_measure": 2,
                "tempo_bpm": 80,
                "velocity_delta": 12,
                "duration_scale": 0.75,
                "character": "warm",
            }
        ],
    }


class ExpressiveMidiTests(unittest.TestCase):
    def test_diagnostic_serialization_preserves_the_complete_typed_score_tree(self):
        score = semantic_score()
        payload = json.loads(serialize_semantic_score_diagnostic(score))
        event = payload["parts"][0]["measures"][0]["events"][0]
        self.assertEqual(payload["$type"], "SemanticScore")
        self.assertEqual(event["$type"], "SemanticNoteEvent")
        self.assertEqual(event["provenance"]["note_index"], 1)
        self.assertEqual(event["content"]["$type"], "WrittenPitch")
        self.assertEqual(event["content"]["alter"], {"$type": "Fraction", "numerator": 0, "denominator": 1})
        self.assertEqual(event["slurs"][0]["$type"], "SlurRelation")
        self.assertEqual(set(payload), {"$type", *(item.name for item in __import__('dataclasses').fields(score))})

    def test_plan_changes_only_performed_properties(self):
        score = semantic_score()
        original = score.parts[0].measures[1].events[0]
        plan = parse_performance_plan(plan_data(), 2)
        realized, audit = apply_performance_plan(score, plan)

        self.assertTrue(audit.ok)
        self.assertEqual(realized.notes[0].velocity, 64)
        self.assertEqual(realized.notes[1].velocity, 76)
        self.assertEqual(realized.notes[1].duration, Fraction(3, 4))
        self.assertEqual(realized.notes[1].source_event_ids, [SourceEventId("P1", 2)])
        self.assertEqual([(item.onset, item.bpm) for item in realized.tempos], [(0, 100), (4, 80)])
        self.assertEqual((original.onset, original.duration), (0, 1))

    def test_render_with_supplied_plan_needs_no_llm_or_cmusic(self):
        with patch("concise_music_parser.parse", side_effect=AssertionError("must not parse cmusic")):
            result = render_expressive_midi(
                semantic_score(), parse_performance_plan(plan_data(), 2)
            )
        self.assertEqual(result.data[:4], b"MThd")
        self.assertTrue(result.audit.ok)

    def test_invalid_overlapping_or_out_of_range_plan_is_rejected(self):
        data = plan_data()
        data["sections"].append(dict(data["sections"][0]))
        with self.assertRaisesRegex(PerformancePlanError, "ordered, non-overlapping"):
            parse_performance_plan(data, 2)

    def test_llm_response_is_schema_parsed_and_score_is_sent_directly(self):
        response = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(plan_data())}
        ]}]}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(response).encode()

        captured = {}

        def fake_open(request, timeout):
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_open):
            plan = generate_performance_plan(semantic_score(), "test-model", api_key="test")
        self.assertEqual(plan.sections[0].tempo_bpm, 80)
        prompt = captured["body"]["input"]
        self.assertIn("CMUSIC VIEW OF THE AUTHORITATIVE SEMANTIC SCORE", prompt)
        self.assertIn('score format="concise-music-v2"', prompt)
        self.assertNotIn('"$type":"SemanticScore"', prompt)
        self.assertEqual(captured["body"]["text"]["format"]["type"], "json_schema")

    def test_v1_llm_view_remains_available_as_fallback(self):
        response = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(plan_data())}
        ]}]}

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return json.dumps(response).encode()

        captured = {}
        def fake_open(request, timeout):
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_open):
            generate_performance_plan(
                semantic_score(), "test-model", api_key="test", cmusic_version="v1"
            )
        self.assertIn("@score format=concise-music-v1", captured["body"]["input"])

    def test_cmusic_is_smaller_llm_input_while_diagnostic_dump_remains_available(self):
        sizes = input_size_diagnostics(semantic_score())
        self.assertIsNone(sizes.musicxml_bytes)
        self.assertLess(sizes.cmusic_bytes, sizes.semantic_score_bytes)


if __name__ == "__main__":
    unittest.main()
