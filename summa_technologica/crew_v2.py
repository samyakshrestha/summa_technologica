from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

from .config import Settings
from .semantic_scholar import (
    RetrievalResult,
    SemanticScholarPaper,
    retrieve_grounded_papers,
)
from .v2_contracts import (
    ContractValidationError,
    PipelineErrorContract,
    build_partial_failure_payload,
    validate_v2_payload,
)


@dataclass
class _StageFailure(Exception):
    stage: str
    message: str
    retry_attempted: bool = True

    def __str__(self) -> str:
        return f"{self.stage}: {self.message}"


def run_summa_v2(
    question: str,
    *,
    domain: str | None = None,
    objective: str | None = None,
    top: int = 1,
) -> dict[str, Any]:
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
        normalized_hypotheses = hypotheses_with_scores

        composer_output = _run_stage_with_retry(
            stage_name="summa_composer",
            run_once=lambda retry_error: _run_json_stage(
                agent_cfg=agents_cfg["summa_composer"],
                task_cfg=tasks_cfg["summa_composer_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "top_hypotheses_json": _as_json(_top_hypotheses(normalized_hypotheses, ranked_ids, top)),
                    "ranking_json": _as_json({"ranked_hypothesis_ids": ranked_ids}),
                    "top_count": str(top),
                },
                retry_error=retry_error,
            ),
        )
        stage_outputs["summa_composer"] = composer_output
        summa_rendering = _require_nonempty_str(composer_output, "summa_rendering")

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
            composer_retry = _run_json_stage(
                agent_cfg=agents_cfg["summa_composer"],
                task_cfg=tasks_cfg["summa_composer_task"],
                settings=settings,
                inputs={
                    "question": cleaned_question,
                    "domain": cleaned_domain,
                    "top_hypotheses_json": _as_json(_top_hypotheses(normalized_hypotheses, ranked_ids, top)),
                    "ranking_json": _as_json({"ranked_hypothesis_ids": ranked_ids}),
                    "top_count": str(top),
                },
                retry_error=f"Final payload validation failed: {exc}",
            )
            stage_outputs["summa_composer_retry"] = composer_retry
            final_payload["summa_rendering"] = _require_nonempty_str(composer_retry, "summa_rendering")
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


def _run_stage_with_retry(
    *,
    stage_name: str,
    run_once: Callable[[str | None], dict[str, Any]],
) -> dict[str, Any]:
    retry_error: str | None = None
    for attempt in range(2):
        try:
            return run_once(retry_error)
        except Exception as exc:
            if attempt == 0:
                retry_error = str(exc)
                continue
            raise _StageFailure(
                stage=stage_name,
                message=str(exc),
                retry_attempted=True,
            ) from exc
    raise _StageFailure(stage=stage_name, message="Unknown stage failure.", retry_attempted=True)


def _run_json_stage(
    *,
    agent_cfg: dict[str, Any],
    task_cfg: dict[str, Any],
    settings: Settings,
    inputs: dict[str, str],
    retry_error: str | None,
) -> dict[str, Any]:
    raw = _run_agent_task(
        agent_cfg=agent_cfg,
        task_cfg=task_cfg,
        settings=settings,
        inputs=inputs,
        retry_error=retry_error,
    )
    return _parse_json_object(raw)


def _run_agent_task(
    *,
    agent_cfg: dict[str, Any],
    task_cfg: dict[str, Any],
    settings: Settings,
    inputs: dict[str, str],
    retry_error: str | None,
) -> str:
    try:
        from crewai import Agent, Crew, Process, Task
    except ModuleNotFoundError as exc:
        if exc.name == "crewai":
            raise RuntimeError(
                "crewai is not installed. Run: pip install crewai && pip install -e ."
            ) from exc
        raise

    description_template = _require_nonempty_str(task_cfg, "description")
    expected_output_template = _require_nonempty_str(task_cfg, "expected_output")
    description = description_template.format(**inputs)
    expected_output = expected_output_template.format(**inputs)

    if retry_error:
        description += (
            "\n\nRetry context:\n"
            f"Previous attempt failed with: {retry_error}\n"
            "You must return strict JSON only, parseable by json.loads."
        )

    agent = Agent(config=agent_cfg, llm=settings.model, verbose=settings.verbose)
    task = Task(
        description=description,
        expected_output=expected_output,
        agent=agent,
    )
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=settings.verbose,
    )
    output = crew.kickoff(inputs=inputs)
    return _extract_raw_output(output)


def _extract_raw_output(output: Any) -> str:
    if isinstance(output, str):
        return output

    raw = getattr(output, "raw", None)
    if isinstance(raw, str) and raw.strip():
        return raw

    tasks_output = getattr(output, "tasks_output", None)
    if isinstance(tasks_output, list) and tasks_output:
        maybe_last = tasks_output[-1]
        maybe_raw = getattr(maybe_last, "raw", None)
        if isinstance(maybe_raw, str) and maybe_raw.strip():
            return maybe_raw

    return str(output)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            snippet = raw[:260].replace("\n", " ")
            raise ValueError(f"No JSON object found in stage output: {snippet}") from None
        payload = json.loads(match.group(0))

    if not isinstance(payload, dict):
        raise ValueError("Stage output must be a JSON object.")
    return payload


def _normalize_generated_hypotheses(
    payload: dict[str, Any],
    grounded_papers: list[SemanticScholarPaper],
) -> list[dict[str, Any]]:
    raw = payload.get("hypotheses")
    if not isinstance(raw, list):
        raise ValueError("Generator output must include hypotheses array.")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    fallback_counter = 1
    for item in raw:
        if not isinstance(item, dict):
            continue
        hypothesis_id = _as_id(item.get("id"), fallback_counter)
        while hypothesis_id in seen_ids:
            fallback_counter += 1
            hypothesis_id = _as_id(None, fallback_counter)
        seen_ids.add(hypothesis_id)
        fallback_counter += 1

        hypothesis = {
            "id": hypothesis_id,
            "title": _as_nonempty_text(item.get("title"), f"Hypothesis {hypothesis_id}"),
            "statement": _as_nonempty_text(item.get("statement"), "No statement provided."),
            "novelty_rationale": _as_nonempty_text(
                item.get("novelty_rationale"),
                "Novelty rationale unavailable.",
            ),
            "plausibility_rationale": _as_nonempty_text(
                item.get("plausibility_rationale"),
                "Plausibility rationale unavailable.",
            ),
            "testability_rationale": _as_nonempty_text(
                item.get("testability_rationale"),
                "Testability rationale unavailable.",
            ),
            "falsifiable_predictions": _normalize_text_list(
                item.get("falsifiable_predictions"),
                fallback="Prediction not provided.",
            ),
            "minimal_experiments": _normalize_text_list(
                item.get("minimal_experiments"),
                fallback="Experiment plan not provided.",
            ),
            "citations": _sanitize_citations(item.get("citations"), grounded_papers),
        }
        normalized.append(hypothesis)

    return normalized[:5]


def _normalize_critic_hypotheses(
    critic_payload: dict[str, Any],
    *,
    fallback: list[dict[str, Any]],
    grounded_papers: list[SemanticScholarPaper],
) -> list[dict[str, Any]]:
    raw = critic_payload.get("hypotheses")
    if not isinstance(raw, list) or not raw:
        hypotheses = fallback
    else:
        hypotheses = []
        seen_ids: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            hypothesis_id = _as_nonempty_text(item.get("id"), "")
            if not hypothesis_id or hypothesis_id in seen_ids:
                continue
            seen_ids.add(hypothesis_id)
            hypotheses.append(
                {
                    "id": hypothesis_id,
                    "title": _as_nonempty_text(item.get("title"), f"Hypothesis {hypothesis_id}"),
                    "statement": _as_nonempty_text(item.get("statement"), "No statement provided."),
                    "novelty_rationale": _as_nonempty_text(
                        item.get("novelty_rationale"),
                        "Novelty rationale unavailable.",
                    ),
                    "plausibility_rationale": _as_nonempty_text(
                        item.get("plausibility_rationale"),
                        "Plausibility rationale unavailable.",
                    ),
                    "testability_rationale": _as_nonempty_text(
                        item.get("testability_rationale"),
                        "Testability rationale unavailable.",
                    ),
                    "falsifiable_predictions": _normalize_text_list(
                        item.get("falsifiable_predictions"),
                        fallback="Prediction not provided.",
                    ),
                    "minimal_experiments": _normalize_text_list(
                        item.get("minimal_experiments"),
                        fallback="Experiment plan not provided.",
                    ),
                    "citations": _sanitize_citations(item.get("citations"), grounded_papers),
                    "objections": _ensure_objections(item.get("objections")),
                    "replies": _ensure_replies(item.get("replies")),
                }
            )

    if not hypotheses:
        raise ValueError("Critic output did not provide any usable hypotheses.")

    for hypothesis in hypotheses:
        if "objections" not in hypothesis:
            hypothesis["objections"] = _ensure_objections(None)
        if "replies" not in hypothesis:
            hypothesis["replies"] = _ensure_replies(None)
    return hypotheses[:5]


def _apply_pairwise_ranking(
    *,
    hypotheses: list[dict[str, Any]],
    ranker_output: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    ids = [item["id"] for item in hypotheses]
    comparisons = ranker_output.get("comparisons")
    if not isinstance(comparisons, list):
        raise ValueError("Ranker output must contain a comparisons array.")

    normalized_comparisons: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in comparisons:
        if not isinstance(item, dict):
            continue
        a = _as_nonempty_text(item.get("hypothesis_a_id"), "")
        b = _as_nonempty_text(item.get("hypothesis_b_id"), "")
        if not a or not b or a == b or a not in ids or b not in ids:
            continue
        pair = tuple(sorted([a, b]))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        normalized_comparisons.append(
            {
                "hypothesis_a_id": a,
                "hypothesis_b_id": b,
                "winner_novelty": _winner(item.get("winner_novelty")),
                "winner_plausibility": _winner(item.get("winner_plausibility")),
                "winner_testability": _winner(item.get("winner_testability")),
            }
        )

    expected_pairs = {
        tuple(sorted([ids[i], ids[j]]))
        for i in range(len(ids))
        for j in range(i + 1, len(ids))
    }
    for pair in sorted(expected_pairs):
        if pair not in seen_pairs:
            normalized_comparisons.append(
                {
                    "hypothesis_a_id": pair[0],
                    "hypothesis_b_id": pair[1],
                    "winner_novelty": "tie",
                    "winner_plausibility": "tie",
                    "winner_testability": "tie",
                }
            )

    wins: dict[str, dict[str, int]] = {
        hypothesis_id: {"novelty": 0, "plausibility": 0, "testability": 0}
        for hypothesis_id in ids
    }
    for comparison in normalized_comparisons:
        a = comparison["hypothesis_a_id"]
        b = comparison["hypothesis_b_id"]
        _accumulate_win(wins, "novelty", comparison["winner_novelty"], a, b)
        _accumulate_win(wins, "plausibility", comparison["winner_plausibility"], a, b)
        _accumulate_win(wins, "testability", comparison["winner_testability"], a, b)

    divisor = max(len(ids) - 1, 1)
    scores_by_id: dict[str, dict[str, float]] = {}
    for hypothesis_id in ids:
        novelty = 1 + 4 * (wins[hypothesis_id]["novelty"] / divisor)
        plausibility = 1 + 4 * (wins[hypothesis_id]["plausibility"] / divisor)
        testability = 1 + 4 * (wins[hypothesis_id]["testability"] / divisor)
        overall = 0.35 * novelty + 0.30 * plausibility + 0.35 * testability
        scores_by_id[hypothesis_id] = {
            "novelty": round(novelty, 3),
            "plausibility": round(plausibility, 3),
            "testability": round(testability, 3),
            "overall": round(overall, 3),
        }

    ranked_ids = sorted(
        ids,
        key=lambda hid: (
            scores_by_id[hid]["overall"],
            scores_by_id[hid]["novelty"],
            scores_by_id[hid]["testability"],
            scores_by_id[hid]["plausibility"],
        ),
        reverse=True,
    )

    by_id = {item["id"]: item for item in hypotheses}
    updated: list[dict[str, Any]] = []
    for hypothesis_id in ids:
        hypothesis = dict(by_id[hypothesis_id])
        hypothesis["pairwise_record"] = {
            "comparisons": [cmp for cmp in normalized_comparisons if hypothesis_id in {cmp["hypothesis_a_id"], cmp["hypothesis_b_id"]}],
            "wins_by_dimension": wins[hypothesis_id],
        }
        hypothesis["scores"] = scores_by_id[hypothesis_id]
        updated.append(hypothesis)

    return ranked_ids, updated


def _top_hypotheses(
    hypotheses: list[dict[str, Any]],
    ranked_ids: list[str],
    top: int,
) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in hypotheses}
    top_ids = ranked_ids[:top]
    return [by_id[hypothesis_id] for hypothesis_id in top_ids if hypothesis_id in by_id]


def _sanitize_citations(
    citations: Any,
    grounded_papers: list[SemanticScholarPaper],
) -> list[dict[str, Any]]:
    if not isinstance(citations, list):
        return []

    valid_ids = {paper.paper_id for paper in grounded_papers if paper.paper_id}
    valid_dois = {_normalize_doi(paper.doi) for paper in grounded_papers if paper.doi}

    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        title = citation.get("title")
        authors = citation.get("authors")
        year = citation.get("year")
        paper_id = citation.get("paper_id")
        doi = citation.get("doi")

        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(authors, list) or not authors:
            continue
        if not isinstance(year, int):
            continue

        has_valid_paper_id = isinstance(paper_id, str) and paper_id.strip() in valid_ids
        has_valid_doi = isinstance(doi, str) and _normalize_doi(doi) in valid_dois
        if not (has_valid_paper_id or has_valid_doi):
            continue

        key = paper_id.strip() if has_valid_paper_id else f"doi:{_normalize_doi(doi)}"
        if key in seen:
            continue
        seen.add(key)

        payload: dict[str, Any] = {
            "title": title.strip(),
            "authors": [str(item).strip() for item in authors if str(item).strip()],
            "year": year,
        }
        if has_valid_paper_id:
            payload["paper_id"] = paper_id.strip()
        if has_valid_doi:
            payload["doi"] = doi.strip()
        sanitized.append(payload)

    return sanitized


def _ensure_objections(raw: Any) -> list[dict[str, Any]]:
    objections: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            number = item.get("number")
            text = item.get("text")
            if isinstance(number, int) and isinstance(text, str) and text.strip():
                objections.append({"number": number, "text": text.strip()})

    objections = sorted(objections, key=lambda item: item["number"])
    for n in [1, 2, 3]:
        if not any(item["number"] == n for item in objections):
            objections.append(
                {
                    "number": n,
                    "text": f"Objection {n} was not explicitly provided; further critique required.",
                }
            )
    objections = sorted(objections, key=lambda item: item["number"])
    return objections[:3]


def _ensure_replies(raw: Any) -> list[dict[str, Any]]:
    replies: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            number = item.get("objection_number")
            text = item.get("text")
            if isinstance(number, int) and isinstance(text, str) and text.strip():
                replies.append({"objection_number": number, "text": text.strip()})

    replies = sorted(replies, key=lambda item: item["objection_number"])
    for n in [1, 2, 3]:
        if not any(item["objection_number"] == n for item in replies):
            replies.append(
                {
                    "objection_number": n,
                    "text": f"Reply to objection {n} requires further elaboration.",
                }
            )
    replies = sorted(replies, key=lambda item: item["objection_number"])
    return replies[:3]


def _load_yaml_config(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required for V2 mode. Run: pip install -e ."
        ) from exc

    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Invalid YAML object at {path}")
    return content


def _winner(value: Any) -> str:
    text = str(value).strip().lower()
    if text in {"a", "b", "tie"}:
        return text
    return "tie"


def _accumulate_win(
    wins: dict[str, dict[str, int]],
    dimension: str,
    winner: str,
    a: str,
    b: str,
) -> None:
    if winner == "a":
        wins[a][dimension] += 1
    elif winner == "b":
        wins[b][dimension] += 1


def _as_id(value: Any, fallback_counter: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"h{fallback_counter}"


def _as_nonempty_text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _normalize_text_list(value: Any, fallback: str) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if cleaned:
            return cleaned
    return [fallback]


def _normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized.startswith("doi:"):
        normalized = normalized[4:].strip()
    return normalized


def _as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _require_nonempty_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{key}' must be a non-empty string.")
    return value.strip()
