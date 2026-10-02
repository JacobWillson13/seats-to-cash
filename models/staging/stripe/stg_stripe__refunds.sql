select
    id as stripe_refund_id,
    charge_id as stripe_charge_id,
    {{ cents_to_usd('amount') }} as amount_usd,
    currency,
    created,
    {{ local_date('created') }} as created_date,
    reason,
    status,
    balance_transaction_id,
    _fivetran_synced as loaded_at
from {{ source('stripe', 'refund') }}
where livemode and not _fivetran_deleted and status = 'succeeded'
    and {{ as_of('_fivetran_synced') }}
