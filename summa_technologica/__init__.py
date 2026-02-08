"""Summa Technologica scaffold package."""

from .models import SummaResponse
from .semantic_scholar import (
    RetrievalResult,
    SemanticScholarPaper,
    build_dual_queries,
    retrieve_grounded_papers,
    search_semantic_scholar,
    validate_citations_against_papers,
)
from .v2_contracts import (
    ContractValidationError,
    PipelineErrorContract,
    build_partial_failure_payload,
    parse_and_validate_v2_json,
    validate_partial_failure_payload,
    validate_v2_payload,
)


def run_summa(*args, **kwargs):
    """Run summa."""
    from .crew import run_summa as _run_summa

    return _run_summa(*args, **kwargs)


def run_summa_v2(*args, **kwargs):
    """Run summa v2."""
    from .crew_v2 import run_summa_v2 as _run_summa_v2

    return _run_summa_v2(*args, **kwargs)


__all__ = [
    "run_summa",
    "run_summa_v2",
    "SummaResponse",
    "ContractValidationError",
    "PipelineErrorContract",
    "build_partial_failure_payload",
    "parse_and_validate_v2_json",
    "validate_partial_failure_payload",
    "validate_v2_payload",
    "RetrievalResult",
    "SemanticScholarPaper",
    "build_dual_queries",
    "retrieve_grounded_papers",
    "search_semantic_scholar",
    "validate_citations_against_papers",
]
