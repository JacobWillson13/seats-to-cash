"""People, companies, and tailnet signups (SPEC 2.4, 4.4, 4.5).

Every entity created here draws from its own entity stream (ADR-023), so its attributes don't
depend on how many other entities exist. Population counts in config are totals over the whole
simulation, from sim_start_date through end_date. Internal tailnets (D03) come on top of
`population.business_tailnets`, which counts trial signups only.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

import numpy as np
from faker.providers.company.en_US import Provider as CompanyProvider
from faker.providers.person.en_US import Provider as PersonProvider

from generator.clock import PHASE_LIFECYCLE, SECONDS_PER_DAY, Calendar
from generator.config import SimulationConfig
from generator.rng import Stream, entity_rng

CURRENCIES = ("USD", "EUR", "GBP")
WIREFERN_NAME = "Wirefern"
WIREFERN_DOMAIN = "wirefern.example"
KIND_TRIAL, KIND_INTERNAL, KIND_CHILD, KIND_DIRECT = 0, 1, 2, 3

# Cosmetic string formats (not behavior): email local parts and company names.
PERSONAL_LOCAL_FORMATS = ("{f}.{l}", "{f}{l}", "{i}{l}", "{f}.{l}{n}", "{f}{n}", "{f}_{l}")
PERSONAL_LOCAL_WEIGHTS = (0.30, 0.20, 0.15, 0.15, 0.10, 0.10)
WORK_LOCAL_FORMATS = ("{f}.{l}", "{i}{l}", "{f}", "{f}{j}")
WORK_LOCAL_WEIGHTS = (0.50, 0.30, 0.10, 0.10)
COMPANY_FORMAT_WEIGHTS = (0.5, 0.3, 0.2)  # Faker's three en_US company formats


class NamePool:
    def __init__(self, weighted: dict[str, float]):
        self.names = list(weighted)
        cumulative = np.cumsum(np.fromiter(weighted.values(), float))
        self._cdf = cumulative / cumulative[-1]

    def pick(self, u: float | np.ndarray):
        return np.minimum(np.searchsorted(self._cdf, u, side="right"), len(self.names) - 1)


FIRST_NAMES = NamePool(PersonProvider.first_names)
LAST_NAMES = NamePool(PersonProvider.last_names)
SUFFIXES = CompanyProvider.company_suffixes


def _pick(weights, u: float) -> int:
    return min(
        int(np.searchsorted(np.cumsum(weights) / sum(weights), u, side="right")), len(weights) - 1
    )


def _clean(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def local_part(fmt: str, first: str, last: str, number: int) -> str:
    first_part, last_part = _clean(first), _clean(last)
    return fmt.format(f=first_part, l=last_part, i=first_part[0], j=last_part[0], n=number)


@dataclass
class People:
    """Tailnet creators. A bring-to-work creator has both a personal and a work email."""

    first: list[str]
    last: list[str]
    personal_email: list[str | None]
    work_email: list[str | None]

    def add(self, first, last, personal_email=None, work_email=None) -> int:
        self.first.append(first)
        self.last.append(last)
        self.personal_email.append(personal_email)
        self.work_email.append(work_email)
        return len(self.first) - 1


@dataclass
class PersonalSignups:
    """Personal tailnets by ordinal (creation order), plus their users."""

    created_day: np.ndarray
    created_sec: np.ndarray
    currency: np.ndarray
    creator: np.ndarray  # person index
    employed: np.ndarray
    plus_retire: np.ndarray  # moves to free during the Personal Plus retirement window
    plus_retire_offset: np.ndarray  # days after v4_effective_date
    # users: creator first, then extras, grouped by tailnet ordinal
    user_tailnet: np.ndarray
    user_join_day: np.ndarray
    user_join_sec: np.ndarray
    user_is_creator: np.ndarray
    user_email: list[str]


@dataclass
class BusinessSignups:
    """Trial and internal tailnets by business ordinal (creation order)."""

    created_day: np.ndarray
    created_sec: np.ndarray
    kind: np.ndarray
    lead_day: np.ndarray
    close_day: np.ndarray
    lead_source: np.ndarray  # 0 PQL, 1 Inbound, 2 Outbound
    currency: np.ndarray
    nonprofit: np.ndarray
    company: np.ndarray
    creator: np.ndarray  # person index
    personal_first: np.ndarray
    origin_personal: np.ndarray  # personal ordinal, -1 if none
    shared_machine: np.ndarray
    localpart_reuse: np.ndarray
    initial_users: np.ndarray
    company_size: np.ndarray  # employees; caps the tailnet's users
    growth_mult: np.ndarray
    approval_required: np.ndarray
    advanced_interest: np.ndarray
    premium_interest: np.ndarray
    tagged_resources: np.ndarray
    ephemeral: np.ndarray


@dataclass
class Population:
    people: People
    company_name: list[str]
    company_domain: list[str]
    personal: PersonalSignups
    business: BusinessSignups


def monthly_counts(total: int, n_months: int, growth: float) -> np.ndarray:
    """Split `total` signups over months growing at `growth` per month (largest remainder)."""
    weights = (1 + growth) ** np.arange(n_months)
    exact = total * weights / weights.sum()
    counts = np.floor(exact).astype(np.int64)
    short = total - counts.sum()
    counts[np.argsort(-(exact - counts), kind="stable")[:short]] += 1
    return counts


def _schedule(config: SimulationConfig, cal: Calendar, total: int):
    """(month, slot) for each signup slot, month-major. Slots key the entity streams."""
    counts = monthly_counts(total, len(cal.months), config.population.signup_growth_monthly)
    month = np.repeat(np.arange(len(counts)), counts)
    return month, np.arange(total)


def _day_in_month(cal: Calendar, month: int, u: float) -> int:
    first, last = cal.month_start[month], cal.month_end[month]
    return int(first + min(int(u * (last - first + 1)), last - first))


class _Emails:
    """Assigns unique addresses in call order by suffixing a number on collision."""

    def __init__(self):
        self.taken: set[str] = set()

    def claim(self, local: str, domain: str) -> str:
        candidate, k = f"{local}@{domain}", 2
        while candidate in self.taken:
            candidate, k = f"{local}{k}@{domain}", k + 1
        self.taken.add(candidate)
        return candidate


def build_population(
    config: SimulationConfig, cal: Calendar, *, internal: bool = True
) -> Population:
    seed = config.seed
    people = People([], [], [], [])
    emails = _Emails()
    webmail = list(config.people.webmail_domains)
    webmail_w = list(config.people.webmail_domains.values())
    ccy_w = [config.population.currencies.get(c, 0.0) for c in CURRENCIES]

    # Personal tailnets: draw each slot from its own stream, then order by creation time.
    p_month, p_slots = _schedule(config, cal, config.population.personal_tailnets)
    drawn = []
    for month, slot in zip(p_month.tolist(), p_slots.tolist(), strict=True):
        rng = entity_rng(seed, Stream.PERSONAL_SIGNUP, slot)
        u = rng.random(12)
        day = _day_in_month(cal, month, u[0])
        sec = int(u[1] * SECONDS_PER_DAY)
        extras = int(rng.poisson(config.personal.extra_users_mean))
        extra_u = rng.random((extras, 6))
        drawn.append((day, sec, slot, u, extras, extra_u))
    drawn.sort(key=lambda r: (r[0], r[1], r[2]))

    n_p = len(drawn)
    p = {
        k: np.zeros(n_p, dt)
        for k, dt in [
            ("created_day", np.int32),
            ("created_sec", np.int32),
            ("currency", np.int8),
            ("creator", np.int32),
            ("employed", bool),
            ("plus_retire", bool),
            ("plus_retire_offset", np.int16),
        ]
    }
    u_tailnet, u_day, u_sec, u_creator, u_email = [], [], [], [], []
    v4_day = cal.day(config.v4_effective_date)
    for ordinal, (day, sec, _slot, u, _extras, extra_u) in enumerate(drawn):
        first = FIRST_NAMES.names[FIRST_NAMES.pick(u[3])]
        last = LAST_NAMES.names[LAST_NAMES.pick(u[4])]
        fmt = PERSONAL_LOCAL_FORMATS[_pick(PERSONAL_LOCAL_WEIGHTS, u[5])]
        email = emails.claim(
            local_part(fmt, first, last, 10 + int(u[6] * 90)), webmail[_pick(webmail_w, u[7])]
        )
        p["created_day"][ordinal], p["created_sec"][ordinal] = day, sec
        p["currency"][ordinal] = _pick(ccy_w, u[2])
        p["creator"][ordinal] = people.add(first, last, personal_email=email)
        p["employed"][ordinal] = u[8] < config.people.employed_share
        p["plus_retire"][ordinal] = u[9] < config.personal.plus_retirement_downgrade_share
        p["plus_retire_offset"][ordinal] = int(u[10] * config.personal.plus_retirement_window_days)
        max_users = 3 if day < v4_day else 6
        u_tailnet.append(ordinal), u_day.append(day), u_sec.append(sec)
        u_creator.append(True), u_email.append(email)
        for e in extra_u[: max_users - 1]:
            join = min(day + int(e[0] * 30), cal.n_days - 1)
            first_e = FIRST_NAMES.names[FIRST_NAMES.pick(e[1])]
            last_e = LAST_NAMES.names[LAST_NAMES.pick(e[2])]
            fmt_e = PERSONAL_LOCAL_FORMATS[_pick(PERSONAL_LOCAL_WEIGHTS, e[3])]
            u_tailnet.append(ordinal), u_day.append(join)
            u_sec.append(sec if join == day else int(e[4] * SECONDS_PER_DAY))
            u_creator.append(False)
            u_email.append(
                emails.claim(
                    local_part(fmt_e, first_e, last_e, 10 + int(e[5] * 90)),
                    webmail[_pick(webmail_w, e[4])],
                )
            )
    personal = PersonalSignups(
        **p,
        user_tailnet=np.array(u_tailnet, np.int32),
        user_join_day=np.array(u_day, np.int32),
        user_join_sec=np.maximum(np.array(u_sec, np.int32), 0),
        user_is_creator=np.array(u_creator, bool),
        user_email=u_email,
    )
    # A join on the creation day can't precede the creation second.
    same_day = personal.user_join_day == personal.created_day[personal.user_tailnet]
    personal.user_join_sec = np.where(
        same_day,
        np.maximum(personal.user_join_sec, personal.created_sec[personal.user_tailnet]),
        personal.user_join_sec,
    )

    # Business-domain signups: trials, then internal tailnets, ordered by creation time.
    b_month, b_slots = _schedule(config, cal, config.population.business_tailnets)
    rows = []
    for month, slot in zip(b_month.tolist(), b_slots.tolist(), strict=True):
        rng = entity_rng(seed, Stream.BUSINESS_SIGNUP, slot)
        rows.append(_business_draws(config, cal, rng, KIND_TRIAL, slot, month=month))
    n_internal = config.population.internal_tailnets if internal else 0
    for k in range(n_internal):
        rng = entity_rng(seed, Stream.INTERNAL_SIGNUP, k)
        rows.append(_business_draws(config, cal, rng, KIND_INTERNAL, k, month=None))
    rows.sort(key=lambda r: (r["created_day"], r["created_sec"], r["kind"], r["slot"]))
    direct_month, direct_slots = _schedule(config, cal, config.enterprise.direct_sales_accounts)
    for month, slot in zip(direct_month.tolist(), direct_slots.tolist(), strict=True):
        rng = entity_rng(seed, Stream.DIRECT_SALES_SIGNUP, slot)
        row = _business_draws(config, cal, rng, KIND_DIRECT, slot, month=month)
        row["lead_day"] = row["created_day"]
        lo, hi = config.enterprise.lead_to_close_lag_days
        row["close_day"] = row["lead_day"] + int(rng.integers(lo, hi + 1))
        row["created_day"] = row["close_day"]  # no product tailnet before signing
        row["lead_source"] = 1 + int(rng.integers(0, 2))
        row["company_size"] = max(row["company_size"], config.enterprise.lead_seat_threshold)
        rows.append(row)
    # Direct rows append after the existing PLG ordinals so their identities remain stable.

    # Bring-to-work: link personal-first creators to an earlier personal tailnet (SPEC 4.4).
    pool = [i for i in range(n_p) if personal.employed[i]]
    pool_days = [int(personal.created_day[i]) for i in pool]
    company_name, company_domain = [], []
    domains_taken: set[str] = set()
    for ordinal, r in enumerate(rows):
        r["origin_personal"] = -1
        if r["kind"] == KIND_INTERNAL:
            r["company"] = _company(company_name, company_domain, domains_taken, WIREFERN_NAME)
        else:
            r["company"] = _company(company_name, company_domain, domains_taken, r["company_name"])
        domain = company_domain[r["company"]]
        if r["personal_first"]:
            eligible = bisect.bisect_left(pool_days, r["created_day"])
            if eligible == 0:
                r["personal_first"] = False
            else:
                link_rng = entity_rng(seed, Stream.BRING_TO_WORK, ordinal)
                j = int(link_rng.random() * eligible)
                origin = pool.pop(j)
                pool_days.pop(j)
                r["origin_personal"] = origin
                person = int(personal.creator[origin])
                personal_local = people.personal_email[person].split("@")[0]
                if r["localpart_reuse"]:
                    local = personal_local
                else:
                    local = _work_local(people.first[person], people.last[person], r["work_fmt"])
                    if local == personal_local:
                        local = _work_local(
                            people.first[person], people.last[person], (r["work_fmt"] + 1) % 4
                        )
                people.work_email[person] = emails.claim(local, domain)
                r["creator"] = person
        if not r["personal_first"]:
            r["shared_machine"] = r["localpart_reuse"] = False
            local = _work_local(r["first"], r["last"], r["work_fmt"])
            r["creator"] = people.add(r["first"], r["last"], work_email=emails.claim(local, domain))

    fields = [
        ("created_day", np.int32),
        ("created_sec", np.int32),
        ("kind", np.int8),
        ("lead_day", np.int32),
        ("close_day", np.int32),
        ("lead_source", np.int8),
        ("currency", np.int8),
        ("nonprofit", bool),
        ("company", np.int32),
        ("creator", np.int32),
        ("personal_first", bool),
        ("origin_personal", np.int32),
        ("shared_machine", bool),
        ("localpart_reuse", bool),
        ("initial_users", np.int32),
        ("company_size", np.int32),
        ("growth_mult", np.float64),
        ("approval_required", bool),
        ("advanced_interest", bool),
        ("premium_interest", bool),
        ("tagged_resources", np.int32),
        ("ephemeral", bool),
    ]
    business = BusinessSignups(**{f: np.array([r[f] for r in rows], t) for f, t in fields})
    return Population(people, company_name, company_domain, personal, business)


def _work_local(first: str, last: str, fmt: int) -> str:
    return local_part(WORK_LOCAL_FORMATS[fmt], first, last, 0)


def _company(names: list[str], domains: list[str], taken: set[str], name: str) -> int:
    if name == WIREFERN_NAME:
        if WIREFERN_DOMAIN in taken:
            return domains.index(WIREFERN_DOMAIN)
        slug = WIREFERN_DOMAIN.removesuffix(".example")
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace(" and ", " ")).strip("-")
    candidate, k = f"{slug}.example", 2
    while candidate in taken:
        candidate, k = f"{slug}-{k}.example", k + 1
    taken.add(candidate)
    names.append(name)
    domains.append(candidate)
    return len(names) - 1


def _business_draws(config, cal, rng, kind, slot, *, month):
    u = rng.random(24)
    if month is None:  # internal tailnets spread evenly over the whole simulation
        day = min(int(u[0] * cal.n_days), cal.n_days - 1)
    else:
        day = _day_in_month(cal, month, u[0])
    lo, hi = PHASE_LIFECYCLE
    last_names = [LAST_NAMES.names[LAST_NAMES.pick(x)] for x in u[9:12]]
    company_fmt = _pick(COMPANY_FORMAT_WEIGHTS, u[8])
    company_name = (
        f"{last_names[0]} {SUFFIXES[int(u[12] * len(SUFFIXES))]}",
        f"{last_names[0]}-{last_names[1]}",
        f"{last_names[0]}, {last_names[1]} and {last_names[2]}",
    )[company_fmt]
    a = config.activity
    overage = u[20] < config.addons.tagged_resource_overage_share
    tagged = (
        50 + 1 + int(rng.poisson(a.tagged_resources_overage_mean))
        if overage
        else min(50, int(rng.poisson(a.tagged_resources_mean)))
    )
    shape = config.seats.growth_gamma_shape
    initial_users = max(1, int(round(rng.lognormal(
        config.seats.initial_users_lognormal.mean, config.seats.initial_users_lognormal.sigma
    ))))  # fmt: skip
    size = config.seats.company_size_lognormal
    company_size = max(initial_users, int(round(rng.lognormal(size.mean, size.sigma))))
    ccy_w = [config.population.currencies.get(c, 0.0) for c in CURRENCIES]
    internal = kind == KIND_INTERNAL
    return {
        "slot": slot,
        "kind": kind,
        "lead_day": -1,
        "close_day": -1,
        "lead_source": 0,
        "created_day": day,
        "created_sec": lo + int(u[1] * (hi - lo)),
        "currency": 0 if internal else _pick(ccy_w, u[2]),
        "nonprofit": (not internal) and u[3] < config.population.nonprofit_share,
        "personal_first": kind == KIND_TRIAL and u[4] < config.people.personal_first_share,
        "shared_machine": u[5] < config.people.same_machine_share,
        "localpart_reuse": u[6] < config.people.email_localpart_reuse,
        "company_name": WIREFERN_NAME if internal else company_name,
        "first": FIRST_NAMES.names[FIRST_NAMES.pick(u[13])],
        "last": LAST_NAMES.names[LAST_NAMES.pick(u[14])],
        "work_fmt": _pick(WORK_LOCAL_WEIGHTS, u[15]),
        "initial_users": initial_users,
        "company_size": company_size,
        "growth_mult": float(rng.gamma(shape, 1.0 / shape)),
        "approval_required": u[16] < config.seats.approval_required_share,
        "advanced_interest": u[17] < a.advanced_feature_interest_share,
        "premium_interest": u[18] < a.premium_feature_interest_share,
        "tagged_resources": tagged,
        "ephemeral": u[21] < a.ephemeral_share,
    }
