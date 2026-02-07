import unittest

from summa_technologica.crew_v2 import (
    _apply_pairwise_ranking,
    _normalize_generated_hypotheses,
)
from summa_technologica.semantic_scholar import SemanticScholarPaper


class CrewV2HelperTests(unittest.TestCase):
    def test_apply_pairwise_ranking(self) -> None:
        hypotheses = [
            {
                "id": "h1",
                "title": "H1",
                "statement": "S1",
                "novelty_rationale": "n1",
                "plausibility_rationale": "p1",
                "testability_rationale": "t1",
                "falsifiable_predictions": ["x"],
                "minimal_experiments": ["e"],
                "citations": [],
                "objections": [{"number": 1, "text": "o1"}, {"number": 2, "text": "o2"}, {"number": 3, "text": "o3"}],
                "replies": [{"objection_number": 1, "text": "r1"}, {"objection_number": 2, "text": "r2"}, {"objection_number": 3, "text": "r3"}],
            },
            {
                "id": "h2",
                "title": "H2",
                "statement": "S2",
                "novelty_rationale": "n2",
                "plausibility_rationale": "p2",
                "testability_rationale": "t2",
                "falsifiable_predictions": ["x"],
                "minimal_experiments": ["e"],
                "citations": [],
                "objections": [{"number": 1, "text": "o1"}, {"number": 2, "text": "o2"}, {"number": 3, "text": "o3"}],
                "replies": [{"objection_number": 1, "text": "r1"}, {"objection_number": 2, "text": "r2"}, {"objection_number": 3, "text": "r3"}],
            },
        ]
        ranker_output = {
            "comparisons": [
                {
                    "hypothesis_a_id": "h1",
                    "hypothesis_b_id": "h2",
                    "winner_novelty": "a",
                    "winner_plausibility": "a",
                    "winner_testability": "b",
                }
            ]
        }
        ranked_ids, updated = _apply_pairwise_ranking(
            hypotheses=hypotheses,
            ranker_output=ranker_output,
        )
        self.assertEqual(set(ranked_ids), {"h1", "h2"})
        self.assertEqual(len(updated), 2)
        for item in updated:
            self.assertIn("scores", item)
            self.assertIn("pairwise_record", item)

    def test_normalize_generated_hypotheses_filters_ungrounded_citations(self) -> None:
        grounded = [
            SemanticScholarPaper(
                paper_id="p1",
                title="T",
                authors=["A"],
                year=2022,
                abstract="",
                citation_count=1,
                doi="10.1000/x",
                url=None,
                source_query="q",
            )
        ]
        payload = {
            "hypotheses": [
                {
                    "id": "h1",
                    "title": "title",
                    "statement": "statement",
                    "novelty_rationale": "n",
                    "plausibility_rationale": "p",
                    "testability_rationale": "t",
                    "falsifiable_predictions": ["f"],
                    "minimal_experiments": ["m"],
                    "citations": [
                        {
                            "title": "good",
                            "authors": ["A"],
                            "year": 2022,
                            "paper_id": "p1",
                        },
                        {
                            "title": "bad",
                            "authors": ["B"],
                            "year": 2022,
                            "paper_id": "p9",
                        },
                    ],
                }
            ]
        }
        normalized = _normalize_generated_hypotheses(payload, grounded)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(len(normalized[0]["citations"]), 1)
        self.assertEqual(normalized[0]["citations"][0]["paper_id"], "p1")


if __name__ == "__main__":
    unittest.main()

