"""Pluggable LLM providers for the MCP integration harness.

The canonical conversation format is the OpenAI Chat Completions message shape
(``{"role", "content", "tool_calls", "tool_call_id"}``) and the OpenAI tool
schema (``{"type": "function", "function": {...}}``). Each provider converts
that canonical form to/from its own wire format inside ``complete``.

Selection order for :func:`make_provider`:

1. the explicit ``name`` argument, else
2. the ``LLM_PROVIDER`` environment variable.

Supported names: ``azure-openai``, ``openai``, ``anthropic``, ``gemini``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderUnavailable(RuntimeError):
    """Raised when a provider is selected but its config/SDK is missing.

    Tests catch this and ``pytest.skip`` so CI without keys stays green.
    """


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(repr=False)


@dataclass
class AssistantTurn:
    """One model turn: free-text answer and/or a batch of tool calls."""

    text: str | None = field(default=None, repr=False)
    tool_calls: list[ToolCall] = field(default_factory=list, repr=False)
    assistant_message: dict[str, Any] | None = field(default=None, repr=False)


@runtime_checkable
class Provider(Protocol):
    name: str

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        ...


# ---------------------------------------------------------------------------
# OpenAI-family helpers (shared by Azure + OpenAI providers)
# ---------------------------------------------------------------------------


def _tool_arguments(raw: Any) -> dict[str, Any]:
    try:
        arguments = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Tool arguments must be a JSON object") from None
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object")
    return arguments


def _openai_turn_from_choice(choice: Any) -> AssistantTurn:
    if getattr(choice, "finish_reason", None) not in {"stop", "tool_calls"}:
        raise RuntimeError("Incomplete or unsupported chat completion")
    return _openai_turn_from_message(choice.message)


def _openai_turn_from_message(message: Any) -> AssistantTurn:
    calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        args = _tool_arguments(tc.function.arguments)
        calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    raw = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else None
    assistant_message = (
        {key: value for key, value in raw.items() if key in {"role", "content", "tool_calls"}}
        if raw is not None else None
    )
    return AssistantTurn(
        text=getattr(message, "content", None), tool_calls=calls,
        assistant_message=assistant_message,
    )


class AzureOpenAIProvider:
    """Azure OpenAI (works through an APIM gateway).

    ``v1`` selects stateless Responses; dated versions select Chat Completions.
    APIM subscriptions use the additional ``Ocp-Apim-Subscription-Key`` header.
    """

    name = "azure-openai"

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_version: str,
        api_key: str,
        apim_subscription_key: str | None = None,
    ) -> None:
        try:
            from openai import AsyncAzureOpenAI, AsyncOpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable(
                "openai package not installed; run `uv sync --extra llm`"
            ) from exc

        default_headers = (
            {"Ocp-Apim-Subscription-Key": apim_subscription_key}
            if apim_subscription_key
            else None
        )
        self._use_responses = api_version == "v1"
        if self._use_responses:
            self._client = AsyncOpenAI(
                base_url=endpoint.rstrip("/") + "/openai/v1/",
                api_key=api_key,
                default_headers=default_headers,
            )
        else:
            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_version=api_version,
                api_key=api_key,
                default_headers=default_headers,
            )
        self._deployment = deployment

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        if self._use_responses:
            return await self._complete_responses(messages, tools)
        # NOTE: gpt-5.x mini deployments reject `temperature`/`max_tokens`; omit
        # them and let the service use defaults.
        resp = await self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
        )
        return _openai_turn_from_choice(resp.choices[0])

    async def _complete_responses(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        inputs: list[dict[str, Any]] = []
        for message in messages:
            if "_responses_output" in message:
                inputs.extend(message["_responses_output"])
            elif message["role"] == "tool":
                inputs.append({
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message["content"],
                })
            else:
                if message.get("content") is not None:
                    inputs.append({"role": message["role"], "content": message["content"]})
                for call in message.get("tool_calls") or []:
                    inputs.append({
                        "type": "function_call", "call_id": call["id"],
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                    })

        response = await self._client.responses.create(
            model=self._deployment,
            input=inputs,
            tools=[{"type": "function", "strict": False, **tool["function"]} for tool in tools],
            store=False,
            include=["reasoning.encrypted_content"],
        )
        if response.status != "completed":
            raise RuntimeError(f"Azure response status: {response.status}")
        calls = []
        for item in response.output:
            if item.type == "function_call":
                arguments = _tool_arguments(item.arguments)
                calls.append(ToolCall(item.call_id, item.name, arguments))
        return AssistantTurn(
            text=response.output_text or None,
            tool_calls=calls,
            assistant_message={
                "role": "assistant",
                "content": response.output_text or None,
                "_responses_output": [item.model_dump(exclude_none=True) for item in response.output],
            },
        )


class OpenAICompatibleProvider:
    """OpenAI Chat Completions compatible provider."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
        tool_request_options: dict[str, Any] | None = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable(
                "openai package not installed; run `uv sync --extra llm`"
            ) from exc
        self.name = name
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        self._model = model
        self._tool_request_options = tool_request_options or {}

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "tools": tools or None,
            "tool_choice": "auto" if tools else None,
        }
        if tools:
            request.update(self._tool_request_options)
        resp = await self._client.chat.completions.create(**request)
        return _openai_turn_from_choice(resp.choices[0])


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(
        self, api_key: str, model: str, base_url: str | None = None
    ) -> None:
        super().__init__(
            name=self.name,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )


# ---------------------------------------------------------------------------
# Anthropic — converts the canonical OpenAI-style transcript to Messages API.
# ---------------------------------------------------------------------------


def _to_anthropic(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict]]:
    system: str | None = None
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system = m.get("content")
            continue
        if role == "user":
            out.append(
                {"role": "user", "content": [{"type": "text", "text": m.get("content") or ""}]}
            )
        elif role == "assistant":
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                fn = tc["function"]
                args = _tool_arguments(fn.get("arguments"))
                blocks.append(
                    {"type": "tool_use", "id": tc["id"], "name": fn["name"], "input": args}
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id"),
                "content": str(m.get("content") or ""),
            }
            # Anthropic wants tool_result blocks inside a user message; merge
            # consecutive tool results into the trailing user turn.
            if out and out[-1]["role"] == "user":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return system, out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable(
                "anthropic package not installed; run `uv sync --extra llm`"
            ) from exc
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        system, conv = _to_anthropic(messages)
        anth_tools = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters")
                or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": conv,
        }
        if system:
            kwargs["system"] = system
        if anth_tools:
            kwargs["tools"] = anth_tools
        resp = await self._client.messages.create(**kwargs)
        if getattr(resp, "stop_reason", None) not in {"end_turn", "stop_sequence", "tool_use"}:
            raise RuntimeError("Incomplete or unsupported Anthropic completion")

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        return AssistantTurn(
            text="".join(text_parts) or None, tool_calls=calls
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_provider(name: str | None = None) -> Provider:
    """Build a provider from ``name`` (arg > ``LLM_PROVIDER`` env).

    Raises :class:`ProviderUnavailable` if no provider is configured or the
    selected provider is missing required configuration so tests can skip
    cleanly.
    """
    selected = (name or os.getenv("LLM_PROVIDER") or "").strip().lower()

    if not selected:
        raise ProviderUnavailable(
            "no LLM provider configured: set LLM_PROVIDER "
            "(azure-openai | openai | anthropic | gemini)"
        )

    if selected == "azure-openai":
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        apim_key = os.getenv("AZURE_OPENAI_APIM_SUBSCRIPTION_KEY")
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or apim_key
        missing = [
            n
            for n, v in (
                ("AZURE_OPENAI_ENDPOINT", endpoint),
                ("AZURE_OPENAI_DEPLOYMENT", deployment),
                ("AZURE_OPENAI_API_KEY or AZURE_OPENAI_APIM_SUBSCRIPTION_KEY", api_key),
            )
            if not v
        ]
        if missing:
            raise ProviderUnavailable(
                "azure-openai missing config: " + ", ".join(missing)
            )
        return AzureOpenAIProvider(
            endpoint=endpoint,
            deployment=deployment,
            api_version=api_version,
            api_key=api_key,
            apim_subscription_key=apim_key,
        )

    if selected == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderUnavailable("openai missing config: OPENAI_API_KEY")
        return OpenAIProvider(
            api_key=api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )

    if selected == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ProviderUnavailable("gemini missing config: GEMINI_API_KEY")
        return OpenAICompatibleProvider(
            name="gemini",
            api_key=api_key,
            model=os.getenv("GEMINI_MODEL") or "gemini-3.8-flash",
            base_url=os.getenv("GEMINI_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    if selected == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderUnavailable("anthropic missing config: ANTHROPIC_API_KEY")
        return AnthropicProvider(
            api_key=api_key,
            model=os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5",
        )

    raise ProviderUnavailable(f"unknown LLM_PROVIDER: {selected!r}")
