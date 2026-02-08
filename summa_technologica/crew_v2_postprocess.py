"""Post-processing — cleans up raw LLM output into structured, validated data.

After the LLM produces JSON, the output is often messy: missing fields,
duplicate IDs, ungrounded citations, missing objections. This file fixes
all of that. Key responsibilities:

  - Normalize hypotheses: assign IDs, fill missing fields with fallbacks
  - Sanitize citations: keep only papers that exist in Semantic Scholar results
  - Ensure objections/replies: guarantee exactly 3 of each per hypothesis
  - Pairwise ranking: tally wins from the Ranker's comparisons, compute scores
  - Summa rendering: validate the LLM's rendering or build one from scratch

The main orchestrator (crew_v2.py) calls these functions after each LLM stage
to clean up the output before passing it to the next stage.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .semantic_scholar import SemanticScholarPaper


def _normalize_generated_hypotheses(
    payload: dict[str, Any],
    grounded_papers: list[SemanticScholarPaper],
) -> list[dict[str, Any]]:
    """Internal helper to normalize generated hypotheses."""
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

        citations = _sanitize_citations(item.get("citations"), grounded_papers)
        if not citations:
            citations = _fallback_grounded_citations(grounded_papers)

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
            "citations": citations,
            "objections": _ensure_objections(item.get("objections")),
            "replies": _ensure_replies(item.get("replies")),
        }
        normalized.append(hypothesis)

    return normalized[:5]


def _normalize_critic_hypotheses(
    critic_payload: dict[str, Any],
    *,
    fallback: list[dict[str, Any]],
    grounded_papers: list[SemanticScholarPaper],
) -> list[dict[str, Any]]:
    """Internal helper to normalize critic hypotheses."""
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
            citations = _sanitize_citations(item.get("citations"), grounded_papers)
            if not citations:
                citations = _fallback_grounded_citations(grounded_papers)
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
                    "citations": citations,
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
    """Internal helper to apply pairwise ranking."""
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
    points: dict[str, dict[str, float]] = {
        hypothesis_id: {"novelty": 0.0, "plausibility": 0.0, "testability": 0.0}
        for hypothesis_id in ids
    }
    for comparison in normalized_comparisons:
        a = comparison["hypothesis_a_id"]
        b = comparison["hypothesis_b_id"]
        _accumulate_win(wins, "novelty", comparison["winner_novelty"], a, b)
        _accumulate_win(wins, "plausibility", comparison["winner_plausibility"], a, b)
        _accumulate_win(wins, "testability", comparison["winner_testability"], a, b)
        _accumulate_points(points, "novelty", comparison["winner_novelty"], a, b)
        _accumulate_points(points, "plausibility", comparison["winner_plausibility"], a, b)
        _accumulate_points(points, "testability", comparison["winner_testability"], a, b)

    divisor = max(len(ids) - 1, 1)
    scores_by_id: dict[str, dict[str, float]] = {}
    for hypothesis_id in ids:
        novelty = 1 + 4 * (points[hypothesis_id]["novelty"] / divisor)
        plausibility = 1 + 4 * (points[hypothesis_id]["plausibility"] / divisor)
        testability = 1 + 4 * (points[hypothesis_id]["testability"] / divisor)
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
            "comparisons": [
                cmp
                for cmp in normalized_comparisons
                if hypothesis_id in {cmp["hypothesis_a_id"], cmp["hypothesis_b_id"]}
            ],
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
    """Internal helper to top hypotheses."""
    by_id = {item["id"]: item for item in hypotheses}
    top_ids = ranked_ids[:top]
    return [by_id[hypothesis_id] for hypothesis_id in top_ids if hypothesis_id in by_id]


def _hydrate_summa_triplets(hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Internal helper to hydrate summa triplets."""
    hydrated: list[dict[str, Any]] = []
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        hypothesis = dict(item)
        hypothesis["objections"] = _ensure_objections(hypothesis.get("objections"))
        hypothesis["replies"] = _ensure_replies(hypothesis.get("replies"))
        hydrated.append(hypothesis)
    return hydrated


def _sanitize_citations(
    citations: Any,
    grounded_papers: list[SemanticScholarPaper],
) -> list[dict[str, Any]]:
    """Internal helper to sanitize citations."""
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


def _fallback_grounded_citations(
    grounded_papers: list[SemanticScholarPaper],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Internal helper to fallback grounded citations."""
    fallback: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in grounded_papers:
        if not isinstance(paper, SemanticScholarPaper):
            continue
        if not paper.title or not isinstance(paper.year, int):
            continue
        if paper.year < 1800 or paper.year > 2100:
            continue
        if not paper.authors:
            continue
        if not paper.paper_id and not paper.doi:
            continue

        key = paper.paper_id or f"doi:{_normalize_doi(paper.doi)}"
        if key in seen:
            continue
        seen.add(key)

        citation = {
            "title": paper.title.strip(),
            "authors": [str(author).strip() for author in paper.authors if str(author).strip()],
            "year": int(paper.year),
        }
        if paper.paper_id:
            citation["paper_id"] = paper.paper_id.strip()
        if paper.doi:
            citation["doi"] = paper.doi.strip()
        fallback.append(citation)
        if len(fallback) >= max(1, limit):
            break
    return fallback


def _ensure_objections(raw: Any) -> list[dict[str, Any]]:
    """Internal helper to ensure objections."""
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
    """Internal helper to ensure replies."""
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


def _winner(value: Any) -> str:
    """Internal helper to winner."""
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
    """Internal helper to accumulate win."""
    if winner == "a":
        wins[a][dimension] += 1
    elif winner == "b":
        wins[b][dimension] += 1


def _accumulate_points(
    points: dict[str, dict[str, float]],
    dimension: str,
    winner: str,
    a: str,
    b: str,
) -> None:
    """Internal helper to accumulate points."""
    if winner == "a":
        points[a][dimension] += 1.0
    elif winner == "b":
        points[b][dimension] += 1.0
    else:
        points[a][dimension] += 0.5
        points[b][dimension] += 0.5


def _as_id(value: Any, fallback_counter: int) -> str:
    """Internal helper to as id."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"h{fallback_counter}"


def _as_nonempty_text(value: Any, fallback: str) -> str:
    """Internal helper to as nonempty text."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _normalize_text_list(value: Any, fallback: str) -> list[str]:
    """Internal helper to normalize text list."""
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if cleaned:
            return cleaned
    return [fallback]


def _normalize_doi(value: str | None) -> str:
    """Internal helper to normalize doi."""
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized.startswith("doi:"):
        normalized = normalized[4:].strip()
    return normalized


def _as_json(value: Any) -> str:
    """Internal helper to as json."""
    return json.dumps(value, ensure_ascii=True)


def _ensure_summa_rendering(
    *,
    raw_rendering: str,
    question: str,
    hypotheses: list[dict[str, Any]],
    ranked_ids: list[str],
    top: int,
) -> str:
    """Internal helper to ensure summa rendering."""
    cleaned = raw_rendering.strip()
    target_blocks = max(1, min(top, len(ranked_ids)))
    if _is_valid_summa_rendering(cleaned, target_blocks):
        return cleaned
    return _build_summa_rendering(question, hypotheses, ranked_ids, top)


def _is_valid_summa_rendering(rendering: str, expected_blocks: int) -> bool:
    """Internal helper to is valid summa rendering."""
    if not rendering:
        return False

    blocks = _split_summa_blocks(rendering)
    if len(blocks) < expected_blocks:
        return False
    blocks = blocks[:expected_blocks]

    required_markers = [
        "question:",
        "objections:",
        "on the contrary",
        "i answer that",
        "replies to objections",
    ]
    for block in blocks:
        lowered = block.lower()
        if any(marker not in lowered for marker in required_markers):
            return False
        if not all(f"{n}." in block for n in [1, 2, 3]):
            return False
        # Reject if "on the contrary" and "i answer that" are merged on the same line.
        for line in block.splitlines():
            line_lower = line.lower()
            if "on the contrary" in line_lower and "i answer that" in line_lower:
                return False
    return True


def _build_summa_rendering(
    question: str,
    hypotheses: list[dict[str, Any]],
    ranked_ids: list[str],
    top: int,
) -> str:
    """Internal helper to build summa rendering."""
    by_id = {
        item["id"]: item
        for item in hypotheses
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    selected_ids = [hid for hid in ranked_ids[:top] if hid in by_id]
    if not selected_ids:
        return ""

    blocks: list[str] = []
    for index, hypothesis_id in enumerate(selected_ids):
        hypothesis = by_id[hypothesis_id]
        competitor_id = _pick_competitor_id(
            ranked_ids=ranked_ids,
            selected_index=index,
            hypothesis_id=hypothesis_id,
        )
        on_the_contrary = _compose_on_the_contrary(
            hypothesis=hypothesis,
            competitor=by_id.get(competitor_id) if competitor_id else None,
        )
        block_lines: list[str] = []
        block_lines.append(f"Question: {question}")
        block_lines.append("")
        block_lines.append("Objections:")
        for objection in _ensure_objections(hypothesis.get("objections")):
            block_lines.append(f"{objection['number']}. {objection['text']}")
        block_lines.append("")
        block_lines.append("On the contrary...")
        block_lines.append(on_the_contrary)
        block_lines.append("")
        block_lines.append("I answer that...")
        block_lines.append(_as_nonempty_text(hypothesis.get("statement"), "No thesis stated."))
        block_lines.append("")
        block_lines.append("Replies to objections:")
        for reply in _ensure_replies(hypothesis.get("replies")):
            block_lines.append(
                f"Reply to Objection {reply['objection_number']}. {reply['text']}"
            )
        blocks.append("\n".join(block_lines).strip())

    if len(blocks) == 1:
        return blocks[0]
    return "\n---\n".join(blocks)


def _pick_competitor_id(
    *,
    ranked_ids: list[str],
    selected_index: int,
    hypothesis_id: str,
) -> str | None:
    """Internal helper to pick competitor id."""
    if selected_index == 0:
        if len(ranked_ids) > 1:
            return ranked_ids[1]
        return None
    if selected_index == 1:
        return ranked_ids[0] if ranked_ids else None
    return ranked_ids[0] if ranked_ids else None


def _compose_on_the_contrary(
    *,
    hypothesis: dict[str, Any],
    competitor: dict[str, Any] | None,
) -> str:
    """Internal helper to compose on the contrary."""
    if competitor is not None:
        competitor_statement = _as_nonempty_text(
            competitor.get("statement"),
            "a competing hypothesis claims otherwise",
        )
        return f"On the contrary, one may hold that {competitor_statement}"

    strongest_objection = _ensure_objections(hypothesis.get("objections"))[0]["text"]
    return f"On the contrary, the strongest objection states that {strongest_objection}"


def _split_summa_blocks(rendering: str) -> list[str]:
    """Internal helper to split summa blocks."""
    raw_blocks = re.split(r"\n\s*---\s*\n", rendering.strip())
    return [block.strip() for block in raw_blocks if block.strip()]
