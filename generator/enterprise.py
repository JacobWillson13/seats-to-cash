"""Immutable enterprise contract facts drawn at lifecycle events, before Orb rendering.

Contracts come from two sources: PLG tailnets that reach the seat threshold and close
(`plg`), and direct-sales accounts that sign before any product tailnet exists (`direct`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from generator.rng import Stream, entity_rng

CENT = Decimal("0.01")
SOURCE = ("plg", "direct")
EVENT_KIND = ("close", "renewal", "expansion")


@dataclass(frozen=True)
class ContractEvent:
    tailnet: int
    day: int
    sec: int
    kind: str
    enterprise_source: str
    term_months: int
    contract_start_day: int
    contract_end_day: int
    seats: int
    price_id: str
    discount_pct: Decimal
    recurring_acv: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def record(sim, idx, day, sec, kind: str, rng: np.random.Generator) -> None:
    """Record contract price facts once, from a per-contract entity stream. USD only."""
    from generator.lifecycle import State

    cfg, b, book = sim.config, sim.b, sim.seeds.price_book
    idx = np.asarray(idx, np.int64)
    secs = np.broadcast_to(sec, idx.shape)
    e = cfg.enterprise
    floor = Decimal(str(e.min_acv_usd))
    for tailnet, second in zip(idx.tolist(), secs.tolist(), strict=True):
        rng = entity_rng(cfg.seed, Stream.ENTERPRISE_CONTRACT, tailnet, day, EVENT_KIND.index(kind))
        prior = sim.latest_contract.get(tailnet)
        version = f"v{int(b.version[tailnet])}"
        price = book.plan_version_price(State.PREMIUM.name.lower(), version)
        unit = price.unit_amount()
        if kind == "close":
            discount = Decimal(str(rng.uniform(*e.discount_range)))
            acv = max(Decimal(int(b.held[tailnet])) * 12 * unit * (1 - discount), floor)
            start = day
        elif kind == "renewal":
            discount = prior.discount_pct
            uplift = Decimal(str(rng.exponential(e.renewal_uplift_mean)))
            acv = max(Decimal(int(b.held[tailnet])) * 12 * unit * (1 - discount), floor)
            acv = max(acv, prior.recurring_acv) * (1 + uplift)
            start = day
        else:  # expansion updates the annual contract value, and preserves its anniversary
            discount = prior.discount_pct
            extra = max(0, int(b.held[tailnet]) - prior.seats)
            acv = prior.recurring_acv + Decimal(extra) * 12 * unit * (1 - discount)
            start = prior.contract_start_day
        contract = ContractEvent(
            tailnet=tailnet,
            day=day,
            sec=int(second),
            kind=kind,
            enterprise_source=SOURCE[int(b.enterprise_source[tailnet])],
            term_months=int(b.term_months[tailnet]),
            contract_start_day=start,
            contract_end_day=int(b.term_end_day[tailnet]),
            seats=int(b.held[tailnet]),
            price_id=price.price_id,
            discount_pct=discount,
            recurring_acv=_money(acv),
        )
        sim.contract_events.append(contract)
        sim.latest_contract[tailnet] = contract
