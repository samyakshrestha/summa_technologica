from __future__ import annotations

from typing import Any

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from .config import Settings
from .models import SummaResponse, parse_summa_json


@CrewBase
class SummaTechnologicaCrew:
    """YAML-configured CrewAI workflow for Summa-style responses."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def problem_formulator(self) -> Agent:
        settings = Settings.from_env()
        return Agent(
            config=self.agents_config["problem_formulator"],
            llm=settings.model,
            verbose=settings.verbose,
        )

    @agent
    def objection_engineer(self) -> Agent:
        settings = Settings.from_env()
        return Agent(
            config=self.agents_config["objection_engineer"],
            llm=settings.model,
            verbose=settings.verbose,
        )

    @agent
    def respondeo_author(self) -> Agent:
        settings = Settings.from_env()
        return Agent(
            config=self.agents_config["respondeo_author"],
            llm=settings.model,
            verbose=settings.verbose,
        )

    @agent
    def scholastic_editor(self) -> Agent:
        settings = Settings.from_env()
        return Agent(
            config=self.agents_config["scholastic_editor"],
            llm=settings.model,
            verbose=settings.verbose,
        )

    @task
    def formulate_problem_task(self) -> Task:
        return Task(config=self.tasks_config["formulate_problem_task"])

    @task
    def generate_objections_task(self) -> Task:
        return Task(config=self.tasks_config["generate_objections_task"])

    @task
    def draft_summa_task(self) -> Task:
        return Task(config=self.tasks_config["draft_summa_task"])

    @task
    def quality_gate_task(self) -> Task:
        return Task(config=self.tasks_config["quality_gate_task"])

    @crew
    def crew(self) -> Crew:
        settings = Settings.from_env()
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=settings.verbose,
        )


def run_summa(
    question: str,
    domain: str | None = None,
    objective: str | None = None,
) -> SummaResponse:
    cleaned_question = question.strip()
    if not cleaned_question:
        raise ValueError("Question cannot be empty.")

    settings = Settings.from_env()
    cleaned_domain = (domain or settings.default_domain).strip() or settings.default_domain
    cleaned_objective = (objective or settings.default_objective).strip()
    if not cleaned_objective:
        cleaned_objective = settings.default_objective

    output = SummaTechnologicaCrew().crew().kickoff(
        inputs={
            "question": cleaned_question,
            "domain": cleaned_domain,
            "objective": cleaned_objective,
        }
    )
    raw = _extract_raw_output(output)
    return parse_summa_json(raw)


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

