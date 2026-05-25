import sys
from pathlib import Path

import pytest

from pythinker.agent.tools.exec_session import ExecSessionManager, ListExecSessionsTool, WriteStdinTool
from pythinker.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_exec_yield_returns_session_and_write_stdin_polls(tmp_path: Path) -> None:
    manager = ExecSessionManager(max_sessions=2, idle_timeout=30)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)

    result = await tool.execute(
        command=(
            f'"{sys.executable}" -c "import time; print(\'ready\', flush=True); time.sleep(1)"'
        ),
        yield_time_ms=50,
    )
    assert "session_id:" in result
    session_id = result.split("session_id:", 1)[1].split()[0]

    poller = WriteStdinTool(manager=manager)
    result = await poller.execute(session_id=session_id, wait_for="ready", wait_timeout_ms=2000)
    assert "ready" in result
    if "Exit code:" not in result:
        result = await poller.execute(session_id=session_id, wait_for="Exit code", wait_timeout_ms=2000)
    assert "Exit code: 0" in result


@pytest.mark.asyncio
async def test_write_stdin_sends_input_and_closes_stdin(tmp_path: Path) -> None:
    manager = ExecSessionManager(max_sessions=2, idle_timeout=30)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    result = await tool.execute(command="python -c 'print(input())'", yield_time_ms=0)
    session_id = result.split("session_id:", 1)[1].split()[0]

    writer = WriteStdinTool(manager=manager)
    result = await writer.execute(
        session_id=session_id,
        chars="hello\n",
        close_stdin=True,
        wait_for="hello",
        wait_timeout_ms=2000,
    )
    assert "hello" in result
    assert "Exit code: 0" in result


@pytest.mark.asyncio
async def test_list_exec_sessions_reports_running_session(tmp_path: Path) -> None:
    manager = ExecSessionManager(max_sessions=2, idle_timeout=30)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    result = await tool.execute(command="python -c 'import time; time.sleep(2)'", yield_time_ms=0)
    session_id = result.split("session_id:", 1)[1].split()[0]

    listed = await ListExecSessionsTool(manager=manager).execute()
    assert session_id in listed
    assert "running" in listed

    await WriteStdinTool(manager=manager).execute(session_id=session_id, terminate=True)
