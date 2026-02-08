"""Core utilities for crew v2 stages in Summa Technologica."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

from .config import Settings


@dataclass
class _StageFailure(Exception):
    stage: str
    message: str
    retry_attempted: bool = True

    def __str__(self) -> str:
        """Internal helper to str."""
        return f"{self.stage}: {self.message}"


def _run_stage_with_retry(
    *,
    stage_name: str,
    run_once: Callable[[str | None], dict[str, Any]],
) -> dict[str, Any]:
    """Internal helper to run stage with retry."""
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
    """Internal helper to run json stage."""
    raw = _run_agent_task(
        agent_cfg=agent_cfg,
        task_cfg=task_cfg,
        settings=settings,
        inputs=inputs,
        retry_error=retry_error,
    )
    return _parse_json_object(raw)


def _run_summa_composer_stage(
    *,
    agent_cfg: dict[str, Any],
    task_cfg: dict[str, Any],
    settings: Settings,
    inputs: dict[str, str],
    retry_error: str | None,
) -> dict[str, Any]:
    """Run the SummaComposer with tolerance for non-JSON output.

    LLMs often return the Summa rendering as plain text instead of wrapping
    it in {"summa_rendering": "..."}. This function tries JSON parsing first,
    and if that fails, treats the entire raw output as the rendering.
    """
    raw = _run_agent_task(
        agent_cfg=agent_cfg,
        task_cfg=task_cfg,
        settings=settings,
        inputs=inputs,
        retry_error=retry_error,
    )
    try:
        parsed = _parse_json_object(raw)
        if isinstance(parsed.get("summa_rendering"), str) and parsed["summa_rendering"].strip():
            return parsed
    except (ValueError, json.JSONDecodeError):
        pass

    # The agent returned raw Summa text instead of JSON. Use it directly.
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:markdown|md)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    if not cleaned:
        raise ValueError("SummaComposer returned empty output.")
    return {"summa_rendering": cleaned}


def _run_agent_task(
    *,
    agent_cfg: dict[str, Any],
    task_cfg: dict[str, Any],
    settings: Settings,
    inputs: dict[str, str],
    retry_error: str | None,
) -> str:
    """Internal helper to run agent task."""
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
    description = _render_template(description_template, inputs)
    expected_output = _render_template(expected_output_template, inputs)

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
    # Inputs are pre-rendered into description/expected_output above.
    # Passing inputs again can trigger a second formatting pass in CrewAI and
    # break on literal braces used in scientific notation or JSON examples.
    output = crew.kickoff()
    return _extract_raw_output(output)


def _extract_raw_output(output: Any) -> str:
    """Internal helper to extract raw output."""
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
    """Internal helper to parse json object."""
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


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Internal helper to load yaml config."""
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


def _render_template(template: str, inputs: dict[str, str]) -> str:
    """Render {key} placeholders while preserving unrelated literal braces.

    Using str.format() is unsafe here because task prompts include literal JSON
    examples like {"summa_rendering": "..."} that trigger KeyError.
    """
    rendered = template
    for key, value in inputs.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _require_nonempty_str(payload: dict[str, Any], key: str) -> str:
    """Internal helper to require nonempty str."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{key}' must be a non-empty string.")
    return value.strip()
