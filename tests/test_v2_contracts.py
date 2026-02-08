"""Unit tests for the test v2 contracts module behavior."""

import unittest

from summa_technologica.v2_contracts import (
    ContractValidationError,
    PipelineErrorContract,
    build_partial_failure_payload,
    resolve_v2_schema_path,
    validate_partial_failure_payload,
    validate_v2_payload,
)
from summa_technologica.semantic_scholar import SemanticScholarPaper

try:
    import jsonschema  # noqa: F401

    HAS_JSONSCHEMA = True
except ModuleNotFoundError:
    HAS_JSONSCHEMA = False


def _valid_payload() -> dict:
    """Internal helper to valid payload."""
    return {
        "question": "Can topological ideas improve quantum error correction?",
        "domain": "physics",
        "hypotheses": [
            {
                "id": "h1",
                "title": "Topological syndrome compression",
                "statement": "Map syndrome manifolds onto topological classes.",
                "novelty_rationale": "Connects topological order with syndrome reduction.",
                "plausibility_rationale": "Consistent with stabilizer formulations.",
                "testability_rationale": "Can be tested in simulation in under one year.",
                "falsifiable_predictions": [
                    "Logical error rate scales down at fixed physical noise."
                ],
                "minimal_experiments": [
                    "Run comparative simulator against baseline decoder."
                ],
                "objections": [
                    {"number": 1, "text": "Topology may add computational overhead."},
                    {"number": 2, "text": "Noise model assumptions may be fragile."},
                    {"number": 3, "text": "Benefit may vanish on realistic hardware."},
                ],
                "replies": [
                    {"objection_number": 1, "text": "Compression offsets overhead."},
                    {"objection_number": 2, "text": "Method is robust to perturbations."},
                    {"objection_number": 3, "text": "Hardware-aware priors are included."},
                ],
                "citations": [
                    {
                        "title": "Example paper",
                        "authors": ["Alice Doe", "Bob Roe"],
                        "year": 2021,
                        "paper_id": "abc123"
                    }
                ],
                "pairwise_record": {
                    "comparisons": [
                        {
                            "hypothesis_a_id": "h1",
                            "hypothesis_b_id": "h2",
                            "winner_novelty": "a",
                            "winner_plausibility": "tie",
                            "winner_testability": "a"
                        }
                    ],
                    "wins_by_dimension": {
                        "novelty": 1,
                        "plausibility": 0,
                        "testability": 1
                    }
                },
                "scores": {
                    "novelty": 4.5,
                    "plausibility": 3.5,
                    "testability": 4.0,
                    "overall": 4.05
                }
            },
            {
                "id": "h2",
                "title": "Anyon-informed decoder priors",
                "statement": "Use anyon-braid priors in decoding objective.",
                "novelty_rationale": "Introduces structured prior family.",
                "plausibility_rationale": "Aligned with known anyon toy models.",
                "testability_rationale": "Immediate benchmarking possible.",
                "falsifiable_predictions": [
                    "Performance lift appears only in structured noise regimes."
                ],
                "minimal_experiments": [
                    "Benchmark under multiple synthetic and realistic noise channels."
                ],
                "objections": [
                    {"number": 1, "text": "Prior mismatch can harm generalization."},
                    {"number": 2, "text": "Anyons may not map to implementation details."},
                    {"number": 3, "text": "Training cost could dominate gains."},
                ],
                "replies": [
                    {"objection_number": 1, "text": "Adaptive prior weighting mitigates mismatch."},
                    {"objection_number": 2, "text": "Mapping is limited to syndrome graph features."},
                    {"objection_number": 3, "text": "Inference-time gains can dominate."},
                ],
                "citations": [
                    {
                        "title": "Second example paper",
                        "authors": ["Cara Poe"],
                        "year": 2020,
                        "doi": "10.1000/example"
                    }
                ],
                "pairwise_record": {
                    "comparisons": [
                        {
                            "hypothesis_a_id": "h1",
                            "hypothesis_b_id": "h2",
                            "winner_novelty": "a",
                            "winner_plausibility": "tie",
                            "winner_testability": "a"
                        }
                    ],
                    "wins_by_dimension": {
                        "novelty": 0,
                        "plausibility": 0,
                        "testability": 0
                    }
                },
                "scores": {
                    "novelty": 3.5,
                    "plausibility": 3.5,
                    "testability": 3.0,
                    "overall": 3.35
                }
            }
        ],
        "ranked_hypothesis_ids": ["h1", "h2"],
        "summa_rendering": "Question: ...\nObjections:\n1. ...\n2. ...\n3. ...\nOn the contrary...\n...\nI answer that...\n...\nReplies to objections:\nReply to Objection 1...\nReply to Objection 2...\nReply to Objection 3..."
    }


class PartialFailureContractTests(unittest.TestCase):
    def test_build_partial_failure_payload(self) -> None:
        """Verify that build partial failure payload."""
        payload = build_partial_failure_payload(
            question="Q",
            domain="physics",
            error=PipelineErrorContract(
                stage="ranker",
                message="Failed to parse pairwise comparisons",
                retry_attempted=True,
            ),
            stage_outputs={"problem_framer": {"summary": "ok"}},
            hypotheses=[{"id": "h1"}],
            ranked_hypothesis_ids=[],
            summa_rendering="",
        )
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["stage"], "ranker")

    def test_partial_failure_requires_stage_outputs(self) -> None:
        """Verify that partial failure requires stage outputs."""
        bad_payload = {
            "question": "Q",
            "domain": "physics",
            "hypotheses": [],
            "ranked_hypothesis_ids": [],
            "summa_rendering": "",
            "error": {
                "stage": "critic",
                "message": "oops",
                "retry_attempted": True
            }
        }
        with self.assertRaises(ContractValidationError):
            validate_partial_failure_payload(bad_payload)


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema not installed")
class V2SchemaValidationTests(unittest.TestCase):
    def test_schema_path_exists(self) -> None:
        """Verify that schema path exists."""
        self.assertTrue(resolve_v2_schema_path().exists())

    def test_valid_payload_passes(self) -> None:
        """Verify that valid payload passes."""
        payload = _valid_payload()
        validated = validate_v2_payload(payload)
        self.assertEqual(validated["ranked_hypothesis_ids"][0], "h1")

    def test_ranked_ids_must_match_hypotheses(self) -> None:
        """Verify that ranked ids must match hypotheses."""
        payload = _valid_payload()
        payload["ranked_hypothesis_ids"] = ["h1"]
        with self.assertRaises(ContractValidationError):
            validate_v2_payload(payload)

    def test_citation_requires_paper_id_or_doi(self) -> None:
        """Verify that citation requires paper id or doi."""
        payload = _valid_payload()
        payload["hypotheses"][0]["citations"][0].pop("paper_id")
        with self.assertRaises(ContractValidationError):
            validate_v2_payload(payload)

    def test_overall_formula_is_checked(self) -> None:
        """Verify that overall formula is checked."""
        payload = _valid_payload()
        payload["hypotheses"][0]["scores"]["overall"] = 5.0
        with self.assertRaises(ContractValidationError):
            validate_v2_payload(payload)

    def test_grounded_citations_are_enforced_when_catalog_is_provided(self) -> None:
        """Verify that grounded citations are enforced when catalog is provided."""
        payload = _valid_payload()
        grounded = [
            SemanticScholarPaper(
                paper_id="p9",
                title="Other paper",
                authors=["X"],
                year=2020,
                abstract="",
                citation_count=None,
                doi=None,
                url=None,
                source_query="q",
            )
        ]
        with self.assertRaises(ContractValidationError):
            validate_v2_payload(payload, grounded_papers=grounded)


if __name__ == "__main__":
    unittest.main()
