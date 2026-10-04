"""A feature's follow-up may route to another tool; refusals may call none."""
from tests.qa.records import RunStore


def test_followup_and_no_call_cases_keep_truthful_tool_coverage(tmp_path):
    store = RunStore.create(tmp_path.resolve() / "private", {"timestamp": "test", "model": "test", "execution_mode": "synthetic"})
    store.save_call("call-1", {"tool": "list_posts", "arguments": {}, "result": [], "is_error": False, "started_at": "test", "finished_at": "test"})
    store.save_answer("search.followup", {"status": "answered", "answer": "합성 후속 목록 확인", "call_ids": ["call-1"]})
    store.save_answer("search.boundary", {"status": "needs_clarification", "reason": "범위 확인 필요"})
    catalog = [
        {"id": "search.followup", "primary_tool": "search_posts", "expected_tools": ["list_posts"]},
        {"id": "search.boundary", "primary_tool": "search_posts", "expected_tools": []},
    ]
    result = store.summarize(catalog, [row["id"] for row in catalog])
    assert result["selected_counts"]["answered"] == 1
    assert result["selected_counts"]["needs_clarification"] == 1
    assert result["primary_tools"] == {"expected": 1, "called": 0, "answered": 0}
