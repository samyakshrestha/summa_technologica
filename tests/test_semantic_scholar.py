"""Unit tests for the test semantic scholar module behavior."""

import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from summa_technologica.semantic_scholar import (
    SemanticScholarPaper,
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

