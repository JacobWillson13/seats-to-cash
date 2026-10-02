-- One row per tailnet with an Orb customer: its Orb, canonical Stripe, and Salesforce IDs.
with stripe as (
    select
        tailnet_id,
        max(canonical_stripe_customer_id) as stripe_customer_id,
        count(*) as stripe_customer_records
    from {{ ref('int_stripe_customer_map') }}
    where tailnet_id is not null
    group by tailnet_id
),

accounts as (
    select tailnet_id, salesforce_account_id
    from {{ ref('stg_salesforce__accounts') }}
    where tailnet_id is not null
    qualify row_number() over (partition by tailnet_id order by created_date) = 1
)

select
    c.tailnet_id,
    c.orb_customer_id,
    s.stripe_customer_id,
    coalesce(s.stripe_customer_records, 0) as stripe_customer_records,
    a.salesforce_account_id,
    coalesce(t.is_internal, false) as is_internal
from {{ ref('stg_orb__customers') }} as c
left join stripe as s on s.tailnet_id = c.tailnet_id
left join accounts as a on a.tailnet_id = c.tailnet_id
left join {{ ref('stg_app__tailnets') }} as t on t.tailnet_id = c.tailnet_id
