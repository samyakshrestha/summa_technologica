"""Unit tests for the test crew v2 helpers module behavior."""

import unittest

from summa_technologica.crew_v2 import (
    _apply_pairwise_ranking,
    _ensure_summa_rendering,
    _hydrate_summa_triplets,
    _normalize_generated_hypotheses,
    _render_template,
)
from summa_technologica.semantic_scholar import SemanticScholarPaper


class CrewV2HelperTests(unittest.TestCase):
    def test_render_template_preserves_literal_json_braces(self) -> None:
        """Verify that render template preserves literal json braces."""
        template = (
            "Question: {question}\n"
            "Do not output JSON other than {\"summa_rendering\": \"...\"}."
        )
        rendered = _render_template(template, {"question": "Q?"})
        self.assertIn("Question: Q?", rendered)
        self.assertIn("{\"summa_rendering\": \"...\"}", rendered)

    def test_apply_pairwise_ranking(self) -> None:
        """Verify that apply pairwise ranking."""
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

    def test_apply_pairwise_ranking_tie_centers_scores(self) -> None:
        """Verify that apply pairwise ranking tie centers scores."""
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
                    "winner_novelty": "tie",
                    "winner_plausibility": "tie",
                    "winner_testability": "tie",
                }
            ]
        }
        _ranked_ids, updated = _apply_pairwise_ranking(
            hypotheses=hypotheses,
            ranker_output=ranker_output,
        )
        score_h1 = next(item["scores"] for item in updated if item["id"] == "h1")
        score_h2 = next(item["scores"] for item in updated if item["id"] == "h2")
        self.assertAlmostEqual(score_h1["overall"], 3.0, places=3)
        self.assertAlmostEqual(score_h2["overall"], 3.0, places=3)

    def test_normalize_generated_hypotheses_filters_ungrounded_citations(self) -> None:
        """Verify that normalize generated hypotheses filters ungrounded citations."""
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
        self.assertEqual(
            [item["number"] for item in normalized[0]["objections"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [item["objection_number"] for item in normalized[0]["replies"]],
            [1, 2, 3],
        )

    def test_normalize_generated_hypotheses_falls_back_to_grounded_citations(self) -> None:
        """Verify that normalize generated hypotheses falls back to grounded citations."""
        grounded = [
            SemanticScholarPaper(
                paper_id="p1",
                title="Paper One",
                authors=["A1"],
                year=2020,
                abstract="",
                citation_count=10,
                doi=None,
                url=None,
                source_query="q",
            ),
            SemanticScholarPaper(
                paper_id="p2",
                title="Paper Two",
                authors=["A2"],
                year=2021,
                abstract="",
                citation_count=9,
                doi=None,
                url=None,
                source_query="q",
            ),
            SemanticScholarPaper(
                paper_id="p3",
                title="Paper Three",
                authors=["A3"],
                year=2022,
                abstract="",
                citation_count=8,
                doi=None,
                url=None,
                source_query="q",
            ),
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
                    "citations": [],
                }
            ]
        }
        normalized = _normalize_generated_hypotheses(payload, grounded)
        self.assertEqual(len(normalized[0]["citations"]), 3)
        self.assertEqual(
            [item["paper_id"] for item in normalized[0]["citations"]],
            ["p1", "p2", "p3"],
        )

    def test_ensure_summa_rendering_builds_fallback_top3(self) -> None:
        """Verify that ensure summa rendering builds fallback top3."""
        hypotheses = [
            {
                "id": "h1",
                "title": "H1",
                "statement": "Statement 1",
                "objections": [{"number": 1, "text": "o11"}, {"number": 2, "text": "o12"}, {"number": 3, "text": "o13"}],
                "replies": [{"objection_number": 1, "text": "r11"}, {"objection_number": 2, "text": "r12"}, {"objection_number": 3, "text": "r13"}],
            },
            {
                "id": "h2",
                "title": "H2",
                "statement": "Statement 2",
                "objections": [{"number": 1, "text": "o21"}, {"number": 2, "text": "o22"}, {"number": 3, "text": "o23"}],
                "replies": [{"objection_number": 1, "text": "r21"}, {"objection_number": 2, "text": "r22"}, {"objection_number": 3, "text": "r23"}],
            },
            {
                "id": "h3",
                "title": "H3",
                "statement": "Statement 3",
                "objections": [{"number": 1, "text": "o31"}, {"number": 2, "text": "o32"}, {"number": 3, "text": "o33"}],
                "replies": [{"objection_number": 1, "text": "r31"}, {"objection_number": 2, "text": "r32"}, {"objection_number": 3, "text": "r33"}],
            },
        ]
        rendered = _ensure_summa_rendering(
            raw_rendering="invalid",
            question="Q?",
            hypotheses=hypotheses,
            ranked_ids=["h1", "h2", "h3"],
            top=3,
        )
        self.assertIn("Question: Q?", rendered)
        self.assertIn("On the contrary...", rendered)
        self.assertIn("I answer that...", rendered)
        self.assertIn("\n---\n", rendered)
        # rank #1 should use rank #2 as contrary source
        self.assertIn("Statement 2", rendered)

    def test_hydrate_summa_triplets_adds_missing_fields(self) -> None:
        """Verify that hydrate summa triplets adds missing fields."""
        hydrated = _hydrate_summa_triplets(
            [
                {
                    "id": "h1",
                    "title": "H1",
                    "statement": "S1",
                }
            ]
        )
        self.assertEqual(len(hydrated), 1)
        self.assertEqual(
            [item["number"] for item in hydrated[0]["objections"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [item["objection_number"] for item in hydrated[0]["replies"]],
            [1, 2, 3],
        )


if __name__ == "__main__":
    unittest.main()
