-- Revenue by tailnet and month: line revenue recognized by service day, less refunds in the
-- month issued and credit notes in their effective month (ADR-015). Internal tailnets excluded.
with identity as (
    select tailnet_id, orb_customer_id, is_internal from {{ ref('int_identity') }}
),

recognized as (
    select
        tailnet_id,
        cast({{ dbt.date_trunc('month', 'revenue_date') }} as date) as month,
        sum(revenue_usd) as recognized_usd
    from {{ ref('int_line_revenue_daily') }}
    where revenue_date <= cast('{{ var("end_date") }}' as date)
    group by 1, 2
),

refunds as (
    select
        i.tailnet_id,
        cast({{ dbt.date_trunc('month', 'r.created_date') }} as date) as month,
        sum(r.amount_usd) as refunds_usd
    from {{ ref('stg_stripe__refunds') }} as r
    inner join {{ ref('stg_stripe__charges') }} as ch on ch.stripe_charge_id = r.stripe_charge_id
    inner join {{ ref('stg_stripe__invoices') }} as si on si.stripe_invoice_id = ch.stripe_invoice_id
    inner join {{ ref('stg_orb__invoices') }} as oi on oi.orb_invoice_id = si.orb_invoice_id
    inner join identity as i on i.orb_customer_id = oi.orb_customer_id
    where r.created_date <= cast('{{ var("end_date") }}' as date)
    group by 1, 2
),

credits as (
    select
        i.tailnet_id,
        cast({{ dbt.date_trunc('month', 'cn.effective_date') }} as date) as month,
        sum(cn.total_usd) as credit_notes_usd
    from {{ ref('stg_orb__credit_notes') }} as cn
    inner join identity as i on i.orb_customer_id = cn.orb_customer_id
    where cn.effective_date <= cast('{{ var("end_date") }}' as date)
    group by 1, 2
),

keys as (
    select tailnet_id, month from recognized
    union
    select tailnet_id, month from refunds
    union
    select tailnet_id, month from credits
)

select
    k.month,
    k.tailnet_id,
    cast(coalesce(rec.recognized_usd, 0) as numeric(18, 2)) as recognized_usd,
    cast(coalesce(ref.refunds_usd, 0) as numeric(18, 2)) as refunds_usd,
    cast(coalesce(cr.credit_notes_usd, 0) as numeric(18, 2)) as credit_notes_usd,
    cast(
        coalesce(rec.recognized_usd, 0) - coalesce(ref.refunds_usd, 0)
        - coalesce(cr.credit_notes_usd, 0) as numeric(18, 2)
    ) as revenue_usd
from keys as k
inner join identity as i on i.tailnet_id = k.tailnet_id and not i.is_internal
left join recognized as rec on rec.tailnet_id = k.tailnet_id and rec.month = k.month
left join refunds as ref on ref.tailnet_id = k.tailnet_id and ref.month = k.month
left join credits as cr on cr.tailnet_id = k.tailnet_id and cr.month = k.month
