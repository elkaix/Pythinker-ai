"""OpenAI Codex Responses Provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from loguru import logger
from oauth_cli_kit import get_token as get_codex_token

from pythinker.auth.refresh_lock import refresh_lock
from pythinker.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
    stream_idle_timeout_s,
)
from pythinker.providers.openai_responses import (
    consume_sse,
    convert_messages,
    convert_tools,
)

DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_ORIGINATOR = "pythinker"

# Models with explicit support under the ChatGPT/Codex OAuth plan.
# Mirrors opencode's allow-list at packages/opencode/src/plugin/codex.ts.
# Any other gpt-X.Y with major.minor > 5.4 is also accepted (forward-compat).
_CODEX_ALLOWED_MODELS = frozenset({
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.3-codex",
    "gpt-5.4",
    "gpt-5.4-mini",
})

# Context-window caps imposed server-side by the Codex OAuth plan.
# gpt-5.5 is currently restricted; other models inherit OpenAI defaults.
_CODEX_GPT_5_5_LIMITS = {
    "context": 400_000,
    "input": 272_000,
    "output": 128_000,
}

_GPT_VERSION_RE = re.compile(r"^gpt-(\d+\.\d+)")


class OpenAICodexProvider(LLMProvider):
    """Use Codex OAuth to call the Responses API."""

    supports_progress_deltas = True

    def __init__(self, default_model: str = "openai-codex/gpt-5.5"):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model

    @staticmethod
    def is_supported_model(model: str) -> bool:
        """Return True if `model` is acceptable for the Codex OAuth backend."""
        api_id = _strip_model_prefix(model).lower()
        if "codex" in api_id:
            return True
        if api_id in _CODEX_ALLOWED_MODELS:
            return True
        m = _GPT_VERSION_RE.match(api_id)
        if m:
            try:
                return float(m.group(1)) > 5.4
            except ValueError:
                return False
        return False

    @staticmethod
    def get_model_limits(model: str) -> dict[str, int] | None:
        """Return server-side context limits, or None if unknown."""
        api_id = _strip_model_prefix(model).lower()
        if "gpt-5.5" in api_id:
            return dict(_CODEX_GPT_5_5_LIMITS)
        return None

    async def _call_codex(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        *,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Shared request logic for both chat() and chat_stream()."""
        model = model or self.default_model
        if not self.is_supported_model(model):
            logger.warning(
                "Codex OAuth model {!r} is not in the allow-list; the ChatGPT "
                "backend will likely reject the request.",
                model,
            )
        system_prompt, input_items = convert_messages(messages)

        token = await asyncio.to_thread(_locked_get_codex_token)
        headers = _build_headers(token.account_id, token.access)

        body: dict[str, Any] = {
            "model": _strip_model_prefix(model),
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(messages[:2]),
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }
        if reasoning_effort and reasoning_effort.lower() != "none":
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"] = convert_tools(tools)

        try:
            try:
                content, tool_calls, finish_reason = await _request_codex(
                    DEFAULT_CODEX_URL, headers, body, verify=True,
                    on_content_delta=on_content_delta,
                    on_tool_call_delta=on_tool_call_delta,
                )
            except Exception as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                logger.warning("SSL verification failed for Codex API; retrying with verify=False")
                content, tool_calls, finish_reason = await _request_codex(
                    DEFAULT_CODEX_URL, headers, body, verify=False,
                    on_content_delta=on_content_delta,
                    on_tool_call_delta=on_tool_call_delta,
                )
            return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish_reason)
        except Exception as e:
            response = _codex_error_response(e)
            exc_type = "CodexHTTPError" if isinstance(e, _CodexHTTPError) else type(e).__name__
            logger.warning(
                "Codex API request failed: type={} kind={} retryable={} status={} "
                "error_type={} error_code={} retry_after={} summary={}",
                exc_type,
                response.error_kind,
                response.error_should_retry,
                response.error_status_code,
                response.error_type,
                response.error_code,
                response.retry_after,
                _codex_log_summary(exc_type, response),
            )
            return response

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
        model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return await self._call_codex(messages, tools, model, reasoning_effort, tool_choice)

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
        model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        return await self._call_codex(
            messages, tools, model, reasoning_effort, tool_choice,
            on_content_delta, on_tool_call_delta=on_tool_call_delta,
        )

    def get_default_model(self) -> str:
        return self.default_model


def _locked_get_codex_token():
    """Acquire the cross-process refresh lock, then fetch/refresh the Codex token.

    Serializes token refreshes across multiple pythinker processes (e.g., serve +
    gateway) sharing the same OAuth credentials, preventing provider-side
    `refresh_token_reused` errors.
    """
    with refresh_lock("openai-codex"):
        return get_codex_token()


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _build_headers(account_id: str, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "pythinker (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


class _CodexHTTPError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        should_retry: bool | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_code = error_code
        self.should_retry = should_retry


async def _request_codex(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: bool,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    *,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str]:
    idle_timeout_s = stream_idle_timeout_s()
    async with httpx.AsyncClient(timeout=idle_timeout_s, verify=verify) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                text = await response.aread()
                raw = text.decode("utf-8", "ignore")
                retry_after = LLMProvider._extract_retry_after_from_headers(response.headers)
                error_type, error_code = LLMProvider._extract_error_type_code(raw)
                raise _CodexHTTPError(
                    _friendly_error(response.status_code, raw),
                    status_code=response.status_code,
                    retry_after=retry_after,
                    error_type=error_type,
                    error_code=error_code,
                    should_retry=_should_retry_status(
                        response.status_code, error_type, error_code, raw
                    ),
                )
            return await consume_sse(
                response, on_content_delta, on_tool_call_delta=on_tool_call_delta,
            )


def _prompt_cache_key(messages: list[dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _friendly_error(status_code: int, raw: str) -> str:
    if status_code == 429:
        return "ChatGPT usage quota exceeded or rate limit triggered. Please try again later."
    if status_code == 402:
        code = _extract_error_code(raw)
        if code == "deactivated_workspace":
            return (
                "Your ChatGPT workspace is deactivated, so Codex rejected the request. "
                "Please reconnect or re-auth with Codex: run "
                "`pythinker-ai provider login openai-codex` and sign in with a ChatGPT "
                "account that has an active Plus/Pro/Business subscription."
            )
        return (
            "ChatGPT billing rejected the request (HTTP 402). Please check your "
            "ChatGPT subscription, then re-auth with "
            "`pythinker-ai provider login openai-codex`."
        )
    if status_code in (401, 403):
        return (
            f"ChatGPT rejected the Codex credentials (HTTP {status_code}). "
            "Your token is likely expired or revoked — please re-auth with "
            "`pythinker-ai provider login openai-codex`."
        )
    return f"HTTP {status_code}: Codex API request failed"


def _codex_error_response(exc: Exception) -> LLMResponse:
    """Convert Codex transport/API failures into actionable, retryable metadata."""
    exc_type = "CodexHTTPError" if isinstance(exc, _CodexHTTPError) else type(exc).__name__
    detail = str(exc).strip()

    status_code = getattr(exc, "status_code", None)
    error_kind: str | None = None
    default_detail: str | None = None
    should_retry: bool | None = getattr(exc, "should_retry", None)

    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        error_kind = "timeout"
        default_detail = "timed out waiting for response"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, httpx.RemoteProtocolError):
        error_kind = "connection"
        default_detail = "network protocol error while reading response"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, (httpx.NetworkError, httpx.TransportError)):
        error_kind = "connection"
        default_detail = "network connection failed"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, _CodexHTTPError):
        error_kind = "http"
        default_detail = "HTTP request failed"

    if status_code is not None and should_retry is None:
        retry_content = None if int(status_code) == 429 and isinstance(exc, _CodexHTTPError) else detail
        should_retry = _should_retry_status(
            int(status_code),
            getattr(exc, "error_type", None),
            getattr(exc, "error_code", None),
            retry_content,
        )

    detail = detail or default_detail or "unexpected error"
    message = f"Error calling Codex ({exc_type}): {detail}"
    retry_after = getattr(exc, "retry_after", None) or LLMProvider._extract_retry_after(message)
    return LLMResponse(
        content=message,
        finish_reason="error",
        retry_after=retry_after,
        error_status_code=int(status_code) if status_code is not None else None,
        error_kind=error_kind,
        error_type=getattr(exc, "error_type", None),
        error_code=getattr(exc, "error_code", None),
        error_retry_after_s=retry_after,
        error_should_retry=should_retry,
    )


def _codex_log_summary(exc_type: str, response: LLMResponse) -> str:
    """Return a bounded diagnostic summary without request body or raw upstream payload."""
    if response.error_status_code is not None:
        parts = [f"HTTP {response.error_status_code}"]
        if response.error_type:
            parts.append(f"type={response.error_type}")
        if response.error_code:
            parts.append(f"code={response.error_code}")
        return " ".join(parts)

    kind = (response.error_kind or "").strip()
    if kind:
        return f"{exc_type} {kind}"

    return exc_type


def _should_retry_status(
    status_code: int,
    error_type: str | None,
    error_code: str | None,
    content: str | None,
) -> bool:
    if status_code == 429:
        return LLMProvider._is_retryable_429_response(
            LLMResponse(
                content=content or "",
                finish_reason="error",
                error_status_code=status_code,
                error_type=error_type,
                error_code=error_code,
            )
        )
    return status_code in LLMProvider._RETRYABLE_STATUS_CODES or status_code >= 500


def _extract_error_code(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str):
            return code
    return None
