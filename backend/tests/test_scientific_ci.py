from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("cases", "expected"),
    [
        ('<testcase name="scientific_fixture"/>', 0),
        ('<testcase name="scientific_fixture"><skipped message="R unavailable"/></testcase>', 1),
        ("", 1),
    ],
)
def test_required_integration_job_rejects_missing_execution(tmp_path, cases, expected):
    report = tmp_path / "report.xml"
    report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    script = Path(__file__).resolve().parents[2] / "scripts/assert-test-execution.py"
    result = subprocess.run([sys.executable, str(script), str(report)], capture_output=True)
    assert result.returncode == expected
