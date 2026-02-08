"""Settings — reads configuration from environment variables and .env file.

All pipeline settings (which LLM model to use, API keys, default domain, etc.)
are loaded here. The Settings dataclass is created once at the start of each
pipeline run and passed to every stage.
"""

from dataclasses import dataclass
import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - fallback for minimally provisioned envs
    def load_dotenv() -> bool:
        """Load dotenv."""
        return False

load_dotenv()


def _as_bool(value: str, default: bool = False) -> bool:
    """Internal helper to as bool."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model: str
    verbose: bool
    default_domain: str
    default_objective: str
    semantic_scholar_api_key: str | None
    semantic_scholar_base_url: str
    semantic_scholar_timeout_seconds: float

    @staticmethod
    def from_env() -> "Settings":
        """From env."""
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
            semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
            semantic_scholar_base_url=os.getenv(
                "SEMANTIC_SCHOLAR_BASE_URL",
                "https://api.semanticscholar.org",
            ),
            semantic_scholar_timeout_seconds=float(
                os.getenv("SEMANTIC_SCHOLAR_TIMEOUT_SECONDS", "20.0")
            ),
        )
