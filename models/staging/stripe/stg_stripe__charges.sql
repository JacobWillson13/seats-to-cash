-- Latest version of each live charge. Soft-deleted rows (D09) and test mode (D13) are dropped.
select
    id as stripe_charge_id,
    customer_id as stripe_customer_id,
    invoice_id as stripe_invoice_id,
    {{ cents_to_usd('amount') }} as amount_usd,
    {{ cents_to_usd('amount_refunded') }} as amount_refunded_usd,
    currency,
    created,
    {{ local_date('created') }} as created_date,
    status,
    paid,
    refunded,
    failure_code,
    payment_method_type,
    balance_transaction_id
from {{ source('stripe', 'charge') }}
where livemode and {{ as_of('_fivetran_synced') }}
qualify row_number() over (partition by id order by _fivetran_synced desc) = 1
    and not _fivetran_deleted
