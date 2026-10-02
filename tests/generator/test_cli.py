import subprocess
import sys


def test_help_prints_usage():
    result = subprocess.run(
        [sys.executable, "-m", "generator", "--help"], capture_output=True, text=True, check=True
    )
    assert result.stdout.startswith("usage: python -m generator")
    assert "--no-defects" in result.stdout
