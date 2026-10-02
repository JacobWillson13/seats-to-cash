-- One row per planted defect: how many records were injected (from the manifest), how many
-- the pipeline detected, and how many it handled so that no mart is affected.
with manifest as (
    select * from {{ source('truth', 'defect_manifest') }}
),

mart_tailnets as (
    select distinct tailnet_id from {{ ref('fct_mrr_monthly') }}
    union
    select distinct tailnet_id from {{ ref('fct_revenue_monthly') }}
),

raw_invoices as (
    select id, {{ json_string('metadata', 'orb_invoice_id') }} as orb_invoice_id
    from {{ source('stripe', 'invoice') }}
    where livemode
),

double_synced as (
    select distinct i.id
    from raw_invoices as i
    inner join (
        select orb_invoice_id from raw_invoices group by 1 having count(distinct id) > 1
    ) as d on d.orb_invoice_id = i.orb_invoice_id
),

staged as (
    select stripe_customer_id as record_key, 'stripe.customer' as source_table
    from {{ ref('stg_stripe__customers') }}
    union all
    select stripe_invoice_id, 'stripe.invoice' from {{ ref('stg_stripe__invoices') }}
    union all
    select stripe_charge_id, 'stripe.charge' from {{ ref('stg_stripe__charges') }}
    union all
    select balance_transaction_id, 'stripe.balance_transaction'
    from {{ ref('stg_stripe__balance_transactions') }}
    union all
    select opportunity_id, 'salesforce.opportunity' from {{ ref('stg_salesforce__opportunities') }}
),

records as (
    select
        m.defect_code,
        m.record_key,
        case m.defect_code
            -- D01: a duplicate Stripe customer resolved to its tailnet by email.
            when 'D01' then coalesce(map.resolution_method = 'email', false)
            -- D03: an internal tailnet flagged in staging.
            when 'D03' then coalesce(t.is_internal, false)
            -- D06: an Orb invoice with two live Stripe invoices.
            when 'D06' then ds.id is not null
            -- D09 and D13 are detectable from their deleted and livemode flags.
            else true
        end as detected,
        case m.defect_code
            -- D01: mapped to the tailnet's canonical customer.
            when 'D01' then coalesce(map.canonical_stripe_customer_id = ti.stripe_customer_id, false)
            -- D03: excluded from every finance mart.
            when 'D03' then coalesce(t.is_internal, false) and mt.tailnet_id is null
            -- D06, D09, D13: dropped by staging.
            else s.record_key is null
        end as handled
    from manifest as m
    left join {{ ref('int_stripe_customer_map') }} as map
        on m.defect_code = 'D01' and map.stripe_customer_id = m.record_key
    left join {{ source('truth', 'truth_identity') }} as ti
        on m.defect_code = 'D01' and ti.tailnet_id = map.tailnet_id
    left join {{ ref('stg_app__tailnets') }} as t
        on m.defect_code = 'D03' and t.tailnet_id = m.record_key
    left join mart_tailnets as mt on m.defect_code = 'D03' and mt.tailnet_id = m.record_key
    left join double_synced as ds on m.defect_code = 'D06' and ds.id = m.record_key
    left join staged as s
        on m.defect_code in ('D06', 'D09', 'D13')
        and s.record_key = m.record_key and s.source_table = m.source_table
),

described as (
    select 'D01' as defect_code, 'Duplicate Stripe customer' as description
    union all select 'D03', 'Internal Wirefern tailnets'
    union all select 'D05', 'Late refunds and credit notes'
    union all select 'D06', 'Duplicate Stripe invoice sync'
    union all select 'D09', 'Soft-deleted source rows'
    union all select 'D13', 'Stripe test-mode rows'
)

select
    d.defect_code,
    d.description,
    count(r.record_key) as injected_records,
    sum(case when r.detected then 1 else 0 end) as detected_records,
    sum(case when r.handled then 1 else 0 end) as handled_records,
    count(r.record_key) > 0
    and sum(case when r.handled then 1 else 0 end) = count(r.record_key) as fully_handled
from described as d
left join records as r on r.defect_code = d.defect_code
group by d.defect_code, d.description
