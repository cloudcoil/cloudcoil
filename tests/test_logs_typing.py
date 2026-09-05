"""Ensure log callers get natural keyword completion and concrete record types."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_log_api_typing(tmp_path, checker):
    script = tmp_path / "log_usage.py"
    script.write_text("""from typing import assert_type
from cloudcoil import logs

options = logs.LogOptions(tail_lines=10, since_seconds=30)
assert_type(options.tail_lines, int | None)

def sync_usage() -> None:
    for source in logs.discover(label_selector="app=worker"):
        assert_type(source, logs.LogSource)
        assert_type(logs.read(source, tail_lines=10, options=options), str)
        with logs.stream(source, match=logs.LogFilter(contains="error")) as records:
            for record in records:
                assert_type(record, logs.LogRecord)
                assert_type(record.timestamp, str | None)

async def async_usage() -> None:
    async for source in logs.async_discover(all_namespaces=True):
        assert_type(source, logs.LogSource)
        assert_type(await logs.async_read(source, previous=True), str)
        async with logs.async_stream(source, follow=False, match=lambda r: r.container == "app") as records:
            async for record in records:
                assert_type(record, logs.LogRecord)
""")
    args = (
        ["--cache-dir", str(tmp_path / "mypy-cache")]
        if checker == "mypy"
        else ["--pythonversion", "3.14"]
    )
    result = subprocess.run(
        [checker, *args, str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
