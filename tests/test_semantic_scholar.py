"""Unit tests for the test semantic scholar module behavior."""

import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from summa_technologica.semantic_scholar import (
    SemanticScholarPaper,
    build_expanded_queries,
    build_dual_queries,
    retrieve_grounded_papers,
    search_semantic_scholar,
    validate_citations_against_papers,
)


class _FakeResponse:
    def __init__(self, payload: dict):
        """Initialize this object with validated inputs."""
        self._payload = payload

    def read(self) -> bytes:
        """Read."""
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        """Internal helper to enter."""
        return self

    def __exit__(self, exc_type, exc, tb):
        """Internal helper to exit."""
        return None


class SemanticScholarQueryTests(unittest.TestCase):
    def test_build_dual_queries(self) -> None:
        """Verify that build dual queries."""
        queries = build_dual_queries("q1", "q2")
        self.assertEqual(queries, ["q1", "q2"])

    def test_build_dual_queries_dedupes(self) -> None:
        """Verify that build dual queries dedupes."""
        queries = build_dual_queries("q1", "q1")
        self.assertEqual(queries, ["q1"])

    def test_build_expanded_queries_uses_problem_memo(self) -> None:
        """Verify expanded queries add thesis and assumption hints."""
        queries = build_expanded_queries(
            "base question",
            "refined query",
            {
                "thesis_directions": ["direction one", "direction two"],
                "assumptions": ["assumption one", "assumption two"],
            },
            max_queries=5,
        )
        self.assertGreaterEqual(len(queries), 3)
        self.assertLessEqual(len(queries), 5)
        self.assertIn("base question", queries[0])


class SemanticScholarSearchTests(unittest.TestCase):
    @patch("summa_technologica.semantic_scholar.urlopen")
    def test_search_parses_papers(self, mock_urlopen) -> None:
        """Verify that search parses papers."""
        mock_urlopen.return_value = _FakeResponse(
            {
                "data": [
                    {
                        "paperId": "p1",
                        "title": "Paper One",
                        "authors": [{"name": "A"}, {"name": "B"}],
                        "year": 2022,
                        "abstract": "x",
                        "citationCount": 10,
                        "externalIds": {"DOI": "10.1000/x"},
                        "url": "https://example.org/p1",
                    }
                ]
            }
        )

        papers = search_semantic_scholar(
            "test query",
            base_url="https://api.semanticscholar.org",
            api_key=None,
            limit=10,
            timeout_seconds=1.0,
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].paper_id, "p1")
        self.assertEqual(papers[0].doi, "10.1000/x")

    @patch("summa_technologica.semantic_scholar.urlopen")
    def test_retrieve_deduplicates_across_queries(self, mock_urlopen) -> None:
        """Verify that retrieve deduplicates across queries."""
        first_payload = {
            "data": [
                {
                    "paperId": "p1",
                    "title": "Paper One",
                    "authors": [{"name": "A"}],
                    "year": 2022,
                    "externalIds": {"DOI": "10.1000/x"},
                }
            ]
        }
        second_payload = {
            "data": [
                {
                    "paperId": "p1",
                    "title": "Paper One",
                    "authors": [{"name": "A"}],
                    "year": 2022,
                    "externalIds": {"DOI": "10.1000/x"},
                },
                {
                    "paperId": "p2",
                    "title": "Paper Two",
                    "authors": [{"name": "B"}],
                    "year": 2021,
                    "externalIds": {"DOI": "10.1000/y"},
                },
            ]
        }
        mock_urlopen.side_effect = [_FakeResponse(first_payload), _FakeResponse(second_payload)]

        result = retrieve_grounded_papers(
            question="query one",
            refined_query="query two",
            base_url="https://api.semanticscholar.org",
            api_key=None,
            per_query_limit=10,
            timeout_seconds=1.0,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.papers), 2)

    @patch("summa_technologica.semantic_scholar.urlopen")
    def test_retrieve_handles_network_failures(self, mock_urlopen) -> None:
        """Verify that retrieve handles network failures."""
        mock_urlopen.side_effect = URLError("offline")
        result = retrieve_grounded_papers(
            question="query one",
            refined_query="query two",
            base_url="https://api.semanticscholar.org",
            api_key=None,
            per_query_limit=10,
            timeout_seconds=1.0,
        )
        self.assertEqual(result.status, "no_grounded_citations_found")
        self.assertTrue(result.errors)

    @patch("summa_technologica.semantic_scholar.urlopen")
    def test_retrieve_ranks_abstract_quality_before_citation_count(self, mock_urlopen) -> None:
        """Verify ranking favors rich abstracts while keeping sparse papers."""
        mock_urlopen.return_value = _FakeResponse(
            {
                "data": [
                    {
                        "paperId": "p1",
                        "title": "Sparse Abstract High Citations",
                        "authors": [{"name": "A"}],
                        "year": 2020,
                        "abstract": "",
                        "citationCount": 1000,
                    },
                    {
                        "paperId": "p2",
                        "title": "Rich Abstract Mid Citations",
                        "authors": [{"name": "B"}],
                        "year": 2023,
                        "abstract": "This abstract is deliberately long enough to pass the quality threshold for ranking.",
                        "citationCount": 100,
                    },
                    {
                        "paperId": "p3",
                        "title": "Rich Abstract Low Citations",
                        "authors": [{"name": "C"}],
                        "year": 2022,
                        "abstract": "This abstract is also long enough to count as high-information evidence in ranking.",
                        "citationCount": 10,
                    },
                ]
            }
        )

        result = retrieve_grounded_papers(
            question="query one",
            refined_query=None,
            base_url="https://api.semanticscholar.org",
            api_key=None,
            per_query_limit=10,
            timeout_seconds=1.0,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.papers), 3)
        self.assertEqual(result.papers[0].paper_id, "p2")
        self.assertEqual(result.papers[1].paper_id, "p3")
        self.assertEqual(result.papers[2].paper_id, "p1")

    @patch("summa_technologica.semantic_scholar.urlopen")
    def test_retrieve_returns_expanded_query_list(self, mock_urlopen) -> None:
        """Verify retrieval reports expanded queries when problem memo is present."""
        mock_urlopen.return_value = _FakeResponse({"data": []})
        result = retrieve_grounded_papers(
            question="base question",
            refined_query="refined query",
            problem_memo={
                "thesis_directions": ["direction one", "direction two"],
                "assumptions": ["assumption one", "assumption two"],
            },
            base_url="https://api.semanticscholar.org",
            api_key=None,
            per_query_limit=10,
            timeout_seconds=1.0,
        )
        self.assertLessEqual(len(result.queries), 5)
        self.assertGreaterEqual(len(result.queries), 3)


class CitationGroundingTests(unittest.TestCase):
    def test_validate_citations_against_papers(self) -> None:
        """Verify that validate citations against papers."""
        papers = [
            SemanticScholarPaper(
                paper_id="p1",
                title="Paper One",
                authors=["A"],
                year=2020,
                abstract="",
                citation_count=None,
                doi="10.1000/x",
                url=None,
                source_query="q",
            )
        ]
        citations = [
            {
                "title": "Paper One",
                "authors": ["A"],
                "year": 2020,
                "paper_id": "p1",
            }
        ]
        issues = validate_citations_against_papers(citations, papers)
        self.assertEqual(issues, [])

    def test_validate_citations_rejects_ungrounded(self) -> None:
        """Verify that validate citations rejects ungrounded."""
        papers = [
            SemanticScholarPaper(
                paper_id="p1",
                title="Paper One",
                authors=["A"],
                year=2020,
                abstract="",
                citation_count=None,
                doi="10.1000/x",
                url=None,
                source_query="q",
            )
        ]
        citations = [
            {
                "title": "Different",
                "authors": ["A"],
                "year": 2020,
                "paper_id": "p9",
            }
        ]
        issues = validate_citations_against_papers(citations, papers)
        self.assertEqual(len(issues), 1)


if __name__ == "__main__":
    unittest.main()
