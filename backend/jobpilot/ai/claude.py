"""Claude via the official Anthropic Python SDK.

Uses structured outputs (`client.messages.parse(output_format=Model)`), which
constrains the response to the Pydantic model's JSON schema; the SDK then
validates it against the original model. The key stays on the server.
"""

import logging

import anthropic
from pydantic import BaseModel, ValidationError

from jobpilot.ai.provider import AIError, AIResult, AIUsage, T
from jobpilot.config import get_settings

log = logging.getLogger("jobpilot.ai")

# USD per million tokens (input, output). Base rates for prompts under 100k tokens,
# from https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-17).
# Override with JOBPILOT_AI_PRICES='{"model": [in, out]}' when prices change.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
DEFAULT_MODEL = "claude-haiku-5-5"  # recommended for high-volume classification and extraction


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = {**DEFAULT_PRICES, **{k: tuple(v) for k, v in get_settings().ai_prices.items()}}
    p_in, p_out = prices.get(model, (0.0, 0.0))
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = 60.0,
                 client: anthropic.Anthropic | None = None):
        self.model = model or DEFAULT_MODEL
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff.
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    def structured(self, *, system: str, user: str, schema: type[T], max_tokens: int = 2048) -> AIResult[T]:
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.RateLimitError as e:
            raise AIError("rate_limited", "Claude API rate limit reached", retryable=True) from e
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            raise AIError("unreachable", "Claude API timed out or was unreachable", retryable=True) from e
        except anthropic.AuthenticationError as e:
            raise AIError("auth_failed", "Claude API key was rejected") from e
        except anthropic.BadRequestError as e:
            raise AIError("bad_request", f"Claude API rejected the request: {e.message}"[:300]) from e
        except anthropic.APIStatusError as e:
            raise AIError("api_error", f"Claude API error {e.status_code}", retryable=e.status_code >= 500) from e
        except ValidationError as e:
            raise AIError("invalid_output", "Claude output did not match the schema") from e

        usage = AIUsage(
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost_usd=cost_usd(self.model, resp.usage.input_tokens, resp.usage.output_tokens),
        )
        if resp.stop_reason == "refusal":
            raise AIError("refused", "Claude declined to produce this output", usage=usage)
        if resp.stop_reason == "max_tokens":
            raise AIError("truncated", "Output hit the token limit", retryable=True, usage=usage)
        parsed = resp.parsed_output
        if not isinstance(parsed, BaseModel):
            raise AIError("invalid_output", "No structured output in the response", usage=usage)
        return AIResult(output=parsed, usage=usage)
