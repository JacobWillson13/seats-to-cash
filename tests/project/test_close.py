"""make close: the as-of timestamp, the refusal to re-close, and the Snowflake ledger path."""

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("close", ROOT / "scripts/close.py")
close = importlib.util.module_from_spec(spec)
spec.loader.exec_module(close)


def test_as_of_is_the_end_of_the_close_date_in_los_angeles():
    assert close.close_date("2026-09") == dt.date(2026, 10, 7)
    # 2026-10-07 is daylight time (UTC-7): local midnight after it is 07:00 UTC on the 8th.
    assert close.as_of_utc(dt.date(2026, 10, 7), "America/Los_Angeles") == (
        "2026-10-08 06:59:59.999999"
    )
    # 2026-02-06 is standard time (UTC-8).
    assert close.as_of_utc(dt.date(2026, 2, 6), "America/Los_Angeles") == (
        "2026-02-07 07:59:59.999999"
    )
    with pytest.raises(SystemExit, match="no close date"):
        close.close_date("2031-01")


def test_a_posted_period_is_refused_without_force(tmp_path, capsys):
    database = str(tmp_path / "ledger.duckdb")
    ledger = close.DuckDBLedger(database)
    assert ledger.posted("2026-09") == 0
    ledger.con.execute(
        "insert into finance_close.close_ledger values "
        "('2026-09', 'revenue_usd', 1.00, timestamp '2026-10-08 06:59:59', date '2026-10-07')"
    )
    ledger.close()
    assert close.main(["--period", "2026-09", "--database", database]) == 2
    assert "already closed on duckdb" in capsys.readouterr().err


def test_duckdb_ledger_posts_and_replaces_a_period(tmp_path):
    database = str(tmp_path / "ledger.duckdb")
    ledger = close.DuckDBLedger(database)
    ledger.posted("2026-09")
    ledger.con.execute("create schema asof_marts")
    ledger.con.execute(
        "create table asof_marts.fct_close_metrics as select '2026-09' as period, "
        "'revenue_usd' as metric, cast(10.50 as numeric(18, 2)) as value_usd"
    )
    for _ in range(2):  # the second post replaces the first
        rows = ledger.post("2026-09", "2026-10-08 06:59:59.999999", dt.date(2026, 10, 7),
                           replace=True)  # fmt: skip
    assert rows == [("revenue_usd", Decimal("10.50"))]
    assert ledger.con.execute("select * from finance_close.close_ledger").fetchall() == [
        ("2026-09", "revenue_usd", Decimal("10.50"),
         dt.datetime(2026, 10, 8, 6, 59, 59, 999999), dt.date(2026, 10, 7))
    ]  # fmt: skip
    ledger.close()


class FakeCursor:
    def __init__(self, log, results):
        self.log, self.results = log, results

    def execute(self, sql, params=()):
        self.log.append((sql, tuple(params)))
        self.rows = self.results.get(" ".join(sql.split()[:2]), [])
        return self

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, results):
        self.log, self.results = [], results

    def cursor(self):
        return FakeCursor(self.log, self.results)

    def close(self):
        pass


def test_snowflake_ledger_uses_pyformat_and_one_transaction():
    con = FakeConnection(
        {"select count(*)": [(0,)], "select metric,": [("revenue_usd", Decimal("10.50"))]}
    )
    ledger = close.Ledger(con)
    ledger.placeholder = "%s"  # what SnowflakeLedger sets for snowflake-connector-python
    assert ledger.posted("2026-09") == 0
    ledger.post("2026-09", "2026-10-08 06:59:59.999999", dt.date(2026, 10, 7), replace=True)
    statements = [sql for sql, _ in con.log]
    assert statements[:2] == list(close.LEDGER_DDL)
    assert all("?" not in sql for sql in statements)
    assert [s.split()[0] for s in statements[3:]] == [
        "select", "begin", "delete", "insert", "commit"
    ]  # fmt: skip
    assert con.log[-2][1] == (
        "2026-09", "revenue_usd", Decimal("10.50"), "2026-10-08 06:59:59.999999", "2026-10-07"
    )  # fmt: skip


def test_snowflake_close_builds_on_the_snowflake_target_with_dotenv(tmp_path, monkeypatch):
    for key in list(close.os.environ):
        if key.startswith("SNOWFLAKE_"):
            monkeypatch.delenv(key)
    env = tmp_path / ".env"
    env.write_text("SNOWFLAKE_ACCOUNT=ab12345\nSNOWFLAKE_PRIVATE_KEY_PATH=/keys/rsa.p8\n")
    cfg = close.snowflake_settings(env)
    assert cfg["SNOWFLAKE_DATABASE"] == "SEATS_TO_CASH"
    assert close.os.environ["SNOWFLAKE_ACCOUNT"] == "ab12345"  # visible to profiles.yml
    args = close.dbt_args("2026-10-08 06:59:59.999999", "snowflake")
    assert args[:3] == ["build", "--target", "snowflake"]
    assert '{"as_of_ts": "2026-10-08 06:59:59.999999"}' in args
    assert "snowflake_load" in sys.modules
