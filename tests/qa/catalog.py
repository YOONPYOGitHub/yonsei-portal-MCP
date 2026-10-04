"""Public question-catalog validation; no environment, model or network access."""
from collections import Counter
import re

KINDS = {"representative", "followup", "empty_or_ambiguous", "boundary_or_safety"}
FIELDS = {"id", "primary_tool", "category", "case_type", "representative", "question",
          "expected_tools", "prerequisites", "expected_behavior", "forbidden_claims", "privacy", "evaluation_mode"}


def validate_catalog(cases: list[dict], registered_tools: set[str]) -> dict:
    """Require the four baseline variants and one representative per actual tool."""
    def fail():
        raise ValueError("Question catalog violates its schema or coverage contract")

    if not isinstance(cases, list) or not registered_tools:
        fail()
    seen, counts, representatives = set(), Counter(), Counter()
    types = {tool: set() for tool in registered_tools}
    for case in cases:
        if not isinstance(case, dict) or set(case) != FIELDS:
            fail()
        for field in ("id", "primary_tool", "category", "case_type", "question", "privacy", "evaluation_mode"):
            if not isinstance(case[field], str) or not case[field].strip():
                fail()
        identifier, tool, kind = case["id"], case["primary_tool"], case["case_type"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", identifier) or identifier in seen:
            fail()
        if tool not in registered_tools or kind not in KINDS:
            fail()
        if type(case["representative"]) is not bool or case["representative"] != (kind == "representative"):
            fail()
        if case["privacy"] not in {"public", "personal"} or case["evaluation_mode"] not in {"answer", "clarification", "refusal"}:
            fail()
        for field in ("expected_tools", "prerequisites", "expected_behavior", "forbidden_claims"):
            values = case[field]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                fail()
        if not case["expected_behavior"] or not case["forbidden_claims"]:
            fail()
        if not set(case["expected_tools"]) <= registered_tools:
            fail()
        if case["representative"] and tool not in case["expected_tools"]:
            fail()
        seen.add(identifier); counts[tool] += 1; types[tool].add(kind)
        representatives[tool] += int(case["representative"])
    if any(types[tool] != KINDS for tool in registered_tools) or representatives != {tool: 1 for tool in registered_tools}:
        fail()
    return {"questions": len(cases), "tools": len(counts), "representatives": sum(representatives.values())}
