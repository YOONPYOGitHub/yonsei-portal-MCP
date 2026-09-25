"""Transport-agnostic MCP host: agent loop + stdio client session.

The agent loop speaks the OpenAI-canonical message format (see
``providers.py``) and is independent of which provider produced a turn, so the
same loop drives a real provider against a real stdio server (real portal
login; opt-in via ``RUN_LIVE_LLM=1``).
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from mcp import ClientSession

from .providers import AssistantTurn, Provider, ToolCall

DEFAULT_SYSTEM_PROMPT = (
    "당신은 연세대학교 포털/LearnUs/도서관 정보를 조회해 주는 한국어 비서입니다. "
    "사용자의 질문에 답하려면 반드시 제공된 도구를 호출해서 실제 데이터를 가져오세요. "
    "도구 결과에 근거해서만 간결하게 답하고, 추측하지 마세요. "
    "마감일(deadlines) 항목의 kind 필드를 반드시 확인하세요. "
    "kind 가 'progress'(강의 수강기간 종료)나 'completion'(온라인 수료 권장일)이면 "
    "실제 제출 과제가 아니므로 '과제 마감'이라고 부르지 말고 '강의 진도/수료 마감'으로 "
    "구분해 안내하고, 제출 과제가 정말 없으면 없다고 분명히 말하세요."
)


@dataclass
class AgentRun:
    final_text: str = field(repr=False)
    tool_calls: list[ToolCall] = field(default_factory=list, repr=False)
    messages: list[dict[str, Any]] = field(default_factory=list, repr=False)
    tool_errors: list[str] = field(default_factory=list)
    exhausted: bool = False

    @property
    def called_tool_names(self) -> list[str]:
        return [tc.name for tc in self.tool_calls]


def agent_run_error(run: AgentRun, expected_tools: set[str] | None = None) -> str | None:
    if run.tool_errors:
        return "MCP tool returned an error (payload suppressed)"
    if run.exhausted:
        return "Agent turn limit reached"
    if not run.final_text.strip():
        return "Empty final answer"
    if expected_tools is not None and not expected_tools.intersection(run.called_tool_names):
        return "Expected tool was not called"
    return None


# ---------------------------------------------------------------------------
# MCP <-> OpenAI bridging
# ---------------------------------------------------------------------------


def mcp_tools_to_openai(list_tools_result: Any) -> list[dict[str, Any]]:
    """Convert ``session.list_tools()`` output to OpenAI tool schemas."""
    out: list[dict[str, Any]] = []
    for tool in list_tools_result.tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def call_result_to_text(result: Any) -> str:
    """Flatten an MCP ``CallToolResult`` into text for the model."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        try:
            return json.dumps(structured, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else "(no content)"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


async def run_agent(
    session: ClientSession,
    provider: Provider,
    user_message: str,
    *,
    system: str | None = DEFAULT_SYSTEM_PROMPT,
    max_turns: int = 6,
) -> AgentRun:
    """Run a tool-calling loop until the model answers or ``max_turns`` is hit."""
    openai_tools = mcp_tools_to_openai(await session.list_tools())

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})

    made: list[ToolCall] = []
    tool_errors: list[str] = []
    turn: AssistantTurn = AssistantTurn(text="")

    for _ in range(max_turns):
        turn = await provider.complete(messages, openai_tools)

        if not turn.tool_calls:
            return AgentRun(
                final_text=turn.text or "", tool_calls=made, messages=messages,
                tool_errors=tool_errors,
            )

        messages.append(
            turn.assistant_message or {
                "role": "assistant",
                "content": turn.text or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in turn.tool_calls
                ],
            }
        )

        for tc in turn.tool_calls:
            made.append(tc)
            try:
                result = await session.call_tool(tc.name, tc.arguments)
                if getattr(result, "isError", False):
                    tool_errors.append(tc.name)
                content = call_result_to_text(result)
            except Exception as exc:  # surface tool errors back to the model
                tool_errors.append(tc.name)
                content = f"ERROR calling {tc.name}: {type(exc).__name__}"
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": content}
            )

    return AgentRun(
        final_text="", tool_calls=made, messages=messages,
        tool_errors=tool_errors, exhausted=True,
    )


# ---------------------------------------------------------------------------
# stdio client (live) — real server subprocess, real portal login
# ---------------------------------------------------------------------------


@asynccontextmanager
async def stdio_client_session(
    *, python: str | None = None
) -> AsyncIterator[ClientSession]:
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=python or os.getenv("PYTHON") or sys.executable,
        args=["-m", "yonsei_portal_mcp"],
        env=os.environ.copy(),
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
