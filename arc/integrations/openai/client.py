"""Small mockable OpenAI Responses API client with strict local validation."""

import json
from time import monotonic
from typing import Any

import httpx
from pydantic import AnyHttpUrl, SecretStr, ValidationError

from arc.intelligence.errors import (
    StrategyAuthenticationError,
    StrategyInvalidOutputError,
    StrategyRateLimitError,
    StrategyRefusalError,
    StrategyUnavailableError,
)
from arc.intelligence.compatibility import compatible_actions
from arc.intelligence.prompt import STRATEGY_DEVELOPER_INSTRUCTION
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)

OPENAI_REQUEST_TIMEOUT_SECONDS = 20.0
OPENAI_MAX_OUTPUT_TOKENS = 512


class OpenAIResponsesClient:
    """Perform exactly one tool-free Responses API inference per call."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str | AnyHttpUrl = "https://api.openai.com/v1",
        timeout_seconds: float = OPENAI_REQUEST_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = str(base_url).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def model(self) -> str:
        """Return the configured model identifier."""

        return self._model

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(model={self._model!r}, "
            f"base_url={self._base_url!r})"
        )

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        """Request and locally validate one strict bounded proposal."""

        payload = _build_request_payload(self._model, context)
        started_at = monotonic()
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{self._base_url}/responses",
                    headers={
                        "Authorization": (
                            "Bearer " + self._api_key.get_secret_value()
                        ),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise StrategyUnavailableError(
                "Strategy provider request timed out"
            ) from error
        except httpx.RequestError as error:
            raise StrategyUnavailableError(
                "Strategy provider could not be reached"
            ) from error

        latency_ms = max(0, round((monotonic() - started_at) * 1000))
        _raise_for_status(response.status_code)
        try:
            response_data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise StrategyInvalidOutputError(
                "Strategy provider returned invalid response data"
            ) from error
        if not isinstance(response_data, dict):
            raise StrategyInvalidOutputError(
                "Strategy provider returned an invalid response envelope"
            )
        return _parse_response(response_data, latency_ms=latency_ms)


def _build_request_payload(
    model: str,
    context: StrategyContext,
) -> dict[str, Any]:
    context_json = json.dumps(
        {
            "allowed_actions": sorted(
                action.value
                for action in compatible_actions(
                    context.recovery_disposition
                )
            ),
            "case_context": context.model_dump(mode="json"),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "model": model,
        "store": False,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "none"},
        "instructions": STRATEGY_DEVELOPER_INSTRUCTION,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": context_json}],
            }
        ],
        "tools": [],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "arc_strategy_output",
                "strict": True,
                "schema": StrategyOutput.model_json_schema(),
            }
        },
    }


def _raise_for_status(status_code: int) -> None:
    if status_code in {401, 403}:
        raise StrategyAuthenticationError(
            "Strategy provider authentication was rejected"
        )
    if status_code == 429:
        raise StrategyRateLimitError(
            "Strategy provider rate limit or quota was reached"
        )
    if status_code >= 500:
        raise StrategyUnavailableError(
            "Strategy provider is temporarily unavailable"
        )
    if status_code < 200 or status_code >= 300:
        raise StrategyUnavailableError(
            "Strategy provider rejected the request"
        )


def _parse_response(
    response_data: dict[str, Any],
    *,
    latency_ms: int,
) -> StrategyModelResult:
    if response_data.get("status") != "completed":
        raise StrategyInvalidOutputError(
            "Strategy provider response did not complete"
        )

    provider_response_id = response_data.get("id")
    model = response_data.get("model")
    if (
        not isinstance(provider_response_id, str)
        or not provider_response_id
        or len(provider_response_id) > 100
        or not isinstance(model, str)
        or not model
        or len(model) > 100
    ):
        raise StrategyInvalidOutputError(
            "Strategy provider response metadata was invalid"
        )

    output_texts: list[str] = []
    output_items = response_data.get("output")
    if not isinstance(output_items, list):
        raise StrategyInvalidOutputError(
            "Strategy provider output was missing"
        )
    for item in output_items:
        if not isinstance(item, dict):
            raise StrategyInvalidOutputError(
                "Strategy provider output item was invalid"
            )
        content_items = item.get("content")
        if content_items is None:
            continue
        if not isinstance(content_items, list):
            raise StrategyInvalidOutputError(
                "Strategy provider content was invalid"
            )
        for content in content_items:
            if not isinstance(content, dict):
                raise StrategyInvalidOutputError(
                    "Strategy provider content item was invalid"
                )
            content_type = content.get("type")
            if content_type == "refusal":
                raise StrategyRefusalError("Strategy model refused the request")
            if content_type == "output_text":
                text_value = content.get("text")
                if not isinstance(text_value, str):
                    raise StrategyInvalidOutputError(
                        "Strategy provider text output was invalid"
                    )
                output_texts.append(text_value)
    if len(output_texts) != 1:
        raise StrategyInvalidOutputError(
            "Strategy provider returned an unexpected output count"
        )

    try:
        output = StrategyOutput.model_validate_json(output_texts[0])
    except (ValidationError, ValueError) as error:
        raise StrategyInvalidOutputError(
            "Strategy provider output failed local validation"
        ) from error

    input_tokens, output_tokens, total_tokens = _parse_usage(
        response_data.get("usage")
    )
    return StrategyModelResult(
        output=output,
        provider_response_id=provider_response_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )


def _parse_usage(
    usage: Any,
) -> tuple[int | None, int | None, int | None]:
    if usage is None:
        return None, None, None
    if not isinstance(usage, dict):
        raise StrategyInvalidOutputError(
            "Strategy provider usage metadata was invalid"
        )
    values: list[int | None] = []
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise StrategyInvalidOutputError(
                "Strategy provider usage metadata was invalid"
            )
        values.append(value)
    return values[0], values[1], values[2]
