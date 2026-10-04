"""Windows must receive the IANA data required by the portal's KST dates."""
from importlib.metadata import requires
from packaging.requirements import Requirement
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sys
import pytest


def test_windows_dependency_includes_iana_timezone_data():
    dependencies = [Requirement(item) for item in requires("yonsei-portal-mcp") or []]
    assert any(item.name == "tzdata" and (item.marker is None or item.marker.evaluate({"sys_platform": "win32"})) for item in dependencies)


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows IANA timezone verification")
def test_kst_on_native_windows():
    assert datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Seoul")).utcoffset() == timedelta(hours=9)
