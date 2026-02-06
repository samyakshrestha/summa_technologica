from .models import SummaResponse


def to_markdown(result: SummaResponse) -> str:
    lines: list[str] = []
    lines.append(f"Question: {result.question}")
    lines.append("")
    lines.append("Objections:")
    for objection in result.objections:
        lines.append(f"{objection.number}. {objection.text}")
    lines.append("")
    lines.append("On the contrary...")
    lines.append(result.on_the_contrary)
    lines.append("")
    lines.append("I answer that...")
    lines.append(result.i_answer_that)
    lines.append("")
    lines.append("Replies to objections:")
    for reply in result.replies:
        lines.append(f"Reply to Objection {reply.objection_number}. {reply.text}")

    return "\n".join(lines).strip()

