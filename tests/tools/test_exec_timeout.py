from pythinker.agent.tools.shell import ExecTool


def test_exec_config_timeout_zero_disables_default_limit() -> None:
    tool = ExecTool(timeout=0)
    assert tool._resolve_timeout(None) is None


def test_exec_config_timeout_is_not_capped_but_call_timeout_is_capped() -> None:
    tool = ExecTool(timeout=1200)
    assert tool._resolve_timeout(None) == 1200
    assert tool._resolve_timeout(1200) == tool._MAX_TIMEOUT
