-- Users who have logged in and are not removed at each month's end, per tailnet: the seats a
-- tailnet would occupy on a seat plan.
select
    m.month_start as month,
    u.tailnet_id,
    count(*) as logged_in_users
from {{ ref('int_months') }} as m
inner join {{ ref('stg_app__users') }} as u
    on u.first_login_at is not null
    and {{ local_date('u.first_login_at') }} <= m.month_end
    and (u.removed_at is null or {{ local_date('u.removed_at') }} > m.month_end)
group by 1, 2
