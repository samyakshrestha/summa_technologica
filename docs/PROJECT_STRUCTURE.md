# Project Structure

This project has a small public API and several internal modules that split concerns cleanly.
Use this map as the first place to orient yourself before editing code.

## Runtime Entry Points

- `summa_technologica/cli.py`: CLI command wiring (`summa-technologica`) for V1/V2 runs.
- `summa_technologica/__init__.py`: package exports for programmatic use (`run_summa`, `run_summa_v2`).
- `summa_technologica/__main__.py`: `python -m summa_technologica` entrypoint.

## V1 Pipeline

- `summa_technologica/crew.py`: original CrewAI pipeline that returns classic Summa sections.
- `summa_technologica/models.py`: V1 response dataclasses and serialization helpers.
- `summa_technologica/formatter.py`: markdown/text formatting for V1 output.

## V2 Pipeline

- `summa_technologica/crew_v2.py`: high-level V2 orchestrator (stage flow and contract checks).
- `summa_technologica/crew_v2_stages.py`: stage execution internals (YAML loading, retries, CrewAI calls, parsing).
- `summa_technologica/crew_v2_postprocess.py`: normalization, ranking, citation cleanup, and Summa rendering.
- `summa_technologica/formatter_v2.py`: display formatting for structured V2 output.
- `summa_technologica/v2_contracts.py`: schema/contract validation and partial-failure payload checks.
- `schemas/hypothesis_schema.json`: JSON schema for the V2 output contract.

## Retrieval and External Data

- `summa_technologica/semantic_scholar.py`: Semantic Scholar client, retrieval merge, and grounding checks.
- `summa_technologica/semantic_scholar_cli.py`: standalone retrieval CLI helper.

## Evaluation and Benchmarks

- `summa_technologica/eval_v1.py`: benchmark runner for V1.
- `summa_technologica/eval_compare.py`: V1 vs V2 comparison runner with go/no-go checks.
- `eval/`: benchmark inputs and generated result artifacts.

## Configuration

- `summa_technologica/config.py`: environment-driven runtime settings.
- `summa_technologica/config/agents_v2.yaml`: V2 agent definitions.
- `summa_technologica/config/tasks_v2.yaml`: V2 task prompts and expected outputs.
- `.env.example`: example environment variable template.

## Tests

- `tests/`: unit tests for contracts, retrieval, helpers, models, and compare logic.
