select id as quantity_change_id, subscription_id, price_id as orb_price_id, effective_date, quantity,
       source, recorded_at, _exported_at
from {{ source('orb', 'subscription_quantity_changes') }}
where {{ as_of('_exported_at') }}
