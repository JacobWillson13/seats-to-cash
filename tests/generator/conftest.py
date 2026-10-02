import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "simulation.yml"
SEEDS = ROOT / "seeds"


@pytest.fixture
def write_config(tmp_path):
    """Write a copy of simulation.yml with `changes` applied; returns its path.

    `changes` maps dotted keys to new values; a value of DELETE removes the key.
    """
    base = yaml.safe_load(CONFIG.read_text())

    def write(changes: dict) -> Path:
        raw = copy.deepcopy(base)
        for dotted, value in changes.items():
            *parents, leaf = dotted.split(".")
            node = raw
            for key in parents:
                node = node[key]
            if value is DELETE:
                del node[leaf]
            else:
                node[leaf] = value
        path = tmp_path / "config.yml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False))
        return path

    return write


DELETE = object()
