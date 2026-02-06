import unittest

from summa_technologica.models import parse_summa_json


class ParseSummaJsonTests(unittest.TestCase):
    def test_parses_valid_payload(self) -> None:
        payload = """
        {
          "question": "Is symmetry foundational in physics?",
          "objections": [
            {"number": 1, "text": "Objection one."},
            {"number": 2, "text": "Objection two."},
            {"number": 3, "text": "Objection three."}
          ],
          "on_the_contrary": "A unifying principle points the other way.",
          "i_answer_that": "Symmetry is foundational but not exhaustive.",
          "replies": [
            {"objection_number": 1, "text": "Reply one."},
            {"objection_number": 2, "text": "Reply two."},
            {"objection_number": 3, "text": "Reply three."}
          ]
        }
        """
        result = parse_summa_json(payload)
        self.assertEqual(result.question, "Is symmetry foundational in physics?")
        self.assertEqual(len(result.objections), 3)
        self.assertEqual(len(result.replies), 3)

    def test_rejects_wrong_objection_numbers(self) -> None:
        payload = """
        {
          "question": "Q",
          "objections": [
            {"number": 1, "text": "A"},
            {"number": 2, "text": "B"},
            {"number": 4, "text": "C"}
          ],
          "on_the_contrary": "X",
          "i_answer_that": "Y",
          "replies": [
            {"objection_number": 1, "text": "R1"},
            {"objection_number": 2, "text": "R2"},
            {"objection_number": 3, "text": "R3"}
          ]
        }
        """
        with self.assertRaises(ValueError):
            parse_summa_json(payload)

    def test_rejects_missing_json(self) -> None:
        with self.assertRaises(ValueError):
            parse_summa_json("not json")


if __name__ == "__main__":
    unittest.main()

