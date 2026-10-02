-- external_price_id is the price-book price_id (seeds/price_book.csv).
select id as orb_price_id, plan_id as orb_plan_id, external_price_id as price_id, item_name,
       model_type, {{ to_usd('unit_amount') }} as unit_amount_usd, package_size, cadence,
       billing_timing, _exported_at
from {{ source('orb', 'prices') }}
where {{ as_of('_exported_at') }}
