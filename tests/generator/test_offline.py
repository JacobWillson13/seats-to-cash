"""Seeds are committed inputs: only `make seeds` may rebuild them or touch the network."""

import ast
import re
import socket
import subprocess

import pytest

from generator.__main__ import main

from .conftest import CONFIG, ROOT

SEED_BUILDERS = ("build_close_calendar", "build_free_email_domains", "make seeds")
NETWORK_MODULES = {"urllib", "http", "socket", "requests", "httpx", "ftplib", "smtplib"}


def _make_targets() -> list[str]:
    text = (ROOT / "Makefile").read_text()
    return sorted(set(re.findall(r"^([a-z][a-z0-9-]*):", text, flags=re.MULTILINE)) - {"seeds"})


@pytest.mark.parametrize("target", _make_targets())
def test_no_make_target_but_seeds_rebuilds_seeds(target):
    result = subprocess.run(
        ["make", "-n", target], cwd=ROOT, capture_output=True, text=True, check=True
    )
    for builder in SEED_BUILDERS:
        assert builder not in result.stdout, f"`make {target}` runs {builder}"


def test_data_and_demo_are_guarded():
    # Fails loudly if a rename drops the targets this guard exists for.
    assert "data" in _make_targets()


def test_generator_imports_no_network_modules():
    for path in sorted((ROOT / "generator").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in NETWORK_MODULES, f"{path} imports {name}"


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the generator tried to open a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_generator_runs_offline(no_network, capsys):
    assert main(["--config", str(CONFIG), "--check"]) == 0
