from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


@dataclass(frozen=True)
class Objection:
    number: int
    text: str


@dataclass(frozen=True)
class Reply:
    objection_number: int
    text: str


@dataclass(frozen=True)
class SummaResponse:
    question: str
    objections: list[Objection]
    on_the_contrary: str
    i_answer_that: str
    replies: list[Reply]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "objections": [
                {"number": item.number, "text": item.text} for item in self.objections
            ],
            "on_the_contrary": self.on_the_contrary,
            "i_answer_that": self.i_answer_that,
            "replies": [
                {"objection_number": item.objection_number, "text": item.text}
                for item in self.replies
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=True)


def parse_summa_json(raw: str) -> SummaResponse:
    payload = _extract_json(raw)
    question = _require_str(payload, "question")
    on_the_contrary = _require_str(payload, "on_the_contrary")
    i_answer_that = _require_str(payload, "i_answer_that")

    objections_payload = payload.get("objections")
    replies_payload = payload.get("replies")
    if not isinstance(objections_payload, list) or len(objections_payload) != 3:
        raise ValueError("Expected 'objections' to be a list of exactly three items.")
    if not isinstance(replies_payload, list) or len(replies_payload) != 3:
        raise ValueError("Expected 'replies' to be a list of exactly three items.")

    objections: list[Objection] = []
    for item in objections_payload:
        if not isinstance(item, dict):
            raise ValueError("Each objection must be an object.")
        objections.append(
            Objection(
                number=_require_int(item, "number"),
                text=_require_str(item, "text"),
            )
        )

    replies: list[Reply] = []
    for item in replies_payload:
        if not isinstance(item, dict):
            raise ValueError("Each reply must be an object.")
        replies.append(
            Reply(
                objection_number=_require_int(item, "objection_number"),
                text=_require_str(item, "text"),
            )
        )

    objections.sort(key=lambda item: item.number)
    replies.sort(key=lambda item: item.objection_number)
    _validate_structure(objections, replies)

    return SummaResponse(
        question=question,
        objections=objections,
        on_the_contrary=on_the_contrary,
        i_answer_that=i_answer_that,
        replies=replies,
    )


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            snippet = raw[:280].replace("\n", " ")
            raise ValueError(f"No JSON object found in model output: {snippet}") from None
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object.")
    return data


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{key}' must be a non-empty string.")
    return value.strip()


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Field '{key}' must be an integer.")
    return value


def _validate_structure(objections: list[Objection], replies: list[Reply]) -> None:
    expected_numbers = [1, 2, 3]
    objection_numbers = [item.number for item in objections]
    reply_numbers = [item.objection_number for item in replies]

    if objection_numbers != expected_numbers:
        raise ValueError(
            "Objections must be numbered exactly 1, 2, 3 in sequence."
        )
    if reply_numbers != expected_numbers:
        raise ValueError(
            "Replies must target objection numbers exactly 1, 2, 3 in sequence."
        )
