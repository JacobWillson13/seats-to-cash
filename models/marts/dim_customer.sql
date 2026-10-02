-- One row per tailnet with an Orb customer: identity, profile, enterprise source, and the
-- latest month-end MRR. Internal tailnets are kept and flagged.
with latest_mrr as (
    select tailnet_id, plan_code, price_version, billing_basis, quantity, mrr_usd, arr_usd, month
    from {{ ref('fct_mrr_monthly') }}
    qualify row_number() over (partition by tailnet_id order by month desc) = 1
),

first_paid as (
    select tailnet_id, min(month) as first_paid_month
    from {{ ref('fct_mrr_monthly') }} where mrr_usd > 0 group by 1
),

enterprise as (
    select a.tailnet_id, o.enterprise_source, o.lead_source
    from {{ ref('stg_salesforce__opportunities') }} as o
    inner join {{ ref('stg_salesforce__accounts') }} as a
        on a.salesforce_account_id = o.salesforce_account_id
    where o.opportunity_type = 'New Business' and a.tailnet_id is not null
)

select
    i.tailnet_id,
    t.tailnet_name,
    t.signup_domain,
    t.created_date,
    t.is_nonprofit,
    i.is_internal,
    i.orb_customer_id,
    i.stripe_customer_id,
    i.stripe_customer_records,
    i.salesforce_account_id,
    e.enterprise_source,
    e.lead_source,
    f.first_paid_month,
    l.month as latest_mrr_month,
    l.plan_code as latest_plan_code,
    l.price_version as latest_price_version,
    l.quantity as latest_quantity,
    coalesce(l.mrr_usd, 0) as latest_mrr_usd,
    coalesce(l.arr_usd, 0) as latest_arr_usd,
    l.month = cast({{ dbt.date_trunc('month', "cast('" ~ var('end_date') ~ "' as date)") }} as date)
        as is_active_at_end
from {{ ref('int_identity') }} as i
left join {{ ref('stg_app__tailnets') }} as t on t.tailnet_id = i.tailnet_id
left join enterprise as e on e.tailnet_id = i.tailnet_id
left join first_paid as f on f.tailnet_id = i.tailnet_id
left join latest_mrr as l on l.tailnet_id = i.tailnet_id
