# V2 Workflow Detailed Map

This document explains the exact V2 execution path from user question to final output.
Use it as the canonical memory of how V2 works.

## 1) Entry Points

## CLI path
- File: `summa_technologica/cli.py`
- Function: `main()`
- What happens:
  - Parses CLI args (`question`, `--mode`, `--domain`, `--objective`, `--top`, `--format`).
  - Loads settings from environment via `Settings.from_env()`.
  - Calls `run_summa_v2(...)` when `--mode v2`.
  - Formats output using `to_markdown_v2(...)` or JSON dump.

## Programmatic path
- File: `summa_technologica/__init__.py`
- Function: `run_summa_v2(...)`
- What happens:
  - Thin wrapper that imports and forwards to `summa_technologica/crew_v2.py`.

## 2) Configuration and Prompt Sources

## Environment config
- File: `summa_technologica/config.py`
- Object: `Settings`
- Values used by V2:
  - model (`SUMMA_MODEL` etc.)
  - default domain/objective
  - Semantic Scholar API settings

## Agent/task prompt definitions
- Files:
  - `summa_technologica/config/agents_v2.yaml`
  - `summa_technologica/config/tasks_v2.yaml`
- Loaded in `crew_v2.py` via `_load_yaml_config(...)` from `crew_v2_stages.py`.

## 3) Orchestrator (Control Plane)

- File: `summa_technologica/crew_v2.py`
- Function: `run_summa_v2(...)`
- Role:
  - Owns stage ordering.
  - Owns retry policy per stage.
  - Owns final contract validation and partial-failure behavior.

Stage order inside `run_summa_v2(...)`:
1. `problem_framer`
2. retrieval (Semantic Scholar)
3. `literature_scout`
4. `hypothesis_generator`
5. optional diversity retry
6. `critic`
7. optional diversity retry
8. `ranker`
9. `summa_composer`
10. final validation and possible composer retry

## 4) Stage Execution Layer (CrewAI Calls)

- File: `summa_technologica/crew_v2_stages.py`
- Main functions:
  - `_run_stage_with_retry(...)`: retry-once wrapper.
  - `_run_json_stage(...)`: run a stage and parse strict JSON object.
  - `_run_summa_composer_stage(...)`: tolerant parser for composer output (JSON or raw text).
  - `_run_agent_task(...)`: actually instantiates `Agent`, `Task`, `Crew`, then `kickoff()`.

Important implementation details:
- Prompt templates are pre-rendered by `_render_template(...)` to avoid literal-brace formatting failures.
- `kickoff()` is called without `inputs=...` because prompt text is already materialized.
- `_parse_json_object(...)` strips code fences and extracts embedded JSON objects if needed.

## 5) Retrieval Layer

- File: `summa_technologica/semantic_scholar.py`
- Main path:
  - `retrieve_grounded_papers(...)`
    - builds dual queries (`question` + `refined_query`)
    - calls Semantic Scholar search
    - merges and deduplicates papers
    - returns `RetrievalResult`

Output is fed to generation and grounding logic as `retrieval_result` and `stage_outputs["retrieval"]`.

## 6) Postprocessing Layer (Normalization, Ranking, Rendering)

- File: `summa_technologica/crew_v2_postprocess.py`

## Hypothesis normalization
- `_normalize_generated_hypotheses(...)`
- `_normalize_critic_hypotheses(...)`

These functions:
- enforce required textual fields with fallbacks,
- sanitize citations against grounded retrieval,
- inject fallback grounded citations when model returns none,
- ensure objection/reply triplets exist.

## Ranking
- `_apply_pairwise_ranking(...)`

This function:
- normalizes pairwise comparison records,
- fills missing pairs as ties,
- computes wins + points by dimension,
- converts to 1–5 scores and weighted overall,
- returns ranked hypothesis IDs and enriched hypothesis objects.

## Summa rendering
- `_ensure_summa_rendering(...)`
- `_is_valid_summa_rendering(...)`
- `_build_summa_rendering(...)`

This layer:
- accepts model-produced rendering if structurally valid,
- otherwise builds deterministic fallback Summa text from ranked hypotheses.

## 7) Contract Validation Layer

- File: `summa_technologica/v2_contracts.py`
- Schema file: `schemas/hypothesis_schema.json`

Validation happens at end of orchestrator:
- `validate_v2_payload(final_payload, grounded_papers=...)`

Checks include:
- JSON schema compliance,
- hypothesis ID/ranking consistency,
- objections/replies numbering,
- pairwise ID references,
- score formula consistency,
- citation grounding against retrieved papers.

## 8) Failure Model

V2 does not silently swallow stage failure.
If a stage fails after retry, orchestrator returns a **partial failure payload**:
- `question`, `domain`
- possibly partial hypotheses/ranking/rendering
- `stage_outputs` collected so far
- `error` object: stage/message/retry_attempted

This payload is built via `build_partial_failure_payload(...)` in `v2_contracts.py`.

## 9) Output Formatting

- File: `summa_technologica/formatter_v2.py`
- Function: `to_markdown_v2(payload)`

Formatter behavior:
- prints question/domain,
- prints ranked hypotheses and overall scores,
- prints `summa_rendering`,
- if `error` exists, prints pipeline error section.

## 10) End-to-End Call Trace (CLI, V2)

```text
summa-technologica ... --mode v2
  -> cli.py:main
     -> config.py:Settings.from_env
     -> crew_v2.py:run_summa_v2
        -> crew_v2_stages.py:_load_yaml_config (agents/tasks)
        -> crew_v2_stages.py:_run_stage_with_retry + _run_json_stage (problem_framer)
        -> semantic_scholar.py:retrieve_grounded_papers
        -> crew_v2_stages.py:_run_stage_with_retry + _run_json_stage (literature_scout)
        -> crew_v2_stages.py:_run_stage_with_retry + _run_json_stage (hypothesis_generator)
        -> crew_v2_postprocess.py:_normalize_generated_hypotheses
        -> (optional) crew_v2.py:_regenerate_for_diversity
        -> crew_v2_stages.py:_run_stage_with_retry + _run_json_stage (critic)
        -> crew_v2_postprocess.py:_normalize_critic_hypotheses
        -> crew_v2_stages.py:_run_stage_with_retry + _run_json_stage (ranker)
        -> crew_v2_postprocess.py:_apply_pairwise_ranking
        -> crew_v2_postprocess.py:_hydrate_summa_triplets
        -> crew_v2_stages.py:_run_stage_with_retry + _run_summa_composer_stage
        -> crew_v2_postprocess.py:_ensure_summa_rendering
        -> v2_contracts.py:validate_v2_payload
        -> (on final validation fail) one composer retry, revalidate
        -> return final payload or partial failure payload
     -> formatter_v2.py:to_markdown_v2 (unless --format json)
```

## 11) Files and Responsibilities (Quick Reference)

- `summa_technologica/cli.py`: CLI I/O boundary.
- `summa_technologica/config.py`: runtime settings.
- `summa_technologica/crew_v2.py`: orchestration + error contract wiring.
- `summa_technologica/crew_v2_stages.py`: stage execution engine.
- `summa_technologica/crew_v2_postprocess.py`: data shaping, ranking, rendering.
- `summa_technologica/semantic_scholar.py`: evidence retrieval and grounding primitives.
- `summa_technologica/v2_contracts.py`: schema/contract enforcement.
- `summa_technologica/formatter_v2.py`: display formatting.
- `summa_technologica/config/*.yaml`: prompt and agent behavior definitions.
- `schemas/hypothesis_schema.json`: contract schema.

## 12) Practical Mental Model
Think of V2 as three layers:
1. **Execution layer** runs prompt stages (`crew_v2_stages.py`).
2. **Postprocess layer** turns model text into deterministic structured outputs (`crew_v2_postprocess.py`).
3. **Contract layer** rejects structurally invalid outputs (`v2_contracts.py`).

`crew_v2.py` is the conductor that connects those three layers.
