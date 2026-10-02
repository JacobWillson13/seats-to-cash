"""Actual CI-scale generation: deterministic Parquet and offline operation."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from .conftest import ROOT, SEEDS

SEED_FILES = tuple(sorted(SEEDS.glob("*.csv")))
CI_CONFIG = ROOT / "config" / "ci.yml"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generate(out: Path, *, hash_seed: str, extra_env: dict[str, str] | None = None):
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = hash_seed
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "generator",
            "--config",
            str(CI_CONFIG),
            "--seed",
            "42",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def test_ci_parquet_is_byte_identical_across_hash_seeds(tmp_path):
    seeds_before = {p.name: _hash(p) for p in SEED_FILES}
    first = tmp_path / "first"
    second = tmp_path / "second"
    _generate(first, hash_seed="1")
    _generate(second, hash_seed="987654")
    files_a = {p.relative_to(first): _hash(p) for p in first.glob("**/*.parquet")}
    files_b = {p.relative_to(second): _hash(p) for p in second.glob("**/*.parquet")}
    assert len(files_a) == 23
    assert files_a == files_b
    assert {p.name: _hash(p) for p in SEED_FILES} == seeds_before


def test_actual_ci_generation_runs_with_network_and_children_blocked(tmp_path):
    seeds_before = {p.name: _hash(p) for p in SEED_FILES}
    guard = tmp_path / "guard"
    guard.mkdir()
    marker = tmp_path / "guard-loaded"
    (guard / "sitecustomize.py").write_text(
        "import os, socket, subprocess\n"
        "from pathlib import Path\n"
        "Path(os.environ['NETWORK_GUARD_MARKER']).write_text('active')\n"
        "def block(*args, **kwargs):\n"
        "    raise AssertionError('outbound network or child process attempted')\n"
        "socket.socket.connect = block\n"
        "socket.socket.connect_ex = block\n"
        "socket.getaddrinfo = block\n"
        "socket.create_connection = block\n"
        "subprocess.Popen = block\n"
    )
    env = {
        "PYTHONPATH": os.pathsep.join([str(guard), str(ROOT)]),
        "NETWORK_GUARD_MARKER": str(marker),
    }
    out = tmp_path / "offline"
    _generate(out, hash_seed="23", extra_env=env)
    assert marker.read_text() == "active"
    assert len(list(out.glob("**/*.parquet"))) == 23
    assert {p.name: _hash(p) for p in SEED_FILES} == seeds_before
