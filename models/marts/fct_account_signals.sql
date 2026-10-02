-- Account signals for the Hightouch sync to Salesforce Account (SETUP): one row per Salesforce
-- account linked to a tailnet. Only sync-eligible rows are sent (ADR-022).
with latest_month as (
    select max(month) as month from {{ ref('fct_mrr_monthly') }}
),

mrr as (
    select f.*
    from {{ ref('fct_mrr_monthly') }} as f
    inner join latest_month as lm on lm.month = f.month
),

seats as (
    select s.*
    from {{ ref('int_seats_month_end') }} as s
    inner join latest_month as lm on lm.month = s.month
),

users as (
    select u.*
    from {{ ref('int_users_month_end') }} as u
    inner join latest_month as lm on lm.month = u.month
)

select
    a.salesforce_account_id,
    a.tailnet_id,
    cast(coalesce(m.arr_usd, 0) as numeric(18, 2)) as arr_usd,
    coalesce(s.seats_held, 0) as seats_held,
    coalesce(s.seats_occupied, u.logged_in_users, 0) as seats_occupied,
    case
        when coalesce(s.seats_held, 0) > 0
            then cast(s.seats_occupied as numeric(18, 4)) / s.seats_held
    end as seat_utilization,
    case
        when m.price_version = 'v3' then e.migration_risk_tier
        else 'none'
    end as migration_risk_tier,
    m.plan_code,
    m.price_version,
    m.tailnet_id is not null and m.arr_usd > 0 and not coalesce(i.is_internal, false)
        as sync_eligible
from {{ ref('stg_salesforce__accounts') }} as a
cross join latest_month as lm
left join mrr as m on m.tailnet_id = a.tailnet_id
left join seats as s on s.tailnet_id = a.tailnet_id
left join users as u on u.tailnet_id = a.tailnet_id
left join {{ ref('fct_migration_exposure') }} as e on e.tailnet_id = a.tailnet_id
left join {{ ref('int_identity') }} as i on i.tailnet_id = a.tailnet_id
where a.tailnet_id is not null
