select id as credit_note_id, invoice_id as orb_invoice_id, customer_id as orb_customer_id, type,
       reason, {{ to_usd('total') }} as total_usd, effective_date, created_at, voided_at,
       _exported_at
from {{ source('orb', 'credit_notes') }}
where voided_at is null
