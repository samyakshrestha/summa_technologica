"""Summa Technologica scaffold package."""

from .models import SummaResponse


def run_summa(*args, **kwargs):
    from .crew import run_summa as _run_summa

    return _run_summa(*args, **kwargs)


__all__ = ["run_summa", "SummaResponse"]
