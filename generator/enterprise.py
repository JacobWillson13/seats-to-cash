"""Immutable enterprise contract facts drawn at lifecycle events, before Orb rendering."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from generator.population import CURRENCIES
from generator.rng import Stream, entity_rng

CENT = Decimal("0.01")
SOURCE = ("plg", "direct")
EVENT_KIND = ("close", "renewal", "expansion", "child")


@dataclass(frozen=True)
class ContractEvent:
    tailnet: int
    day: int
    sec: int
    kind: str
    enterprise_source: str
    parent: int
    term_months: int
    contract_start_day: int
    contract_end_day: int
    seats: int
    price_id: str
    currency: str
    channel: str
    discount_pct: Decimal
    recurring_acv: Decimal
    services_amount: Decimal
    services_delivery_day: int


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def record(sim, idx, day, sec, kind: str, rng: np.random.Generator) -> None:
    """Record price and service facts once, using the lifecycle RNG stream."""
    from generator.lifecycle import State

    cfg, b, book = sim.config, sim.b, sim.seeds.price_book
    idx = np.asarray(idx, np.int64)
    secs = np.broadcast_to(sec, idx.shape)
    e = cfg.enterprise
    for tailnet, second in zip(idx.tolist(), secs.tolist(), strict=True):
        rng = entity_rng(cfg.seed, Stream.ENTERPRISE_CONTRACT, tailnet, day, EVENT_KIND.index(kind))
        prior = sim.latest_contract.get(tailnet)
        version = f"v{int(b.version[tailnet])}"
        price = book.plan_version_price(State.PREMIUM.name.lower(), version)
        currency = CURRENCIES[int(b.currency[tailnet])]
        unit = price.unit_amount(currency)
        fx_day = min(sim.cal.dates[day], cfg.end_date)
        rate = sim.seeds.fx.usd_per_unit(currency, fx_day)
        floor = Decimal(str(e.min_acv_usd)) / rate
        if kind in ("close", "child"):
            if kind == "child" and b.parent[tailnet] in sim.latest_contract:
                discount = sim.latest_contract[int(b.parent[tailnet])].discount_pct
            else:
                discount = Decimal(str(rng.uniform(*e.discount_range)))
            acv = max(Decimal(int(b.held[tailnet])) * 12 * unit * (1 - discount), floor)
            services = Decimal(0)
            if kind == "close" and rng.random() < e.services_attach_rate:
                services_usd = Decimal(str(rng.uniform(*e.services_amount_usd)))
                services = _money(services_usd / rate)
            delivery = min(
                day
                + int(
                    rng.integers(
                        e.services_delivery_lag_days[0], e.services_delivery_lag_days[1] + 1
                    )
                ),
                sim.cal.n_days - 1,
            )
            start = day
        elif kind == "renewal":
            discount = prior.discount_pct
            uplift = Decimal(str(rng.exponential(e.renewal_uplift_mean)))
            acv = max(Decimal(int(b.held[tailnet])) * 12 * unit * (1 - discount), floor)
            acv *= 1 + uplift
            services, delivery, start = Decimal(0), -1, day
        else:  # expansion updates the annual contract value, and preserves its anniversary
            discount = prior.discount_pct
            extra = max(0, int(b.held[tailnet]) - prior.seats)
            acv = prior.recurring_acv + Decimal(extra) * 12 * unit * (1 - discount)
            services, delivery, start = Decimal(0), -1, prior.contract_start_day
        contract = ContractEvent(
            tailnet=tailnet,
            day=day,
            sec=int(second),
            kind=kind,
            enterprise_source=SOURCE[int(b.enterprise_source[tailnet])],
            parent=int(b.parent[tailnet]),
            term_months=int(b.term_months[tailnet]),
            contract_start_day=start,
            contract_end_day=int(b.term_end_day[tailnet]),
            seats=int(b.held[tailnet]),
            price_id=price.price_id,
            currency=currency,
            channel=("stripe", "aws_marketplace", "azure_marketplace")[int(b.channel[tailnet])],
            discount_pct=discount,
            recurring_acv=_money(acv),
            services_amount=services,
            services_delivery_day=delivery,
        )
        sim.contract_events.append(contract)
        sim.latest_contract[tailnet] = contract
