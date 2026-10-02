-- Latest exported version of each invoice.
select
    id as orb_invoice_id,
    invoice_number,
    customer_id as orb_customer_id,
    subscription_id,
    status,
    currency,
    invoice_date,
    issued_at,
    service_period_start,
    service_period_end,
    due_date,
    paid_at,
    voided_at,
    {{ to_usd('subtotal') }} as subtotal_usd,
    {{ to_usd('discount_total') }} as discount_total_usd,
    {{ to_usd('tax') }} as tax_usd,
    {{ to_usd('total') }} as total_usd,
    {{ to_usd('amount_due') }} as amount_due_usd,
    external_sync_id as stripe_invoice_id,
    _exported_at
from {{ source('orb', 'invoices') }}
where {{ as_of('_exported_at') }}
qualify row_number() over (partition by id order by _exported_at desc) = 1
