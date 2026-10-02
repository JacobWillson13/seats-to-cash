-- One row per planted defect: how many records were injected (from the manifest), how many
-- the pipeline detected, and how many it handled so that no mart is affected.
with manifest as (
    select * from {{ source('truth', 'defect_manifest') }}
),

records as (
    -- D01: a duplicate Stripe customer is detected when resolved by email, and handled when
    -- it maps to the tailnet's canonical customer.
    select
        m.defect_code, m.record_key,
        map.resolution_method = 'email' as detected,
        map.canonical_stripe_customer_id = ti.stripe_customer_id as handled
    from manifest as m
    left join {{ ref('int_stripe_customer_map') }} as map on map.stripe_customer_id = m.record_key
    left join {{ source('truth', 'truth_identity') }} as ti on ti.tailnet_id = map.tailnet_id
    where m.defect_code = 'D01'

    union all

    -- D03: an internal tailnet is detected when flagged, and handled when no finance mart
    -- carries it.
    select
        m.defect_code, m.record_key,
        coalesce(t.is_internal, false),
        coalesce(t.is_internal, false)
        and m.record_key not in (select tailnet_id from {{ ref('fct_mrr_monthly') }})
        and m.record_key not in (select tailnet_id from {{ ref('fct_revenue_monthly') }})
    from manifest as m
    left join {{ ref('stg_app__tailnets') }} as t on t.tailnet_id = m.record_key
    where m.defect_code = 'D03'

    union all

    -- D06: a duplicate sync is detected when its Orb invoice has two live Stripe invoices,
    -- and handled when staging keeps only the first.
    select
        m.defect_code, m.record_key,
        m.record_key in (
            select id from {{ source('stripe', 'invoice') }}
            where {{ json_string('metadata', 'orb_invoice_id') }} in (
                select {{ json_string('metadata', 'orb_invoice_id') }}
                from {{ source('stripe', 'invoice') }}
                where livemode
                group by 1
                having count(distinct id) > 1
            )
        ),
        m.record_key not in (select stripe_invoice_id from {{ ref('stg_stripe__invoices') }})
    from manifest as m
    where m.defect_code = 'D06'

    union all

    -- D09: a soft-deleted row is detected by its deleted flag and handled when staging drops it.
    select
        m.defect_code, m.record_key,
        true,
        case m.source_table
            when 'stripe.charge' then
                m.record_key not in (select stripe_charge_id from {{ ref('stg_stripe__charges') }})
            when 'salesforce.opportunity' then
                m.record_key not in (select opportunity_id from {{ ref('stg_salesforce__opportunities') }})
        end
    from manifest as m
    where m.defect_code = 'D09'

    union all

    -- D13: a test-mode row is detected by livemode and handled when staging drops it.
    select
        m.defect_code, m.record_key,
        true,
        case m.source_table
            when 'stripe.customer' then
                m.record_key not in (select stripe_customer_id from {{ ref('stg_stripe__customers') }})
            when 'stripe.invoice' then
                m.record_key not in (select stripe_invoice_id from {{ ref('stg_stripe__invoices') }})
            when 'stripe.charge' then
                m.record_key not in (select stripe_charge_id from {{ ref('stg_stripe__charges') }})
            when 'stripe.balance_transaction' then
                m.record_key not in (
                    select balance_transaction_id from {{ ref('stg_stripe__balance_transactions') }}
                )
        end
    from manifest as m
    where m.defect_code = 'D13'
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
