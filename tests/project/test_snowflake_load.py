"""`make snowflake` loader: configuration and table mapping, without connecting."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sf", ROOT / "scripts/snowflake_load.py")
sf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sf)


def test_env_file_is_read_and_required_keys_enforced(tmp_path, monkeypatch):
    for key in list(sf.os.environ):
        if key.startswith("SNOWFLAKE_"):
            monkeypatch.delenv(key)
    env = tmp_path / ".env"
    env.write_text("# comment\nSNOWFLAKE_ACCOUNT=ab12345.us-east-1\nSNOWFLAKE_DATABASE='DEMO'\n")
    with pytest.raises(SystemExit, match="SNOWFLAKE_PRIVATE_KEY_PATH"):
        sf.settings(sf.read_env(env))
    env.write_text(env.read_text() + "SNOWFLAKE_PRIVATE_KEY_PATH=/keys/rsa.p8\n")
    cfg = sf.settings(sf.read_env(env))
    assert cfg["SNOWFLAKE_ACCOUNT"] == "ab12345.us-east-1"
    assert cfg["SNOWFLAKE_DATABASE"] == "DEMO"
    assert cfg["SNOWFLAKE_WAREHOUSE"] == "TRANSFORMING"


def test_every_parquet_file_maps_to_an_upper_case_raw_table(tmp_path):
    for rel in ("raw/stripe/invoice.parquet", "raw/salesforce/account.parquet",
                "answer_key/truth/defect_manifest.parquet"):  # fmt: skip
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    assert [(s, t) for s, t, _ in sf.tables(tmp_path)] == [
        ("RAW_SALESFORCE", "ACCOUNT"),
        ("RAW_STRIPE", "INVOICE"),
        ("RAW_TRUTH", "DEFECT_MANIFEST"),
    ]
    with pytest.raises(SystemExit, match="make data"):
        sf.tables(tmp_path / "empty")
