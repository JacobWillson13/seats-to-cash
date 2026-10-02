-- Every live Stripe customer mapped to its tailnet and canonical customer (resolves D01).
-- Canonical customers carry tailnet metadata; a customer re-created without metadata is
-- matched to the canonical customer with the same normalized email.
with canonical as (
    select stripe_customer_id, metadata_tailnet_id as tailnet_id, email_normalized
    from {{ ref('stg_stripe__customers') }}
    where metadata_tailnet_id is not null
)

select
    c.stripe_customer_id,
    coalesce(c.metadata_tailnet_id, by_email.tailnet_id) as tailnet_id,
    coalesce(
        case when c.metadata_tailnet_id is not null then c.stripe_customer_id end,
        by_email.stripe_customer_id
    ) as canonical_stripe_customer_id,
    case
        when c.metadata_tailnet_id is not null then 'metadata'
        when by_email.stripe_customer_id is not null then 'email'
        else 'unmatched'
    end as resolution_method
from {{ ref('stg_stripe__customers') }} as c
left join canonical as by_email
    on c.metadata_tailnet_id is null and by_email.email_normalized = c.email_normalized
