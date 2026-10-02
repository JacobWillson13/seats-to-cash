select id as event_id, idempotency_key, event_name, external_customer_id as tailnet_id,
       {{ quoted("timestamp") }} as event_at, {{ local_date(quoted("timestamp")) }} as event_date, properties, _exported_at
from {{ source('orb', 'events') }}
where {{ as_of('_exported_at') }}
