from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from jobpilot.config import get_settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class AIUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class AIResult(Generic[T]):
    output: T
    usage: AIUsage


class AIError(Exception):
    """A failed AI call. `retryable` tells the orchestrator whether to try again later."""

    def __init__(self, code: str, message: str, retryable: bool = False, usage: AIUsage | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.usage = usage


class AIProvider(Protocol):
    name: str
    model: str

    def structured(self, *, system: str, user: str, schema: type[T], max_tokens: int = 2048) -> AIResult[T]:
        """One request, one Pydantic-validated result. Raises AIError."""
        ...

    def chat(self, *, system: str, messages: list[dict], max_tokens: int = 1500) -> tuple[str, AIUsage]:
        """One conversation turn: reply text and usage. Raises AIError."""
        ...


def get_provider() -> AIProvider | None:
    """The configured provider, or None when no key is set (callers fall back to rules)."""
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    from jobpilot.ai.claude import ClaudeProvider

    return ClaudeProvider(api_key=s.anthropic_api_key, model=s.claude_model, timeout_s=s.ai_timeout_s)
