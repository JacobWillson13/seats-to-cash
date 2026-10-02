import subprocess
import sys

from .conftest import CONFIG, ROOT


def _generator(*args):
    return subprocess.run(
        [sys.executable, "-m", "generator", *args], capture_output=True, text=True, cwd=ROOT
    )


def test_help_prints_usage():
    result = _generator("--help")
    assert result.returncode == 0
    assert result.stdout.startswith("usage: python -m generator")
    assert "--no-defects" in result.stdout


def test_check_validates_config_and_seeds():
    result = _generator("--config", str(CONFIG), "--check")
    assert result.returncode == 0, result.stderr
    assert "is valid" in result.stdout


def test_invalid_config_exits_with_a_clear_message(write_config):
    path = write_config({"trial.base_conversion": 1.4})
    result = _generator("--config", str(path), "--check")
    assert result.returncode == 2
    assert f"generator: {path}: invalid config" in result.stderr
    assert (
        "trial.base_conversion: Input should be less than or equal to 1 (got 1.4)" in result.stderr
    )
