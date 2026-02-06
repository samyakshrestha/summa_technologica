from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model: str
    verbose: bool
    default_domain: str
    default_objective: str

    @staticmethod
    def from_env() -> "Settings":
        model = (
            os.getenv("SUMMA_MODEL")
            or os.getenv("MODEL")
            or os.getenv("OPENAI_MODEL_NAME")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4o-mini"
        )
        return Settings(
            model=model,
            verbose=_as_bool(os.getenv("SUMMA_VERBOSE", "false")),
            default_domain=os.getenv("SUMMA_DEFAULT_DOMAIN", "general science"),
            default_objective=os.getenv(
                "SUMMA_DEFAULT_OBJECTIVE",
                "Brainstorm original, testable, high-leverage ideas.",
            ),
        )
