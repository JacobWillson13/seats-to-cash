"""Enterprise lead and opportunity facts, including open pipeline beyond the window."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from generator.app_db import Ids
from generator.population import KIND_DIRECT

OWNER = "005000000000001"
SOURCES = ("Product Qualified Lead", "Inbound", "Outbound")
COUNTRIES = ("US", "DE", "GB")


def _columns(table, rows):
    return {column.name: [row.get(column.name) for row in rows] for column in table.columns}


def render(sim):
    from generator.tables import SF_TABLES, TRUTH_TABLES

    b, cal, pop = sim.b, sim.cal, sim.pop
    ids = Ids(sim).business_tailnet
    contracts = {e.tailnet: e for e in sim.contract_events if e.kind == "close"}
    all_events = []
    for e in sim.contract_events:
        all_events.append(
            {
                "tailnet_id": ids[e.tailnet],
                "event_date": cal.dates[e.day],
                "event_kind": e.kind,
                "enterprise_source": e.enterprise_source,
                "parent_tailnet_id": ids[e.parent] if e.parent >= 0 else None,
                "price_id": e.price_id,
                "currency": e.currency,
                "channel": e.channel,
                "contract_start_date": cal.dates[e.contract_start_day],
                "contract_end_date": cal.start
                + __import__("datetime").timedelta(days=e.contract_end_day),
                "term_months": e.term_months,
                "seats": e.seats,
                "discount_pct": str(e.discount_pct),
                "recurring_acv": str(e.recurring_acv),
                "services_amount": str(e.services_amount),
                "services_delivery_date": cal.dates[e.services_delivery_day]
                if e.services_delivery_day >= 0
                else None,
            }
        )
    truth = {
        "truth_enterprise_contracts": _columns(
            TRUTH_TABLES["truth_enterprise_contracts"], all_events
        )
    }
    accounts, leads, opps = [], [], []
    for i in np.flatnonzero(b.lead & (b.lead_day >= 0)).tolist():
        lead_day = int(b.lead_day[i])
        if lead_day >= cal.n_days:
            continue
        source = SOURCES[int(b.lead_source[i])]
        account = f"001{i:012d}"
        opp = f"006{i:012d}"
        created = int(cal.epoch_us(lead_day, 54_000))
        close_day = int(b.close_day[i])
        close_date = cal.start + __import__("datetime").timedelta(
            days=close_day if close_day >= 0 else lead_day + 90
        )
        contract = contracts.get(i)
        company = int(b.company[i])
        common = {
            "id": account,
            "name": pop.company_name[company],
            "website": f"https://{pop.company_domain[company]}",
            "industry": None,
            "number_of_employees": int(b.company_size[i]),
            "billing_country": COUNTRIES[int(b.currency[i])],
            "owner_id": OWNER,
            "created_date": created,
            "tailnet_id__c": ids[i] if int(b.kind[i]) != KIND_DIRECT or contract else None,
            "customer_tier__c": "Enterprise" if contract else None,
            "is_deleted": False,
        }
        accounts.append(
            {
                **common,
                "type": "Prospect",
                "last_modified_date": created,
                "_fivetran_synced": created + 60_000_000,
            }
        )
        if contract:
            closed = int(cal.epoch_us(contract.day, contract.sec))
            accounts.append(
                {
                    **common,
                    "type": "Customer",
                    "last_modified_date": closed,
                    "_fivetran_synced": closed + 60_000_000,
                }
            )
        if b.kind[i] == KIND_DIRECT:
            leads.append(
                {
                    "id": f"00Q{i:012d}",
                    "account_id": account,
                    "lead_source": source,
                    "status": "Open",
                    "created_date": created,
                    "is_deleted": False,
                    "_fivetran_synced": created + 60_000_000,
                }
            )
        base = {
            "id": opp,
            "account_id": account,
            "name": f"{pop.company_name[company]} Enterprise",
            "type": "New Business",
            "amount": contract.recurring_acv if contract else None,
            "close_date": close_date,
            "created_date": created,
            "owner_id": OWNER,
            "lead_source": source,
            "contract_term_months__c": contract.term_months if contract else None,
            "contract_start_date__c": cal.dates[contract.day] if contract else None,
            "recurring_arr__c": contract.recurring_acv if contract else None,
            "purchase_channel__c": contract.channel if contract else None,
            "marketplace_offer_id__c": None,
            "is_deleted": False,
        }
        opps.append(
            {
                **base,
                "stage_name": "Qualification",
                "is_closed": False,
                "is_won": False,
                "probability": Decimal("0.35"),
                "last_modified_date": created,
                "_fivetran_synced": created + 60_000_000,
            }
        )
        if contract:
            closed = int(cal.epoch_us(contract.day, contract.sec))
            opps.append(
                {
                    **base,
                    "stage_name": "Closed Won",
                    "is_closed": True,
                    "is_won": True,
                    "probability": Decimal("1.00"),
                    "last_modified_date": closed,
                    "_fivetran_synced": closed + 60_000_000,
                }
            )
    rep = {
        "id": OWNER,
        "name": "Wirefern Sales",
        "email": "sales@wirefern.example",
        "user_role_name": "Enterprise Sales",
        "is_active": True,
        "is_deleted": False,
        "_fivetran_synced": int(cal.epoch_us(0, 0)),
    }
    sf = {
        "user": _columns(SF_TABLES["user"], [rep]),
        "account": _columns(SF_TABLES["account"], accounts),
        "lead": _columns(SF_TABLES["lead"], leads),
        "opportunity": _columns(SF_TABLES["opportunity"], opps),
    }
    return sf, truth
