"""LookML parses with lkml and only references columns the dbt models produce."""

import re
from pathlib import Path

import lkml

ROOT = Path(__file__).resolve().parents[2]
LOOKML = ROOT / "lookml"


def _parsed():
    return {p: lkml.load(p.read_text()) for p in sorted(LOOKML.rglob("*.lkml"))}


def test_every_lookml_file_parses():
    parsed = _parsed()
    assert {p.name for p in parsed} == {
        "fct_mrr_monthly.view.lkml", "fct_arr_movements.view.lkml", "seats_to_cash.model.lkml"
    }  # fmt: skip
    model = parsed[LOOKML / "models/seats_to_cash.model.lkml"]
    assert [e["name"] for e in model["explores"]] == ["fct_arr_movements"]
    assert model["explores"][0]["joins"][0]["name"] == "fct_mrr_monthly"


def test_view_columns_exist_in_their_dbt_models():
    for path, parsed in _parsed().items():
        for view in parsed.get("views", []):
            model_sql = (ROOT / "models/marts" / f"{view['name']}.sql").read_text()
            assert view["sql_table_name"].lower() == f"marts.{view['name']}"
            fields = view.get("dimensions", []) + view.get("dimension_groups", [])
            fields += view.get("measures", [])
            columns = set()
            for field in fields:
                columns |= set(re.findall(r"\$\{TABLE\}\.(\w+)", field.get("sql", "")))
            assert columns, path
            for column in columns:
                assert re.search(rf"\b{column}\b", model_sql), f"{path.name}: {column}"
