"""Transport-agnostic MCP host: agent loop + in-memory / stdio client sessions.

The agent loop speaks the OpenAI-canonical message format (see
``providers.py``) and is independent of which provider produced a turn and of
which transport carries the MCP session, so the same loop drives:

* L1 — :class:`~providers.StubProvider` + in-memory fixture tools
* L2 — a real provider + in-memory fixture tools (no portal login, no PII)
* L3 — a real provider + a real stdio server (real portal login; opt-in)
"""
from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from unittest import mock

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

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
    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def called_tool_names(self) -> list[str]:
        return [tc.name for tc in self.tool_calls]


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
    turn: AssistantTurn = AssistantTurn(text="")

    for _ in range(max_turns):
        turn = await provider.complete(messages, openai_tools)

        if not turn.tool_calls:
            return AgentRun(
                final_text=turn.text or "", tool_calls=made, messages=messages
            )

        messages.append(
            {
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
                content = call_result_to_text(result)
            except Exception as exc:  # surface tool errors back to the model
                content = f"ERROR calling {tc.name}: {exc}"
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": content}
            )

    return AgentRun(
        final_text=turn.text or "", tool_calls=made, messages=messages
    )


# ---------------------------------------------------------------------------
# In-memory client (L1/L2) — optionally patch scrapers with fixtures
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for the Playwright-backed session: ``run(action)`` -> action(page)."""

    async def run(self, action):
        return await action(None)


def _apply_fixture_patches(stack: AsyncExitStack) -> None:
    """Patch cache + session factories + scrapers so tools return fixtures."""
    from yonsei_portal_mcp import cache, server
    from yonsei_portal_mcp.scrapers import erp, learnus, library, seats

    from . import fixtures as fx

    async def _no_cache(key, ttl, producer):
        return await producer()

    def patch(target, attr, value):
        stack.enter_context(mock.patch.object(target, attr, value))

    patch(cache, "cached", _no_cache)
    patch(server, "get_session", lambda: _FakeSession())
    patch(server, "get_erp_session", lambda: _FakeSession())
    patch(server, "get_library_session", lambda: _FakeSession())

    async def courses(page=None, **k):
        return fx.COURSES

    async def deadlines(page=None, course_id=None, **k):
        data = fx.DEADLINES
        if course_id:
            data = [d for d in data if d["course_id"] == course_id]
        return data

    async def notices(page=None, scope="all", **k):
        return fx.notices(scope)

    async def notice_body(page=None, url=None, **k):
        return fx.NOTICE_BODY

    async def attendance(page=None, course_id=None, **k):
        return fx.ATTENDANCE

    patch(learnus, "fetch_courses", courses)
    patch(learnus, "fetch_deadlines", deadlines)
    patch(learnus, "fetch_notices", notices)
    patch(learnus, "fetch_notice_body", notice_body)
    patch(learnus, "fetch_attendance", attendance)

    async def loans(page=None, **k):
        return fx.LOANS

    async def seat_rooms(page=None, **k):
        return fx.SEAT_ROOMS

    patch(library, "fetch_my_loans", loans)
    patch(library, "fetch_seat_rooms", seat_rooms)

    async def fetch_seats(seat_type=None, **k):
        return fx.seats(seat_type)

    patch(seats, "fetch_seats", fetch_seats)

    async def profile(page=None, **k):
        return fx.PROFILE

    async def timetable(page=None, **k):
        return fx.TIMETABLE

    async def grades(page=None, **k):
        return fx.GRADES

    patch(erp, "fetch_student_profile", profile)
    patch(erp, "fetch_timetable", timetable)
    patch(erp, "fetch_grades", grades)


@asynccontextmanager
async def inmemory_client(*, mock_tools: bool = True) -> AsyncIterator[ClientSession]:
    """Yield a ClientSession wired to the real FastMCP server in-process.

    When ``mock_tools`` is True the scrapers are patched with fixtures, so no
    network/login/PII is involved (L1/L2). When False the tools hit the real
    portal (used by an explicitly opted-in caller).
    """
    from yonsei_portal_mcp import server

    async with AsyncExitStack() as stack:
        if mock_tools:
            _apply_fixture_patches(stack)
        client = await stack.enter_async_context(
            create_connected_server_and_client_session(server.mcp._mcp_server)
        )
        await client.initialize()
        yield client


# ---------------------------------------------------------------------------
# stdio client (L3) — real server subprocess, real portal login
# ---------------------------------------------------------------------------


@asynccontextmanager
async def stdio_client_session(
    *, python: str | None = None
) -> AsyncIterator[ClientSession]:
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=python or os.getenv("PYTHON", "python"),
        args=["-m", "yonsei_portal_mcp"],
        env=os.environ.copy(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
