-- Orb's own daily revenue allocation; used only to cross-check int_line_revenue_daily.
select revenue_date, invoice_line_item_id as line_id, invoice_id as orb_invoice_id,
       customer_id as orb_customer_id, price_id as orb_price_id,
       {{ to_usd('recognized_amount') }} as recognized_usd, currency, _exported_at
from {{ source('orb', 'daily_line_item_revenue') }}
