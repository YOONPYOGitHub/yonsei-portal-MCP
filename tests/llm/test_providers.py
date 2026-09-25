from __future__ import annotations

import asyncio
import importlib
import os
import sys
import traceback
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from .providers import AssistantTurn, ProviderUnavailable, _openai_turn_from_message, make_provider
from .mcp_host import run_agent


@pytest.mark.parametrize("module_name", [
    "tests.llm.conftest", "tests.llm.demo", "tests.llm.dump_tools",
    "tests.llm.scenarios", "yonsei_portal_mcp.config",
])
@pytest.mark.parametrize("opt_out", ["0", "false", ""])
def test_dotenv_import_preserves_explicit_opt_out(monkeypatch, module_name, opt_out):
    monkeypatch.setenv("RUN_LIVE_LLM", opt_out)
    monkeypatch.setenv("LLM_PROVIDER", "explicit-provider")
    calls = []

    def synthetic_dotenv(*args, override=False, **kwargs):
        calls.append(override)
        for name, value in {"RUN_LIVE_LLM": "1", "LLM_PROVIDER": "dotenv-provider"}.items():
            if override or name not in os.environ:
                monkeypatch.setenv(name, value)

    monkeypatch.setattr("dotenv.load_dotenv", synthetic_dotenv)
    module = importlib.import_module(module_name)
    importlib.reload(module)
    assert calls
    assert os.environ["RUN_LIVE_LLM"] == opt_out
    assert os.environ["LLM_PROVIDER"] == "explicit-provider"


class _FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content="ok", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class _FakeAsyncOpenAI:
    instances: list["_FakeAsyncOpenAI"] = []

    def __init__(self, *, api_key: str, base_url: str | None = None, **kwargs) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.options = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions())
        self.responses = _FakeResponses()
        self.instances.append(self)


class _FakeResponses:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.output = []
        self.status = "completed"

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            output=self.output, output_text="ok", status=self.status,
        )


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch):
    _FakeAsyncOpenAI.instances.clear()
    monkeypatch.setitem(
        sys.modules, "openai", SimpleNamespace(
            AsyncOpenAI=_FakeAsyncOpenAI, AsyncAzureOpenAI=_FakeAsyncOpenAI,
        )
    )


@pytest.mark.asyncio
async def test_gemini_uses_openai_compatibility(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)

    provider = make_provider("gemini")
    await provider.complete(
        [{"role": "user", "content": "시간표를 알려줘"}],
        [
            {
                "type": "function",
                "function": {
                    "name": "get_my_timetable",
                    "description": "시간표 조회",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    client = _FakeAsyncOpenAI.instances[-1]
    request = client.chat.completions.requests[-1]
    assert provider.name == "gemini"
    assert client.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert request["model"] == "gemini-3.8-flash"
    assert request["tool_choice"] == "auto"
    assert "max_tokens" not in request


@pytest.mark.asyncio
async def test_openai_compatibility_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")

    provider = make_provider("openai")
    await provider.complete([{"role": "user", "content": "안녕"}], [])

    client = _FakeAsyncOpenAI.instances[-1]
    request = client.chat.completions.requests[-1]
    assert provider.name == "openai"
    assert client.base_url == "https://example.test/v1"
    assert request["model"] == "test-model"
    assert "max_tokens" not in request
    assert request["tools"] is None
    assert request["tool_choice"] is None


@pytest.mark.parametrize(
    ("provider_name", "key_name"),
    [
        ("gemini", "GEMINI_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ],
)
def test_provider_requires_api_key(
    monkeypatch, provider_name: str, key_name: str
) -> None:
    monkeypatch.delenv(key_name, raising=False)

    with pytest.raises(ProviderUnavailable, match=key_name):
        make_provider(provider_name)


def test_openai_turn_preserves_tool_metadata() -> None:
    raw = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "get_my_timetable", "arguments": "{}"},
            "extra_content": {"google": {"thought_signature": "test-signature"}},
        }],
    }
    message = SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="get_my_timetable", arguments="{}"),
        )],
        model_dump=lambda **kwargs: raw,
    )
    turn = _openai_turn_from_message(message)
    assert turn.tool_calls[0].name == "get_my_timetable"
    assert turn.assistant_message == raw


def _azure_provider(monkeypatch, version="v1"):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://gateway.example.test/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "custom-deployment")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", version)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    monkeypatch.setenv("AZURE_OPENAI_APIM_SUBSCRIPTION_KEY", "test-apim-key")
    return make_provider("azure-openai")


@pytest.mark.asyncio
async def test_azure_v1_uses_stateless_responses(monkeypatch) -> None:
    provider = _azure_provider(monkeypatch)
    messages = [{"role": "system", "content": "Use tools."}, {"role": "user", "content": "Hi"}]
    tools = [{"type": "function", "function": {
        "name": "get_my_timetable", "description": "Timetable",
        "parameters": {"type": "object", "properties": {}},
    }}]
    await provider.complete(messages, tools)
    client = _FakeAsyncOpenAI.instances[-1]
    assert client.base_url == "https://gateway.example.test/openai/v1/"
    assert client.options["default_headers"]["Ocp-Apim-Subscription-Key"] == "test-apim-key"
    request = client.responses.requests[-1]
    assert request["model"] == "custom-deployment"
    assert request["input"] == messages
    assert request["store"] is False
    assert "reasoning.encrypted_content" in request["include"]
    assert request["tools"][0]["name"] == "get_my_timetable"
    assert request["tools"][0]["strict"] is False
    assert "api_version" not in client.options


@pytest.mark.asyncio
async def test_azure_responses_replays_reasoning_and_function_results(monkeypatch) -> None:
    provider = _azure_provider(monkeypatch)
    client = _FakeAsyncOpenAI.instances[-1]
    reasoning = {"type": "reasoning", "id": "rs_test", "summary": [], "encrypted_content": "test-only"}
    call = {"type": "function_call", "id": "fc_test", "call_id": "call_1", "name": "get_my_timetable", "arguments": "{}"}
    client.responses.output = [
        SimpleNamespace(**reasoning, model_dump=lambda **kwargs: reasoning),
        SimpleNamespace(**call, model_dump=lambda **kwargs: call),
    ]
    user = {"role": "user", "content": "Timetable?"}
    turn = await provider.complete([user], [])
    assert turn.tool_calls[0].id == "call_1"
    assert turn.tool_calls[0].arguments == {}
    await provider.complete([
        user, turn.assistant_message,
        {"role": "tool", "tool_call_id": "call_1", "content": "[]"},
    ], [])
    assert client.responses.requests[-1]["input"] == [
        user, reasoning, call,
        {"type": "function_call_output", "call_id": "call_1", "output": "[]"},
    ]
    await provider.complete([{"role": "user", "content": "Separate conversation"}], [])
    assert len(client.responses.requests[-1]["input"]) == 1


@pytest.mark.asyncio
async def test_azure_legacy_chat_remains_supported(monkeypatch) -> None:
    provider = _azure_provider(monkeypatch, "2024-10-21")
    await provider.complete([{"role": "user", "content": "Hi"}], [])
    client = _FakeAsyncOpenAI.instances[-1]
    assert client.options["api_version"] == "2024-10-21"
    assert client.chat.completions.requests[-1]["model"] == "custom-deployment"


@pytest.mark.asyncio
async def test_azure_incomplete_response_is_not_success(monkeypatch) -> None:
    provider = _azure_provider(monkeypatch)
    _FakeAsyncOpenAI.instances[-1].responses.status = "incomplete"
    with pytest.raises(RuntimeError, match="incomplete"):
        await provider.complete([{"role": "user", "content": "Hi"}], [])


@pytest.mark.asyncio
async def test_agent_replays_provider_message_metadata() -> None:
    from .providers import ToolCall

    raw = {"role": "assistant", "content": None, "tool_calls": [], "_responses_output": [{"type": "reasoning"}]}

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

        async def call_tool(self, name, arguments):
            return SimpleNamespace(structuredContent={"count": 0})

    class Model:
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AssistantTurn(tool_calls=[ToolCall("call_1", "test", {})], assistant_message=raw)
            assert messages[-2] == raw
            return AssistantTurn(text="Done")

    result = await run_agent(Session(), Model(), "Test")
    assert result.final_text == "Done"


@pytest.mark.asyncio
async def test_anthropic_default_model_and_tool_roundtrip(monkeypatch) -> None:
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="text", text="Done"),
        ])

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(
        AsyncAnthropic=lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=create)),
    ))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    provider = make_provider("anthropic")
    turn = await provider.complete([
        {"role": "system", "content": "Use tools"},
        {"role": "user", "content": "Test"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "test", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "[]"},
    ], [])
    assert requests[0]["model"] == "claude-sonnet-5"
    assert requests[0]["system"] == "Use tools"
    assert requests[0]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert turn.text == "Done"


@pytest.mark.asyncio
async def test_gemini_agent_preserves_signature_on_second_request(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider = make_provider("gemini")
    client = _FakeAsyncOpenAI.instances[-1]
    requests = []
    raw = {
        "role": "assistant",
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "test", "arguments": "{}"},
            "extra_content": {"google": {"thought_signature": "test-signature"}},
        }],
        "annotations": [], "refusal": None,
    }

    async def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            message = SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(id="call_1", function=SimpleNamespace(name="test", arguments="{}"))],
                model_dump=lambda **options: raw,
            )
        else:
            message = SimpleNamespace(content="Done", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=message, finish_reason="tool_calls" if message.tool_calls else "stop",
        )])

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

        async def call_tool(self, name, arguments):
            return SimpleNamespace(structuredContent={"count": 0})

    client.chat.completions.create = create
    result = await run_agent(Session(), provider, "Test")
    outgoing = requests[1]["messages"][-2]
    assert outgoing["tool_calls"] == raw["tool_calls"]
    assert "annotations" not in outgoing
    assert "refusal" not in outgoing
    assert result.final_text == "Done"


@pytest.mark.asyncio
async def test_azure_concurrent_conversations_keep_separate_reasoning(monkeypatch) -> None:
    provider = _azure_provider(monkeypatch)
    client = _FakeAsyncOpenAI.instances[-1]
    ready = asyncio.Event()
    started = set()
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        label = kwargs["input"][0]["content"]
        if len(kwargs["input"]) == 1:
            started.add(label)
            if len(started) == 2:
                ready.set()
            await ready.wait()
            reasoning = {"type": "reasoning", "id": f"rs_{label}", "summary": [], "encrypted_content": f"test-{label}"}
            call = {"type": "function_call", "call_id": f"call_{label}", "name": "test", "arguments": "{}"}
            return SimpleNamespace(status="completed", output_text="", output=[
                SimpleNamespace(**reasoning, model_dump=lambda **options: reasoning),
                SimpleNamespace(**call, model_dump=lambda **options: call),
            ])
        assert kwargs["input"][1]["encrypted_content"] == f"test-{label}"
        assert kwargs["input"][2]["call_id"] == f"call_{label}"
        assert kwargs["input"][3]["call_id"] == f"call_{label}"
        return SimpleNamespace(status="completed", output_text="Done", output=[])

    async def conversation(label):
        user = {"role": "user", "content": label}
        turn = await provider.complete([user], [])
        return await provider.complete([
            user, turn.assistant_message,
            {"role": "tool", "tool_call_id": turn.tool_calls[0].id, "content": "[]"},
        ], [])

    client.responses.create = create
    results = await asyncio.gather(conversation("first"), conversation("second"))
    assert all(result.text == "Done" for result in results)
    assert len(requests) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_error", [False, True])
async def test_agent_reports_tool_errors_even_when_model_answers(transport_error) -> None:
    from .providers import ToolCall
    from .scenarios import _run_one

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

        async def call_tool(self, name, arguments):
            if transport_error:
                raise RuntimeError("private server detail")
            return SimpleNamespace(isError=True, structuredContent=None, content=[])

    class Model:
        count = 0

        async def complete(self, messages, tools):
            self.count += 1
            if self.count == 1:
                return AssistantTurn(tool_calls=[ToolCall("test-call", "get_my_loans", {})])
            return AssistantTurn(text="The service could not be read.")

    run = await run_agent(Session(), Model(), "Read loans")
    assert run.tool_errors == ["get_my_loans"]
    result = await _run_one(Session(), Model(), "Read loans")
    assert result["error"]
    assert "private server detail" not in result["error"]


@pytest.mark.asyncio
async def test_scenarios_reject_empty_answers_and_turn_exhaustion() -> None:
    from .providers import ToolCall
    from .scenarios import _run_one

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

        async def call_tool(self, name, arguments):
            return SimpleNamespace(isError=False, structuredContent={"count": 0})

    class Model:
        def __init__(self, repeat):
            self.repeat = repeat

        async def complete(self, messages, tools):
            return AssistantTurn(text="checking", tool_calls=[ToolCall("call", "get_my_loans", {})]) if self.repeat else AssistantTurn(text="")

    for repeat in (False, True):
        result = await _run_one(Session(), Model(repeat), "Read loans")
        assert result["error"]


@pytest.mark.parametrize("arguments", [
    '{"private-argument":', "", None, "null", "[]", "42", '"private-argument"', "true", {},
])
def test_chat_rejects_invalid_arguments_without_payload(arguments):
    message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
        id="call", function=SimpleNamespace(name="get_grades", arguments=arguments),
    )])
    with pytest.raises(ValueError, match="Tool arguments must be a JSON object") as caught:
        _openai_turn_from_message(message)
    assert "private-argument" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openai", "gemini", "azure-openai"])
@pytest.mark.parametrize("with_tool", [False, True])
@pytest.mark.parametrize("reason", ["length", "content_filter", None, "private-status"])
async def test_chat_rejects_incomplete_completion(monkeypatch, provider_name, with_tool, reason):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider = (_azure_provider(monkeypatch, "2024-10-21")
                if provider_name == "azure-openai" else make_provider(provider_name))
    calls = [SimpleNamespace(id="call", function=SimpleNamespace(name="get_grades", arguments="{}"))] if with_tool else []

    async def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=reason, message=SimpleNamespace(content="private-answer", tool_calls=calls),
        )])

    _FakeAsyncOpenAI.instances[-1].chat.completions.create = create
    with pytest.raises(RuntimeError, match="completion") as caught:
        await provider.complete([], [])
    assert "private-" not in str(caught.value)


def test_sensitive_dataclass_reprs_hide_payloads():
    from .mcp_host import AgentRun
    from .providers import ToolCall

    call = ToolCall("call", "get_grades", {"query": "private-argument"})
    turn = AssistantTurn(text="private-answer", tool_calls=[call], assistant_message={"content": "private-transcript"})
    run = AgentRun("private-answer", [call], [{"content": "private-transcript"}])
    for value in (call, turn, run):
        assert "private-" not in repr(value)


@pytest.mark.parametrize("case", ["wrong_tool", "whitespace", "tool_error", "exhausted", "valid"])
def test_shared_success_requires_expected_tool_and_stripped_answer(case):
    from . import mcp_host
    from .providers import ToolCall

    run = mcp_host.AgentRun(
        " \n " if case == "whitespace" else "Done",
        [ToolCall("call", "get_my_loans" if case == "wrong_tool" else "get_my_timetable", {})],
        tool_errors=["get_my_timetable"] if case == "tool_error" else [],
        exhausted=case == "exhausted",
    )
    error = mcp_host.agent_run_error(run, {"get_my_timetable"})
    assert (error is None) == (case == "valid")


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id,tool_name,arguments,valid", [
    ("grades_filtered", "get_grades", {}, False),
    ("grades_filtered", "get_grades", {"year": 2026}, False),
    ("grades_filtered", "get_grades", {"term_code": "10"}, False),
    ("grades_filtered", "get_grades", {"year": 2025, "term_code": "10"}, False),
    ("grades_filtered", "get_grades", {"year": 2026, "term_code": "10"}, True),
    ("exam_final", "get_exam_schedule", {}, False),
    ("exam_final", "get_exam_schedule", {"exam_type": "default"}, False),
    ("exam_final", "get_exam_schedule", {"exam_type": "midterm"}, False),
    ("exam_final", "get_exam_schedule", {"exam_type": "final"}, True),
    ("catalog_filtered", "search_courses", {"keyword": "AI"}, False),
    ("catalog_filtered", "search_courses", {"keyword": "인공지능", "limit": 3, "year": 2026, "term_code": "10", "campus_code": "s1"}, False),
    ("catalog_filtered", "search_courses", {"keyword": "인공지능", "limit": 3, "year": 2026, "term_code": "10", "campus_code": "s3"}, True),
    ("lms_gradebook", "get_lms_gradebook", {"course_id": "test", "include_feedback": True}, False),
    ("lms_gradebook", "get_lms_gradebook", {"course_id": "test", "include_feedback": "false"}, False),
    ("lms_gradebook", "get_lms_gradebook", {"course_id": "test", "include_feedback": False}, True),
    ("lms_gradebook", "get_lms_gradebook", {"course_id": "test"}, True),
])
async def test_scenario_argument_contracts(monkeypatch, scenario_id, tool_name, arguments, valid):
    from . import scenarios
    from .mcp_host import AgentRun
    from .providers import ToolCall

    async def fake_run(*args, **kwargs):
        return AgentRun("Done", [ToolCall("call", tool_name, arguments)])

    monkeypatch.setattr(scenarios, "run_agent", fake_run)
    result = await scenarios._run_one(None, None, "Synthetic question", scenario_id=scenario_id)
    assert (result["error"] is None) == valid
    assert "arguments" not in result


@pytest.mark.asyncio
async def test_scenario_rejects_feedback_opt_in_even_if_followed_by_safe_call(monkeypatch):
    from . import scenarios
    from .mcp_host import AgentRun
    from .providers import ToolCall

    async def fake_run(*args, **kwargs):
        return AgentRun("Done", [
            ToolCall("first", "get_lms_gradebook", {"course_id": "test", "include_feedback": True}),
            ToolCall("second", "get_lms_gradebook", {"course_id": "test", "include_feedback": False}),
        ])

    monkeypatch.setattr(scenarios, "run_agent", fake_run)
    result = await scenarios._run_one(None, None, "Synthetic", scenario_id="lms_gradebook")
    assert result["error"]


def test_live_provider_fixture_honors_opt_out_before_construction(monkeypatch):
    from . import conftest

    monkeypatch.setenv("RUN_LIVE_LLM", "0")
    constructed = []
    monkeypatch.setattr(conftest, "make_provider", lambda: constructed.append(True))
    with pytest.raises(pytest.skip.Exception):
        conftest.provider.__wrapped__()
    assert not constructed


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["wrong_tool", "whitespace", "tool_error", "exhausted", "transport", "model", "provider", "valid"])
async def test_live_timetable_validation_is_strict_and_sanitized(monkeypatch, case):
    from . import test_e2e_live
    from .mcp_host import AgentRun
    from .providers import ToolCall

    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    monkeypatch.setenv("LLM_PROVIDER", "synthetic")

    def fake_provider():
        if case == "provider":
            raise RuntimeError("private-provider-error")
        return object()

    @asynccontextmanager
    async def fake_session():
        if case == "transport":
            raise RuntimeError("private-transport-error")
        yield object()

    async def fake_run(*args, **kwargs):
        if case == "model":
            raise RuntimeError("private-model-error")
        return AgentRun(
            " \n " if case == "whitespace" else "private-answer",
            [ToolCall("call", "get_my_loans" if case == "wrong_tool" else "get_my_timetable", {"query": "private-argument"})],
            [{"content": "private-transcript"}],
            tool_errors=["get_my_timetable"] if case == "tool_error" else [],
            exhausted=case == "exhausted",
        )

    monkeypatch.setattr(test_e2e_live, "make_provider", fake_provider)
    monkeypatch.setattr(test_e2e_live, "stdio_client_session", fake_session)
    monkeypatch.setattr(test_e2e_live, "run_agent", fake_run)
    if case == "valid":
        await test_e2e_live.test_live_end_to_end()
    else:
        with pytest.raises(pytest.fail.Exception) as caught:
            await test_e2e_live.test_live_end_to_end()
        assert "private-" not in str(caught.value)
        assert caught.value.pytrace is False
        assert caught.value.__context__ is None or caught.value.__suppress_context__
        assert "private-" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.asyncio
async def test_stdio_suppresses_server_stderr(monkeypatch):
    from mcp.client import stdio
    from .mcp_host import stdio_client_session

    destinations = []

    @asynccontextmanager
    async def fake_stdio(params, **kwargs):
        destinations.append(getattr(kwargs.get("errlog"), "name", None))
        raise RuntimeError("synthetic transport stopped before process creation")
        yield

    monkeypatch.setattr(stdio, "stdio_client", fake_stdio)
    with pytest.raises(RuntimeError):
        async with stdio_client_session():
            pytest.fail("Unexpected connection")
    assert destinations == [os.devnull]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["empty", "dropped", "count", "changed_row", "scope", "summary", "valid"])
async def test_live_grade_filter_checks_complete_baseline(monkeypatch, case):
    live_tools = importlib.import_module("tests.test_live_tools")
    matching = [
        {"year": "2026", "term_code": "10", "course_code": "first", "grade": "A"},
        {"year": "2026", "term_code": "10", "course_code": "second", "grade": "B"},
    ]
    baseline = {
        "courses": matching + [{"year": "2025", "term_code": "20", "course_code": "other"}],
        "summary": {"gpa": "3.5"}, "summary_scope": "all_terms", "count": 3,
    }
    filtered = {
        "courses": [dict(row) for row in matching], "count": 2,
        "summary": dict(baseline["summary"]), "summary_scope": "all_terms",
    }
    if case == "empty":
        filtered.update(courses=[], count=0)
    elif case == "dropped":
        filtered.update(courses=filtered["courses"][:1], count=1)
    elif case == "count":
        filtered["count"] = 0
    elif case == "changed_row":
        filtered["courses"][0]["grade"] = "F"
    elif case == "scope":
        filtered["summary_scope"] = "filtered_terms"
    elif case == "summary":
        filtered["summary"]["gpa"] = "4.0"

    class StopAfterGradeFilter(Exception):
        pass

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[])

        async def call_tool(self, name, arguments):
            if name == "get_my_loans":
                raise StopAfterGradeFilter()
            payloads = {
                "get_lms_courses": [], "get_lms_notices": [], "get_lms_deadlines": [],
                "search_notices": {"count": 0, "results": []},
                "get_lms_overview": {"courses": [], "upcoming_deadlines": []},
                "get_student_profile": {"department": "test", "terms": [], "pii_included": False},
                "get_my_timetable": {"courses": [], "count": 0},
                "get_grades": filtered if arguments else baseline,
            }
            return SimpleNamespace(isError=False, structuredContent=payloads[name])

    @asynccontextmanager
    async def fake_stdio(*args, **kwargs):
        yield None, None

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield Session()

    monkeypatch.setenv("RUN_LIVE_PORTAL", "1")
    monkeypatch.setattr(live_tools, "stdio_client", fake_stdio)
    monkeypatch.setattr(live_tools, "ClientSession", fake_client)
    if case == "valid":
        with pytest.raises(pytest.fail.Exception, match="StopAfterGradeFilter"):
            await live_tools.test_all_read_tools_over_stdio()
    else:
        with pytest.raises((AssertionError, pytest.fail.Exception), match="Grade source/filter mismatch"):
            await live_tools.test_all_read_tools_over_stdio()


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", ["demo", "scenarios", "dump_tools"])
async def test_runner_opt_out_prevents_provider_and_transport(monkeypatch, module_name):
    module = importlib.import_module(f"{__package__}.{module_name}")
    monkeypatch.setenv("RUN_LIVE_LLM", "0")

    def forbidden(*args, **kwargs):
        pytest.fail("Live resource constructed despite opt-out")

    if hasattr(module, "make_provider"):
        monkeypatch.setattr(module, "make_provider", forbidden)
    monkeypatch.setattr(module, "stdio_client_session", forbidden)
    args = [] if module_name == "dump_tools" else SimpleNamespace(provider="test", chat=False, question="Test")
    assert await module._main(args) != 0


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", ["demo", "scenarios"])
async def test_runner_provider_errors_do_not_print_details(monkeypatch, capsys, module_name):
    module = importlib.import_module(f"{__package__}.{module_name}")
    monkeypatch.setenv("RUN_LIVE_LLM", "1")

    def unavailable(*args):
        raise ProviderUnavailable("private-provider-detail")

    monkeypatch.setattr(module, "make_provider", unavailable)
    assert await module._main(SimpleNamespace(provider="test", chat=False, question="Test")) != 0
    captured = capsys.readouterr()
    assert "private-" not in captured.out + captured.err


@pytest.mark.asyncio
async def test_dump_tool_exception_does_not_print_details(monkeypatch, capsys):
    from . import dump_tools

    class Session:
        async def call_tool(self, *args):
            raise RuntimeError("private-tool-detail")

    @asynccontextmanager
    async def fake_session():
        yield Session()

    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    monkeypatch.setattr(dump_tools, "stdio_client_session", fake_session)
    await dump_tools._main([("test", {})])
    captured = capsys.readouterr()
    assert "private-" not in captured.out + captured.err


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [False, True])
async def test_scenario_cli_scores_arguments(monkeypatch, valid):
    from . import scenarios
    from .mcp_host import AgentRun
    from .providers import ToolCall

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def fake_run(*args, **kwargs):
        return AgentRun("Done", [ToolCall("call", "get_grades", {"year": 2026, "term_code": "10"} if valid else {})])

    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    monkeypatch.setattr(scenarios, "make_provider", lambda *args: SimpleNamespace(name="synthetic"))
    monkeypatch.setattr(scenarios, "stdio_client_session", fake_session)
    monkeypatch.setattr(scenarios, "run_agent", fake_run)
    monkeypatch.setattr(scenarios, "SCENARIOS", [("grades_filtered", "Synthetic", {"get_grades"})])
    assert await scenarios._main(SimpleNamespace(provider="synthetic")) == (0 if valid else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,with_tool", [("stop", False), ("tool_calls", True)])
@pytest.mark.parametrize("provider_name", ["openai", "gemini", "azure-openai"])
async def test_chat_accepts_complete_turns(monkeypatch, provider_name, reason, with_tool):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider = (_azure_provider(monkeypatch, "2024-10-21")
                if provider_name == "azure-openai" else make_provider(provider_name))
    calls = [SimpleNamespace(id="call", function=SimpleNamespace(name="get_grades", arguments='{"year":2026}'))] if with_tool else []

    async def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=reason, message=SimpleNamespace(content="Done", tool_calls=calls),
        )])

    _FakeAsyncOpenAI.instances[-1].chat.completions.create = create
    turn = await provider.complete([], [])
    assert bool(turn.tool_calls) == with_tool
    if with_tool:
        assert turn.tool_calls[0].arguments == {"year": 2026}


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tool", [False, True])
@pytest.mark.parametrize("reason", ["max_tokens", "pause_turn", "refusal", None, "private-status"])
async def test_anthropic_rejects_incomplete_completion(monkeypatch, with_tool, reason):
    async def create(**kwargs):
        content = ([SimpleNamespace(type="tool_use", id="call", name="get_grades", input={})]
                   if with_tool else [SimpleNamespace(type="text", text="private-answer")])
        return SimpleNamespace(stop_reason=reason, content=content)

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(
        AsyncAnthropic=lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=create)),
    ))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(RuntimeError, match="completion") as caught:
        await make_provider("anthropic").complete([], [])
    assert "private-" not in str(caught.value)