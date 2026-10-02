"""The Streamlit in Snowflake app runs end to end on the local DuckDB build.

A fake `snowflake.snowpark.context` hands the app a session that runs its SQL on
data/seats_to_cash.duckdb (or DUCKDB_PATH). The fully qualified SEATS_TO_CASH.MARTS and
SEATS_TO_CASH.AUDIT names resolve there because the DuckDB catalog is named after the file.
Column names come back upper case, as Snowpark returns them. Skipped until `make build` has
built the marts.
"""

import os
import re
import sys
import types
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/streamlit_app.py"
DATABASE = Path(os.environ.get("DUCKDB_PATH", ROOT / "data/seats_to_cash.duckdb"))


def _built() -> bool:
    if DATABASE.name != "seats_to_cash.duckdb" or not DATABASE.exists():
        return False
    try:
        with duckdb.connect(str(DATABASE), read_only=True) as con:
            con.execute("select 1 from marts.fct_arr_waterfall limit 1")
        return True
    except duckdb.Error:
        return False


class FakeSession:
    def __init__(self, con):
        self.con, self.queries = con, []

    def sql(self, query):
        self.queries.append(query)
        con = self.con

        class Result:
            def to_pandas(self):
                frame = con.sql(query).df()
                frame.columns = [c.upper() for c in frame.columns]
                return frame

        return Result()


def test_app_uses_only_preinstalled_packages_and_qualified_names():
    source = APP.read_text()
    imports = set(re.findall(r"^(?:from|import) ([\w.]+)", source, flags=re.M))
    allowed = {"__future__", "decimal", "altair", "pandas", "streamlit",
               "snowflake.snowpark.context"}  # fmt: skip
    assert imports <= allowed, imports - allowed
    tables = re.findall(r"\{(MARTS|AUDIT)\}\.(\w+)", source)
    assert tables and all(t.isupper() for _, t in tables)
    assert source.count("@st.cache_data") == source.count("return _frame(")
    assert "Synthetic data. Pricing mechanics modeled on public information." in source


@pytest.mark.skipif(not _built(), reason="run `make build` first")
def test_app_renders_every_section_from_the_build(monkeypatch):
    from streamlit.testing.v1 import AppTest

    con = duckdb.connect(str(DATABASE), read_only=True)
    session = FakeSession(con)
    context = types.ModuleType("snowflake.snowpark.context")
    context.get_active_session = lambda: session
    for name in ("snowflake", "snowflake.snowpark"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "snowflake.snowpark.context", context)

    app = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not app.exception, app.exception
    assert app.title[0].value.startswith("Seats to cash")
    assert [m.label for m in app.metric] == [
        app.metric[0].label,
        "ARR growth since Dec 2025",
        "Repricing share of 2026 growth",
        "Projected migration ARR change",
        "Defects handled",
    ]
    assert re.fullmatch(r"[0-6] of 6", app.metric[4].value)
    assert [h.value for h in app.subheader] == [
        "ARR",
        "Billings, revenue, and cash",
        "Legacy migration exposure",
        "Month-end close: restatements",
        "Data quality",
    ]
    assert app.caption[-1].value == (
        "Synthetic data. Pricing mechanics modeled on public information."
    )
    assert all("SEATS_TO_CASH." in q for q in session.queries)
    con.close()
