-- Latest version of each live Stripe invoice, one per Orb invoice. A duplicate sync (D06)
-- carries the same orb_invoice_id under a second ID; the first sync wins.
with latest as (
    select *
    from {{ source('stripe', 'invoice') }}
    where livemode and not _fivetran_deleted
    qualify row_number() over (partition by id order by _fivetran_synced desc) = 1
)

select
    id as stripe_invoice_id,
    customer_id as stripe_customer_id,
    number as invoice_number,
    status,
    billing_reason,
    collection_method,
    currency,
    {{ cents_to_usd('subtotal') }} as subtotal_usd,
    {{ cents_to_usd('total') }} as total_usd,
    {{ cents_to_usd('amount_paid') }} as amount_paid_usd,
    {{ cents_to_usd('amount_remaining') }} as amount_remaining_usd,
    created,
    {{ local_date('created') }} as created_date,
    due_date,
    period_start,
    period_end,
    paid,
    charge_id as stripe_charge_id,
    {{ json_string('metadata', 'orb_invoice_id') }} as orb_invoice_id,
    {{ json_string('metadata', 'payment_source') }} as payment_source,
    status_transitions_paid_at as paid_at,
    status_transitions_marked_uncollectible_at as marked_uncollectible_at
from latest
qualify row_number() over (
    partition by {{ json_string('metadata', 'orb_invoice_id') }} order by created, id
) = 1
