"""make close: the as-of timestamp and the refusal to re-close a posted period."""

import datetime as dt
import importlib.util
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
    assert close.posted(database, "2026-09") == 0
    import duckdb

    with duckdb.connect(database) as con:
        con.execute(
            "insert into finance_close.close_ledger values "
            "('2026-09', 'revenue_usd', 1.00, timestamp '2026-10-08 06:59:59', date '2026-10-07')"
        )
    assert close.main(["--period", "2026-09", "--database", database]) == 2
    assert "already closed" in capsys.readouterr().err
