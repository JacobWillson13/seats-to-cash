import datetime as dt
from decimal import Decimal

import pytest

from generator.pricebook import PriceBook, PriceBookError

from .conftest import SEEDS


@pytest.fixture(scope="module")
def book():
    return PriceBook.load(SEEDS / "price_book.csv")


@pytest.mark.parametrize("plan_code", ["premium", "personal", "enterprise"])
def test_list_price_switches_to_v4_on_2026_04_08(book, plan_code):
    assert book.list_price(plan_code, dt.date(2026, 4, 7)).price_version == "v3"
    assert book.list_price(plan_code, dt.date(2026, 4, 8)).price_version == "v4"


def test_retired_and_future_plans_are_not_sold(book):
    with pytest.raises(LookupError, match="no 'starter' price is on sale on 2026-04-08"):
        book.list_price("starter", dt.date(2026, 4, 8))
    with pytest.raises(LookupError, match="no 'standard' price is on sale on 2026-04-07"):
        book.list_price("standard", dt.date(2026, 4, 7))


def test_grandfathered_prices_stay_billable_by_id(book):
    starter = book.price("v3_starter")
    assert not starter.on_sale(dt.date(2026, 9, 1))
    assert starter.unit_amount("USD") == Decimal("6.00")
    assert starter.free_units == 3


def test_local_currency_prices(book):
    standard = book.price("v4_standard")
    assert [standard.unit_amount(c) for c in ("USD", "EUR", "GBP")] == [
        Decimal("8.00"),
        Decimal("7.00"),
        Decimal("7.00"),
    ]
    assert book.currencies == ("USD", "EUR", "GBP")
    with pytest.raises(LookupError, match="v4_enterprise has no list price in USD"):
        book.price("v4_enterprise").unit_amount("USD")


def test_discounts(book):
    assert book.price("disc_nonprofit").discount_pct == Decimal("0.50")
    assert book.price("disc_internal").discount_pct == Decimal("1.00")


def test_ambiguous_plan_code_points_to_price_id(book):
    with pytest.raises(LookupError, match=r"'addon' is ambiguous .* look it up with price\(\)"):
        book.list_price("addon", dt.date(2026, 5, 1))


def test_unknown_price_id(book):
    with pytest.raises(LookupError, match="no price with price_id 'v5_standard'"):
        book.price("v5_standard")


def test_malformed_price_book_reports_the_line(tmp_path):
    lines = (SEEDS / "price_book.csv").read_text().splitlines()
    path = tmp_path / "price_book.csv"
    path.write_text("\n".join([*lines, lines[1]]) + "\n")
    with pytest.raises(
        PriceBookError, match=rf"line {len(lines) + 1}: duplicate price_id v3_personal"
    ):
        PriceBook.load(path)
    path.write_text("\n".join([lines[0], lines[1].replace(",0.00,", ",,", 1)]) + "\n")
    with pytest.raises(PriceBookError, match=r"line 2: v3_personal has amounts in some currencies"):
        PriceBook.load(path)
