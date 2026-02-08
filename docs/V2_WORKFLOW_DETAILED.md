# V2 Workflow Detailed Map

This document explains the exact V2 execution path from user question to final output.
Use it as the canonical memory of how V2 works.

## How This Project Works (Plain English)

Summa Technologica takes a scientific question and produces a research hypothesis
written in the style of Thomas Aquinas's *Summa Theologica* — with objections,
counterarguments, and replies.

It does this by chaining 7 LLM calls together, where each call builds on the
output of the previous one. Think of it like an assembly line in a factory:

```
User's question
    │
    ▼
┌──────────────────┐
│  Problem Framer  │  "What exactly are we asking? What assumptions are we making?"
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Paper Retrieval  │  Searches Semantic Scholar (a real academic database) for papers
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Literature Scout │  "What do these papers actually say? What are the key findings?"
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Hypothesis Gen   │  "Based on the evidence, here are 3-5 possible hypotheses"
└────────┬─────────┘
         ▼
┌──────────────────┐
│     Critic       │  "What's wrong with each hypothesis? Here are objections + replies"
└────────┬─────────┘
         ▼
┌──────────────────┐
│     Ranker       │  "Which hypothesis is best?" (compares them head-to-head)
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Summa Composer   │  Formats the winner into Summa Theologica style
└────────┬─────────┘
         ▼
    Final output
```

**Why is this split into so many steps?** Because one LLM call can't do all of
this well. Asking a single prompt to "find papers, generate hypotheses, critique
them, rank them, and format them" produces mediocre results. By splitting the
work, each step has a focused job and does it better.

**Why so many Python files?** Each file handles one responsibility:

| File | One-line explanation |
|------|---------------------|
| `config.py` | Reads your settings (API keys, which LLM to use) from the `.env` file |
| `crew_v2.py` | The "boss" — runs the 7 steps in order, handles errors |
| `crew_v2_stages.py` | The "worker" — actually sends prompts to the LLM and gets responses back |
| `crew_v2_postprocess.py` | The "quality checker" — cleans up messy LLM output, ranks hypotheses, builds the final rendering |
| `semantic_scholar.py` | The "librarian" — fetches real academic papers from the internet |
| `v2_contracts.py` | The "inspector" — checks that the final output has all required fields in the right format |
| `config/tasks_v2.yaml` | The prompt templates — the actual instructions given to the LLM at each step |
| `config/agents_v2.yaml` | The role descriptions — tells the LLM who it's pretending to be at each step |

**Key concept: why does "postprocessing" exist?** LLMs are unreliable. When you
ask an LLM to return JSON with specific fields, it sometimes:
- Forgets a field entirely
- Makes up citations to papers that don't exist
- Merges two sections into one line
- Returns slightly different formats each time

The postprocessing layer catches all of these problems and fixes them. If the
LLM forgot to include objections, it adds placeholder text. If the LLM cited
a fake paper, it removes that citation and substitutes a real one from Semantic
Scholar. This is why the pipeline is reliable even though individual LLM calls
are not.

---

## Technical Reference (for debugging and development)

Everything below is the detailed technical map. You don't need to read this
to understand the project — the section above covers the "what" and "why."
This section covers the "exactly how, line by line."

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

Think of V2 as a restaurant:

| Role | File | What it does |
|------|------|-------------|
| **Restaurant manager** | `crew_v2.py` | Decides the order of operations, handles problems, talks to the customer |
| **Chef** | `crew_v2_stages.py` | Actually cooks the food (sends prompts to the LLM, gets responses) |
| **Quality control** | `crew_v2_postprocess.py` | Checks the dish before it leaves the kitchen (cleans up messy output) |
| **Health inspector** | `v2_contracts.py` | Final check that the dish meets all regulations (schema validation) |
| **Grocery supplier** | `semantic_scholar.py` | Brings in fresh ingredients (real academic papers from the internet) |
| **Recipe book** | `config/tasks_v2.yaml` | The instructions the chef follows (prompt templates) |
| **Staff roster** | `config/agents_v2.yaml` | Who the chef pretends to be for each dish (agent role descriptions) |
| **Menu / settings** | `config.py` | What restaurant we're running today (which LLM, which API keys) |

The key insight: **the LLM (chef) never sees the other files directly.**
The manager (`crew_v2.py`) reads the recipe (`tasks_v2.yaml`), fills in the
specifics, hands it to the chef (`crew_v2_stages.py`), gets the result back,
sends it through quality control (`crew_v2_postprocess.py`), and then the
health inspector (`v2_contracts.py`) gives final approval.
