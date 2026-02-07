import unittest

from summa_technologica.eval_compare import (
    evaluate_go_no_go,
    evaluate_v2_metrics,
    is_summa_complete_text,
    summarize_mode,
)


class EvalCompareHelperTests(unittest.TestCase):
    def test_summa_complete_text(self) -> None:
        text = (
            "Question: Q\n\n"
            "Objections:\n1. A\n2. B\n3. C\n\n"
            "On the contrary...\nX\n\n"
            "I answer that...\nY\n\n"
            "Replies to objections:\n"
            "Reply to Objection 1. r1\n"
            "Reply to Objection 2. r2\n"
            "Reply to Objection 3. r3\n"
        )
        self.assertTrue(is_summa_complete_text(text))

    def test_summarize_mode_v2(self) -> None:
        records = [
            {
                "v2": {
                    "status": "ok",
                    "duration_seconds": 10.0,
                    "metrics": {
                        "schema_valid": True,
                        "summa_complete": True,
                        "falsifiable_predictions_present": True,
                        "grounded_citations_present": True,
                        "keyword_relevance": True,
                        "avoids_known_bad_pattern": True,
                    },
                }
            },
            {
                "v2": {
                    "status": "ok",
                    "duration_seconds": 20.0,
                    "metrics": {
                        "schema_valid": True,
                        "summa_complete": False,
                        "falsifiable_predictions_present": True,
                        "grounded_citations_present": False,
                        "keyword_relevance": True,
                        "avoids_known_bad_pattern": True,
                    },
                }
            },
        ]
        summary = summarize_mode(records, "v2")
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["average_duration_seconds"], 15.0)
        self.assertEqual(summary["metrics"]["schema_valid_rate"], 1.0)
        self.assertEqual(summary["metrics"]["summa_complete_rate"], 0.5)

    def test_evaluate_go_no_go(self) -> None:
        v2_stats = {
            "average_duration_seconds": 120.0,
            "p95_duration_seconds": 200.0,
            "metrics": {
                "schema_valid_rate": 1.0,
                "falsifiable_predictions_rate": 1.0,
                "grounded_citations_rate": 1.0,
                "summa_complete_rate": 1.0,
            },
        }
        decision = evaluate_go_no_go(v2_stats=v2_stats, model="gpt-4o-mini")
        self.assertEqual(decision["recommendation"], "GO")

    def test_evaluate_v2_metrics_schema_error(self) -> None:
        payload = {
            "question": "Q",
            "domain": "physics",
            "hypotheses": [],
            "ranked_hypothesis_ids": [],
            "summa_rendering": "",
        }
        case = type(
            "Case",
            (),
            {
                "relevance_keywords": ["physics"],
                "known_bad_pattern": "restates the question",
            },
        )()
        metrics = evaluate_v2_metrics(case=case, payload=payload)
        self.assertFalse(metrics["schema_valid"])


if __name__ == "__main__":
    unittest.main()

