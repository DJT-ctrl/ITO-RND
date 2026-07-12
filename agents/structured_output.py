"""Structured output helpers for pydantic-ai agents."""

from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_ai.output import NativeOutput

T = TypeVar("T", bound=BaseModel)


def agent_structured_output(model: type[T], resolved_model: Any = None) -> Any:
    """Prefer Gemini native JSON schema; use tool mode for TestModel in unit tests."""
    if resolved_model is not None and type(resolved_model).__name__ == "TestModel":
        return model
    return NativeOutput(model)
