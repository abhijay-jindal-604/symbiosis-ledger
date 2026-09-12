"""Exercises the actual bisect predicate script, not just validate_allocation.py
directly -- this is what catches a regression in the exit-code guards
(CONTEXT-DUMP §7's exit-127-read-as-bad trap) that a pure-Python test of
validate_allocation.py alone would miss.
"""
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.join(REPO_ROOT, "agents", "check_allocation.sh")


def _run(env_overrides, cwd=REPO_ROOT):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(["bash", SCRIPT], cwd=cwd, env=env,
                           capture_output=True, text=True)


def test_good_commit_exits_0(tmp_path):
    validator = tmp_path / "validate_allocation.py"
    shutil.copy(os.path.join(REPO_ROOT, "agents", "validate_allocation.py"), validator)
    shutil.copy(os.path.join(REPO_ROOT, "agents", "stream_io.py"), tmp_path / "stream_io.py")
    result = _run({"BISECT_VALIDATOR": str(validator)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_validator_exits_125_never_bad(tmp_path):
    result = _run({"BISECT_VALIDATOR": str(tmp_path / "does-not-exist.py")})
    assert result.returncode == 125


def test_missing_stream_file_exits_125(tmp_path):
    validator = tmp_path / "validate_allocation.py"
    shutil.copy(os.path.join(REPO_ROOT, "agents", "validate_allocation.py"), validator)
    shutil.copy(os.path.join(REPO_ROOT, "agents", "stream_io.py"), tmp_path / "stream_io.py")
    # Run from a directory with no streams/ subdirectory at all.
    empty_cwd = tmp_path / "empty_repo"
    empty_cwd.mkdir()
    result = _run({"BISECT_VALIDATOR": str(validator)}, cwd=str(empty_cwd))
    assert result.returncode == 125
