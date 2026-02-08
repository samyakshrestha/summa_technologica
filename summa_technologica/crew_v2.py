"""Main orchestrator for the V2 hypothesis-generation pipeline.

This is the entry point. It runs 7 stages in sequence:

  1. Problem Framer   → converts the user's question into a structured research memo
  2. Paper Retrieval  → searches Semantic Scholar for relevant academic papers
  3. Literature Scout → summarizes the retrieved papers into an evidence memo
  4. Hypothesis Gen   → produces 3-5 distinct hypotheses grounded in that evidence
  5. Critic           → stress-tests hypotheses, adds objections and replies
  6. Ranker           → compares hypotheses pairwise on novelty/plausibility/testability
  7. Summa Composer   → renders the top hypothesis into Summa Theologica format

Each stage is an LLM call managed by CrewAI. If a stage fails, it retries once.
If the retry also fails, the pipeline returns a partial-failure payload instead
of crashing.

Files this module depends on:
  - config.py            → reads settings (model name, API keys) from .env
  - crew_v2_stages.py    → handles the actual LLM calls (CrewAI Agent/Task/Crew)
  - crew_v2_postprocess.py → cleans up LLM output (normalize JSON, rank, render)
  - semantic_scholar.py  → fetches papers from the Semantic Scholar API
  - v2_contracts.py      → validates the final output against a JSON schema
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .crew_v2_postprocess import (
    _apply_pairwise_ranking,
    _as_json,
    _ensure_summa_rendering,
    _hydrate_summa_triplets,
    _normalize_critic_hypotheses,
    _normalize_generated_hypotheses,
    _top_hypotheses,
)
from .crew_v2_stages import (
    _StageFailure,
    _load_yaml_config,
    _render_template,  # compatibility export for tests
    _require_nonempty_str,
    _run_json_stage,
    _run_stage_with_retry,
    _run_summa_composer_stage,
)
from .semantic_scholar import RetrievalResult, retrieve_grounded_papers
from .v2_contracts import (
    ContractValidationError,
    PipelineErrorContract,
    build_partial_failure_payload,
    validate_v2_payload,
)


def run_summa_v2(
    question: str,
    *,
    domain: str | None = None,
    objective: str | None = None,
    top: int = 1,
) -> dict[str, Any]:
    """Run the full V2 pipeline: question in, Summa-formatted hypothesis out."""
    cleaned_question = question.strip()
    if not cleaned_question:
        raise ValueError("Question cannot be empty.")
    if top not in {1, 3}:
        raise ValueError("top must be 1 or 3 for V2 mode.")

    settings = Settings.from_env()
    cleaned_domain = (domain or settings.default_domain).strip() or settings.default_domain
    cleaned_objective = (objective or settings.default_objective).strip()
    if not cleaned_objective:
        cleaned_objective = settings.default_objective

    agents_cfg = _load_yaml_config(Path(__file__).with_name("config") / "agents_v2.yaml")
    tasks_cfg = _load_yaml_config(Path(__file__).with_name("config") / "tasks_v2.yaml")

    stage_outputs: dict[str, Any] = {}
    normalized_hypotheses: list[dict[str, Any]] = []
    ranked_ids: list[str] = []
    summa_rendering = ""

    try:
        problem_memo = _run_stage_with_retry(
            stage_name="problem_framer",
            run_once=lambda retry_error: _run_json_stage(
                agent_cfg=agents_cfg["problem_framer"],
                task_cfg=tasks_cfg["problem_framer_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "objective": cleaned_objective,
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["problem_framer"] = problem_memo

        retrieval_result = retrieve_grounded_papers(
            question=cleaned_question,
            refined_query=problem_memo.get("refined_query"),
            base_url=settings.semantic_scholar_base_url,
            api_key=settings.semantic_scholar_api_key,
            per_query_limit=10,
            timeout_seconds=settings.semantic_scholar_timeout_seconds,
        )
        stage_outputs["retrieval"] = retrieval_result.to_dict()

        evidence_memo = _run_stage_with_retry(
            stage_name="literature_scout",
            run_once=lambda retry_error: _run_json_stage(
                agent_cfg=agents_cfg["literature_scout"],
                task_cfg=tasks_cfg["literature_scout_task"],
                settings=settings,
                inputs={
                    "domain": cleaned_domain,
                    "problem_memo_json": _as_json(problem_memo),
                    "retrieval_json": _as_json(retrieval_result.to_dict()),
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["literature_scout"] = evidence_memo

        generator_output = _run_stage_with_retry(
            stage_name="hypothesis_generator",
            run_once=lambda retry_error: _run_json_stage(
                agent_cfg=agents_cfg["hypothesis_generator"],
                task_cfg=tasks_cfg["hypothesis_generator_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "objective": cleaned_objective,
                    "problem_memo_json": _as_json(problem_memo),
                    "evidence_memo_json": _as_json(evidence_memo),
                    "retrieval_json": _as_json(retrieval_result.to_dict()),
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["hypothesis_generator"] = generator_output
        normalized_hypotheses = _normalize_generated_hypotheses(
            generator_output,
            retrieval_result.papers,
        )
        if len(normalized_hypotheses) < 3:
            normalized_hypotheses = _regenerate_for_diversity(
                settings=settings,
                agents_cfg=agents_cfg,
                tasks_cfg=tasks_cfg,
                question=cleaned_question,
                domain=cleaned_domain,
                objective=cleaned_objective,
                problem_memo=problem_memo,
                evidence_memo=evidence_memo,
                retrieval_result=retrieval_result,
                stage_outputs=stage_outputs,
            )

        critic_output = _run_stage_with_retry(
            stage_name="critic",
            run_once=lambda retry_error: _run_json_stage(
                agent_cfg=agents_cfg["critic"],
                task_cfg=tasks_cfg["critic_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "hypotheses_json": _as_json({"hypotheses": normalized_hypotheses}),
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["critic"] = critic_output
        normalized_hypotheses = _normalize_critic_hypotheses(
            critic_output,
            fallback=normalized_hypotheses,
            grounded_papers=retrieval_result.papers,
        )

        if len(normalized_hypotheses) < 3:
            normalized_hypotheses = _regenerate_for_diversity(
                settings=settings,
                agents_cfg=agents_cfg,
                tasks_cfg=tasks_cfg,
                question=cleaned_question,
                domain=cleaned_domain,
                objective=cleaned_objective,
                problem_memo=problem_memo,
                evidence_memo=evidence_memo,
                retrieval_result=retrieval_result,
                stage_outputs=stage_outputs,
            )

        ranker_output = _run_stage_with_retry(
            stage_name="ranker",
            run_once=lambda retry_error: _run_json_stage(
                agent_cfg=agents_cfg["ranker"],
                task_cfg=tasks_cfg["ranker_task"],
                settings=settings,
                inputs={
                    "domain": cleaned_domain,
                    "critic_json": _as_json(
                        {
                            "hypotheses": normalized_hypotheses,
                            "distinctness_matrix": critic_output.get("distinctness_matrix", []),
                        }
                    ),
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["ranker"] = ranker_output

        ranked_ids, hypotheses_with_scores = _apply_pairwise_ranking(
            hypotheses=normalized_hypotheses,
            ranker_output=ranker_output,
        )
        normalized_hypotheses = _hydrate_summa_triplets(hypotheses_with_scores)

        composer_output = _run_stage_with_retry(
            stage_name="summa_composer",
            run_once=lambda retry_error: _run_summa_composer_stage(
                agent_cfg=agents_cfg["summa_composer"],
                task_cfg=tasks_cfg["summa_composer_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "top_hypotheses_json": _as_json(
                        _top_hypotheses(normalized_hypotheses, ranked_ids, top)
                    ),
                    "ranking_json": _as_json({"ranked_hypothesis_ids": ranked_ids}),
                    "top_count": str(top),
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["summa_composer"] = composer_output
        summa_rendering = _ensure_summa_rendering(
            raw_rendering=_require_nonempty_str(composer_output, "summa_rendering"),
            question=cleaned_question,
            hypotheses=normalized_hypotheses,
            ranked_ids=ranked_ids,
            top=top,
        )

        final_payload = {
            "question": cleaned_question,
            "domain": cleaned_domain,
            "hypotheses": normalized_hypotheses,
            "ranked_hypothesis_ids": ranked_ids,
            "summa_rendering": summa_rendering,
        }

        try:
            validate_v2_payload(final_payload, grounded_papers=retrieval_result.papers)
        except ContractValidationError as exc:
            composer_retry = _run_summa_composer_stage(
                agent_cfg=agents_cfg["summa_composer"],
                task_cfg=tasks_cfg["summa_composer_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "top_hypotheses_json": _as_json(
                        _top_hypotheses(normalized_hypotheses, ranked_ids, top)
                    ),
                    "ranking_json": _as_json({"ranked_hypothesis_ids": ranked_ids}),
                    "top_count": str(top),
                },
                retry_error=f"Final payload validation failed: {exc}",
            )
            stage_outputs["summa_composer_retry"] = composer_retry
            final_payload["summa_rendering"] = _ensure_summa_rendering(
                raw_rendering=_require_nonempty_str(composer_retry, "summa_rendering"),
                question=cleaned_question,
                hypotheses=normalized_hypotheses,
                ranked_ids=ranked_ids,
                top=top,
            )
            validate_v2_payload(final_payload, grounded_papers=retrieval_result.papers)

        return final_payload
    except _StageFailure as exc:
        return build_partial_failure_payload(
            question=cleaned_question,
            domain=cleaned_domain,
            error=PipelineErrorContract(
                stage=exc.stage,
                message=exc.message,
                retry_attempted=exc.retry_attempted,
            ),
            stage_outputs=stage_outputs,
            hypotheses=normalized_hypotheses,
            ranked_hypothesis_ids=ranked_ids,
            summa_rendering=summa_rendering,
        )


def _regenerate_for_diversity(
    *,
    settings: Settings,
    agents_cfg: dict[str, Any],
    tasks_cfg: dict[str, Any],
    question: str,
    domain: str,
    objective: str,
    problem_memo: dict[str, Any],
    evidence_memo: dict[str, Any],
    retrieval_result: RetrievalResult,
    stage_outputs: dict[str, Any],
) -> list[dict[str, Any]]:
    """Internal helper to regenerate for diversity."""
    diversity_objective = (
        objective
        + " Hard constraint: produce at least 3 genuinely distinct hypotheses "
        + "across mechanism, empirical domain, or theoretical framework."
    )
    regenerated = _run_stage_with_retry(
        stage_name="hypothesis_generator_diversity_retry",
        run_once=lambda retry_error: _run_json_stage(
            agent_cfg=agents_cfg["hypothesis_generator"],
            task_cfg=tasks_cfg["hypothesis_generator_task"],
            settings=settings,
            inputs={
                "question": question,
                "domain": domain,
                "objective": diversity_objective,
                "problem_memo_json": _as_json(problem_memo),
                "evidence_memo_json": _as_json(evidence_memo),
                "retrieval_json": _as_json(retrieval_result.to_dict()),
            },
            retry_error=retry_error,
        ),
    )
    stage_outputs["hypothesis_generator_diversity_retry"] = regenerated
    normalized = _normalize_generated_hypotheses(regenerated, retrieval_result.papers)
    if len(normalized) < 3:
        raise _StageFailure(
            stage="hypothesis_generator_diversity_retry",
            message="Diversity retry still produced fewer than 3 distinct hypotheses.",
            retry_attempted=True,
        )
    return normalized
