from dataclasses import dataclass
import json
from time import monotonic
from typing import Any, Generic, Protocol, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)
Message = dict[str, str]


class ModelFailure(RuntimeError):
    def __init__(self, code: str, *, transient: bool = False):
        super().__init__(code)
        self.code = code
        self.transient = transient


@dataclass(frozen=True)
class Generated(Generic[T]):
    value: T | str
    provider: str
    model: str
    latency_ms: int
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class Provider(Protocol):
    def generate_structured(self, messages: list[Message], schema: type[T], *,
                            temperature: float, max_tokens: int) -> Generated[T]: ...
    def generate_text(self, messages: list[Message], *,
                      temperature: float, max_tokens: int) -> Generated: ...


class ChatCompletionsProvider:
    def __init__(self, key: str, model: str, timeout: float, client: httpx.Client | None = None):
        if not key.strip() or not model.strip():
            raise ModelFailure("missing_model_configuration")
        self._key, self.model, self.timeout = key, model, timeout
        self._client = client

    def _response_format(self, schema):
        return {"type": "json_object"}

    def _generate(self, messages, temperature, max_tokens, schema=None):
        start = monotonic()
        payload = {
            "model": self.model, "messages": messages, "temperature": temperature,
            "max_completion_tokens": max_tokens, **self.request_options,
        }
        if schema is not None:
            payload["response_format"] = self._response_format(schema)
            payload["messages"] = [
                {"role": "system", "content": "Return JSON matching " + json.dumps(schema.model_json_schema())},
                *messages,
            ]
        try:
            post = self._client.post if self._client else httpx.post
            response = post(
                self.endpoint, json=payload,
                headers={"Authorization": "Bearer " + self._key}, timeout=self.timeout,
            )
        except httpx.TimeoutException as error:
            raise ModelFailure("provider_timeout", transient=True) from error
        except httpx.RequestError as error:
            raise ModelFailure("provider_connection", transient=True) from error
        if response.status_code == 429 or response.status_code >= 500:
            raise ModelFailure("provider_unavailable", transient=True)
        if response.status_code in (401, 403):
            raise ModelFailure("provider_credentials_invalid")
        if response.is_error:
            raise ModelFailure("provider_request_rejected")
        try:
            body = response.json()
            choice = body["choices"][0]
            value = choice["message"]["content"]
            finish = choice.get("finish_reason")
            usage = body.get("usage") or {}
            if not isinstance(usage, dict) or (finish is not None and not isinstance(finish, str)):
                raise ModelFailure("model_output_invalid")
            if finish == "length":
                raise ModelFailure("model_token_limit")
            if not isinstance(value, str) or not value.strip():
                raise ModelFailure("model_empty")
            if schema is not None:
                value = schema.model_validate_json(value)
            prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
            return Generated(
                value, self.provider_name, self.model, int((monotonic() - start) * 1000),
                response.headers.get("x-request-id"),
                prompt if type(prompt) is int and prompt >= 0 else None,
                completion if type(completion) is int and completion >= 0 else None,
                finish,
            )
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise ModelFailure("model_output_invalid") from error

    def generate_structured(self, messages, schema, *, temperature, max_tokens):
        return self._generate(messages, temperature, max_tokens, schema)

    def generate_text(self, messages, *, temperature, max_tokens):
        return self._generate(messages, temperature, max_tokens)


class OpenAIProvider(ChatCompletionsProvider):
    provider_name = "openai"
    endpoint = "https://api.openai.com/v1/chat/completions"
    request_options = {"store": False}


class GeminiProvider(ChatCompletionsProvider):
    provider_name = "gemini"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    request_options = {"reasoning_effort": "low"}

    def _response_format(self, schema):
        return {"type": "json_schema", "json_schema": {
            "name": schema.__name__, "schema": schema.model_json_schema(), "strict": True,
        }}


class MockProvider:
    def __init__(self, responder=None):
        self.responder = responder
        self.calls = 0

    def generate_structured(self, messages, schema, *, temperature, max_tokens):
        from .conversation_models import mock_analysis

        self.calls += 1
        try:
            data = self.responder(messages, schema) if self.responder else mock_analysis(messages, schema)
            return Generated(schema.model_validate(data), "mock", "deterministic", 0, uuid4().hex)
        except ValidationError as error:
            raise ModelFailure("model_output_invalid") from error

    def generate_text(self, messages, *, temperature, max_tokens):
        return Generated("I can help with your insurance question.", "mock", "deterministic", 0)


def create_provider(settings) -> Provider:
    if settings.llm_provider == "mock":
        return MockProvider()
    provider = {"openai": OpenAIProvider, "gemini": GeminiProvider}[settings.llm_provider]
    return provider(settings.llm_api_key.get_secret_value(), settings.llm_model,
                    settings.llm_timeout_seconds)
