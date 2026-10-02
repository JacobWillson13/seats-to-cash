select
    id as balance_transaction_id,
    source as source_id,
    type,
    {{ cents_to_usd('amount') }} as amount_usd,
    {{ cents_to_usd('fee') }} as fee_usd,
    {{ cents_to_usd('net') }} as net_usd,
    currency,
    created,
    {{ local_date('created') }} as created_date,
    available_on,
    status
from {{ source('stripe', 'balance_transaction') }}
where livemode and not _fivetran_deleted and {{ as_of('_fivetran_synced') }}
