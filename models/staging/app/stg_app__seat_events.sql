select
    id as seat_event_id,
    tailnet_id,
    user_id,
    event_type,
    seats_held_after,
    seats_occupied_after,
    actor,
    occurred_at,
    {{ local_date('occurred_at') }} as occurred_date,
    _fivetran_synced
from {{ source('app', 'seat_events') }}
where not _fivetran_deleted and {{ as_of('_fivetran_synced') }}
