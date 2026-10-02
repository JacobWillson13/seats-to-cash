select
    id as line_id,
    invoice_id as orb_invoice_id,
    subscription_id,
    price_id as orb_price_id,
    line_type,
    applies_to_line_id,
    name as line_name,
    start_date,
    end_date,
    quantity,
    {{ to_usd('unit_amount') }} as unit_amount_usd,
    {{ to_usd('amount') }} as amount_usd,
    _exported_at
from {{ source('orb', 'invoice_line_items') }}
where {{ as_of('_exported_at') }}
