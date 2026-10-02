-- Seats held and occupied at the end of each month's last local day, per tailnet.
select
    m.month_start as month,
    e.tailnet_id,
    e.seats_held_after as seats_held,
    e.seats_occupied_after as seats_occupied
from {{ ref('int_months') }} as m
inner join {{ ref('stg_app__seat_events') }} as e on e.occurred_date <= m.month_end
qualify row_number() over (
    partition by m.month_start, e.tailnet_id order by e.occurred_at desc, e.seat_event_id desc
) = 1
