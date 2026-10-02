-- Legacy (v3) exposure at the latest month end: current MRR on the retained active-user price
-- vs. projected MRR if the tailnet moved to the matching v4 seat plan today with one seat per
-- logged-in user (Starter -> Standard, Premium -> Premium), with its discount (ADR-022).
with legacy as (
    select *
    from {{ ref('fct_mrr_monthly') }}
    where price_version = 'v3'
        and month = (select max(month) from {{ ref('fct_mrr_monthly') }})
),

v4 as (
    select plan_code, unit_amount_usd from {{ ref('price_book') }} where price_version = 'v4'
),

projected as (
    select
        l.month,
        l.tailnet_id,
        l.subscription_id,
        l.plan_code,
        l.discount_pct,
        l.quantity as billable_active_users,
        l.mrr_usd as legacy_mrr_usd,
        case when l.plan_code = 'starter' then 'standard' else l.plan_code end
            as projected_plan_code,
        coalesce(u.logged_in_users, 0) as projected_seats,
        v4.unit_amount_usd as projected_unit_usd
    from legacy as l
    left join {{ ref('int_users_month_end') }} as u
        on u.tailnet_id = l.tailnet_id and u.month = l.month
    left join v4
        on v4.plan_code = case when l.plan_code = 'starter' then 'standard' else l.plan_code end
),

priced as (
    select
        *,
        round(projected_unit_usd * projected_seats, 2)
        - round(round(projected_unit_usd * projected_seats, 2) * discount_pct, 2)
            as projected_v4_mrr_usd
    from projected
)

select
    month,
    tailnet_id,
    subscription_id,
    plan_code,
    billable_active_users,
    legacy_mrr_usd,
    projected_plan_code,
    projected_seats,
    projected_v4_mrr_usd,
    projected_v4_mrr_usd - legacy_mrr_usd as mrr_delta_usd,
    12 * (projected_v4_mrr_usd - legacy_mrr_usd) as arr_delta_usd,
    case when legacy_mrr_usd > 0 then (projected_v4_mrr_usd - legacy_mrr_usd) / legacy_mrr_usd end
        as uplift_pct,
    case
        when legacy_mrr_usd = 0 then 'high'
        when (projected_v4_mrr_usd - legacy_mrr_usd) / legacy_mrr_usd
            > {{ var('migration_high_uplift') }} then 'high'
        when (projected_v4_mrr_usd - legacy_mrr_usd) / legacy_mrr_usd
            > {{ var('migration_medium_uplift') }} then 'medium'
        else 'low'
    end as migration_risk_tier
from priced
