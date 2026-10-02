"""The answer key may be read only by models/audit/."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fence", ROOT / "scripts/check_truth_fence.py")
fence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fence)


def test_repository_respects_the_truth_fence():
    assert fence.violations() == []


def test_fence_catches_a_mart_reading_truth(tmp_path):
    (tmp_path / "models/marts").mkdir(parents=True)
    (tmp_path / "models/audit").mkdir(parents=True)
    (tmp_path / "models/audit/ok.sql").write_text("select * from {{ source('truth', 'x') }}")
    (tmp_path / "models/marts/bad.sql").write_text("select * from {{ source( 'truth', 'x') }}")
    found = fence.violations(tmp_path)
    assert len(found) == 1 and found[0].startswith("models/marts/bad.sql:1")
