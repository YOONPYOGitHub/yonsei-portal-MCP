"""Offline question-catalog integrity; only public source files are inspected."""
import ast
from collections import Counter
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("representative", "followup", "empty_or_ambiguous", "boundary_or_safety")


def sample():
    return [{"id": tool + "." + kind, "primary_tool": tool, "category": "test",
             "case_type": kind, "representative": kind == "representative", "question": "합성 질문",
             "expected_tools": [tool], "prerequisites": [], "expected_behavior": ["근거 제시"],
             "forbidden_claims": ["추측 금지"], "privacy": "public", "evaluation_mode": "answer"}
            for tool in ("tool_a", "tool_b") for kind in KINDS]


def test_valid_catalog_reports_tool_and_representative_coverage():
    from tests.qa.catalog import validate_catalog
    result = validate_catalog(sample(), {"tool_a", "tool_b"})
    assert result == {"questions": 8, "tools": 2, "representatives": 2}


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "unknown", "representative", "unsafe_id", "blank_question", "missing_assertion"])
def test_invalid_catalog_is_not_counted_as_complete(mutation):
    from tests.qa.catalog import validate_catalog
    cases = sample()
    if mutation == "duplicate": cases[1]["id"] = cases[0]["id"]
    elif mutation == "missing": cases.pop()
    elif mutation == "unknown": cases[0]["expected_tools"] = ["invented_tool"]
    elif mutation == "representative": cases[1]["representative"] = True
    elif mutation == "unsafe_id": cases[0]["id"] = "../private"
    elif mutation == "blank_question": cases[0]["question"] = " "
    else: cases[0]["expected_behavior"] = []
    with pytest.raises(ValueError):
        validate_catalog(cases, {"tool_a", "tool_b"})


def test_catalog_can_grow_without_recycling_ids():
    from tests.qa.catalog import validate_catalog
    cases = sample()
    extra = dict(cases[1], id="tool_a.followup_more", question="추가 후속 질문")
    cases.append(extra)
    assert validate_catalog(cases, {"tool_a", "tool_b"}) == {"questions": 9, "tools": 2, "representatives": 2}


def test_public_catalog_covers_the_registered_tools():
    from tests.qa.catalog import validate_catalog
    source = ast.parse((ROOT / "src/yonsei_portal_mcp/server.py").read_text(encoding="utf-8"))
    registered = {node.name for node in ast.walk(source)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                          and isinstance(d.func.value, ast.Name) and d.func.value.id == "mcp"
                          and d.func.attr == "tool" for d in node.decorator_list)}
    cases = [json.loads(line) for line in (ROOT / "docs/evaluation/questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    result = validate_catalog(cases, registered)
    assert result == {"questions": len(cases), "tools": len(registered), "representatives": len(registered)}
    assert set(Counter(c["primary_tool"] for c in cases)) == registered
    assert all(count >= 4 for count in Counter(c["primary_tool"] for c in cases).values())
