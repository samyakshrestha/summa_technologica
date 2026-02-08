"""Core utilities for semantic scholar in Summa Technologica."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_FIELDS = (
    "paperId,title,authors,year,abstract,citationCount,externalIds,url"
)


@dataclass(frozen=True)
class SemanticScholarPaper:
    paper_id: str | None
    title: str
    authors: list[str]
    year: int
    abstract: str
    citation_count: int | None
    doi: str | None
    url: str | None
    source_query: str

    def to_citation_dict(self) -> dict[str, Any]:
        """To citation dict."""
        payload: dict[str, Any] = {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
        }
        if self.paper_id:
            payload["paper_id"] = self.paper_id
        if self.doi:
            payload["doi"] = self.doi
        return payload

    def to_dict(self) -> dict[str, Any]:
        """To dict."""
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract,
            "citation_count": self.citation_count,
            "doi": self.doi,
            "url": self.url,
            "source_query": self.source_query,
        }


@dataclass(frozen=True)
class RetrievalResult:
    status: str
    message: str
    queries: list[str]
    papers: list[SemanticScholarPaper]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        """To dict."""
        return {
            "status": self.status,
            "message": self.message,
            "queries": self.queries,
            "papers": [paper.to_dict() for paper in self.papers],
            "errors": self.errors,
        }


def build_dual_queries(question: str, refined_query: str | None = None) -> list[str]:
    """Build dual queries."""
    candidates = [question.strip(), (refined_query or "").strip()]
    queries: list[str] = []
    for query in candidates:
        if query and query not in queries:
            queries.append(query)
    return queries


def search_semantic_scholar(
    query: str,
    *,
    base_url: str,
    api_key: str | None = None,
    limit: int = 10,
    timeout_seconds: float = 20.0,
    fields: str = DEFAULT_FIELDS,
) -> list[SemanticScholarPaper]:
    """Search semantic scholar."""
    if not query.strip():
        return []

    params = urlencode(
        {
            "query": query,
            "limit": max(1, min(int(limit), 100)),
            "fields": fields,
        }
    )
    url = f"{base_url.rstrip('/')}/graph/v1/paper/search?{params}"
    request = Request(url=url, headers=_build_headers(api_key))

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = _read_http_error_body(exc)
        raise RuntimeError(
            f"Semantic Scholar HTTP {exc.code} for query '{query}': {body}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Semantic Scholar network error for query '{query}': {exc}") from exc

    data = payload.get("data")
    if not isinstance(data, list):
        return []

    papers: list[SemanticScholarPaper] = []
    for raw in data:
        paper = _parse_paper(raw, source_query=query)
        if paper is not None:
            papers.append(paper)
    return papers


def retrieve_grounded_papers(
    *,
    question: str,
    refined_query: str | None,
    base_url: str,
    api_key: str | None = None,
    per_query_limit: int = 10,
    timeout_seconds: float = 20.0,
) -> RetrievalResult:
    """Retrieve grounded papers."""
    queries = build_dual_queries(question, refined_query)
    if not queries:
        return RetrievalResult(
            status="no_grounded_citations_found",
            message="no grounded citations found",
            queries=[],
            papers=[],
            errors=["question/refined_query are empty"],
        )

    merged: dict[str, SemanticScholarPaper] = {}
    errors: list[str] = []

    for query in queries:
        try:
            papers = search_semantic_scholar(
                query,
                base_url=base_url,
                api_key=api_key,
                limit=per_query_limit,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - covered via unit tests with mocks
            errors.append(str(exc))
            continue

        for paper in papers:
            dedupe_key = _dedupe_key(paper)
            if dedupe_key not in merged:
                merged[dedupe_key] = paper

    papers = list(merged.values())
    if not papers:
        message = "no grounded citations found"
        if errors:
            message = "no grounded citations found (API failure or empty results)"
        return RetrievalResult(
            status="no_grounded_citations_found",
            message=message,
            queries=queries,
            papers=[],
            errors=errors,
        )

    return RetrievalResult(
        status="ok",
        message=f"retrieved {len(papers)} grounded papers",
        queries=queries,
        papers=papers,
        errors=errors,
    )


def validate_citations_against_papers(
    citations: list[dict[str, Any]],
    papers: list[SemanticScholarPaper],
) -> list[str]:
    """Validate citations against papers."""
    valid_ids = {paper.paper_id for paper in papers if paper.paper_id}
    valid_dois = {_normalize_doi(paper.doi) for paper in papers if paper.doi}
    issues: list[str] = []

    for idx, citation in enumerate(citations, start=1):
        paper_id = citation.get("paper_id")
        doi = citation.get("doi")

        if not isinstance(citation.get("title"), str) or not citation["title"].strip():
            issues.append(f"citation[{idx}] missing non-empty title")
            continue
        if not isinstance(citation.get("authors"), list) or not citation["authors"]:
            issues.append(f"citation[{idx}] missing authors list")
            continue
        if not isinstance(citation.get("year"), int):
            issues.append(f"citation[{idx}] missing integer year")
            continue

        has_paper_id = isinstance(paper_id, str) and bool(paper_id.strip())
        has_doi = isinstance(doi, str) and bool(doi.strip())
        if not has_paper_id and not has_doi:
            issues.append(f"citation[{idx}] missing paper_id/doi")
            continue

        grounded = False
        if has_paper_id and paper_id.strip() in valid_ids:
            grounded = True
        if has_doi and _normalize_doi(doi) in valid_dois:
            grounded = True

        if not grounded:
            issues.append(f"citation[{idx}] not grounded in retrieved Semantic Scholar papers")

    return issues


def _build_headers(api_key: str | None) -> dict[str, str]:
    """Internal helper to build headers."""
    headers = {"Accept": "application/json"}
    if api_key and api_key.strip():
        headers["x-api-key"] = api_key.strip()
    return headers


def _parse_paper(payload: dict[str, Any], source_query: str) -> SemanticScholarPaper | None:
    """Internal helper to parse paper."""
    if not isinstance(payload, dict):
        return None

    title = payload.get("title")
    year = payload.get("year")
    if not isinstance(title, str) or not title.strip() or not isinstance(year, int):
        return None

    authors = payload.get("authors")
    author_names: list[str] = []
    if isinstance(authors, list):
        for author in authors:
            if isinstance(author, dict):
                name = author.get("name")
                if isinstance(name, str) and name.strip():
                    author_names.append(name.strip())
    if not author_names:
        return None

    external_ids = payload.get("externalIds")
    doi: str | None = None
    if isinstance(external_ids, dict):
        raw_doi = external_ids.get("DOI")
        if isinstance(raw_doi, str) and raw_doi.strip():
            doi = raw_doi.strip()

    paper_id = payload.get("paperId")
    abstract = payload.get("abstract")
    citation_count = payload.get("citationCount")
    url = payload.get("url")

    return SemanticScholarPaper(
        paper_id=paper_id.strip() if isinstance(paper_id, str) and paper_id.strip() else None,
        title=title.strip(),
        authors=author_names,
        year=year,
        abstract=abstract.strip() if isinstance(abstract, str) else "",
        citation_count=citation_count if isinstance(citation_count, int) else None,
        doi=doi,
        url=url.strip() if isinstance(url, str) and url.strip() else None,
        source_query=source_query,
    )


def _dedupe_key(paper: SemanticScholarPaper) -> str:
    """Internal helper to dedupe key."""
    if paper.paper_id:
        return f"paper_id:{paper.paper_id}"
    if paper.doi:
        return f"doi:{_normalize_doi(paper.doi)}"
    return f"title_year:{paper.title.lower()}::{paper.year}"


def _normalize_doi(value: str | None) -> str:
    """Internal helper to normalize doi."""
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized.startswith("doi:"):
        normalized = normalized[4:].strip()
    return normalized


def _read_http_error_body(exc: HTTPError) -> str:
    """Internal helper to read http error body."""
    try:
        raw = exc.read()
    except Exception:  # pragma: no cover
        return "<unavailable>"
    if not raw:
        return "<empty>"
    text = raw.decode("utf-8", errors="replace").strip()
    return text or "<empty>"

