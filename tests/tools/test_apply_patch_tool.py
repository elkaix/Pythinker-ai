from pathlib import Path

import pytest

from pythinker.agent.tools.apply_patch import ApplyPatchTool


@pytest.mark.asyncio
async def test_apply_patch_add_update_delete_and_dry_run(tmp_path: Path) -> None:
    tool = ApplyPatchTool(workspace=tmp_path, allowed_dir=tmp_path)

    patch = """*** Begin Patch
*** Add File: src/demo.txt
+hello
+world
*** End Patch"""
    result = await tool.execute(patch=patch, dry_run=True)
    assert result.startswith("Patch dry-run succeeded")
    assert not (tmp_path / "src/demo.txt").exists()

    result = await tool.execute(patch=patch)
    assert "Patch applied" in result
    assert (tmp_path / "src/demo.txt").read_text(encoding="utf-8") == "hello\nworld\n"

    result = await tool.execute(patch="""*** Begin Patch
*** Update File: src/demo.txt
@@
 hello
-world
+there
*** End Patch""")
    assert "update src/demo.txt" in result
    assert (tmp_path / "src/demo.txt").read_text(encoding="utf-8") == "hello\nthere\n"

    result = await tool.execute(patch="""*** Begin Patch
*** Delete File: src/demo.txt
*** End Patch""")
    assert "delete src/demo.txt" in result
    assert not (tmp_path / "src/demo.txt").exists()


@pytest.mark.asyncio
async def test_apply_patch_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    tool = ApplyPatchTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(patch="""*** Begin Patch
*** Add File: ../outside.txt
+nope
*** End Patch""")
    assert "must not contain '..'" in result


@pytest.mark.asyncio
async def test_apply_patch_reports_hunk_mismatch(tmp_path: Path) -> None:
    (tmp_path / "demo.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(patch="""*** Begin Patch
*** Update File: demo.txt
@@
 missing
+line
*** End Patch""")
    assert result.startswith("Error applying patch: hunk does not match demo.txt")
