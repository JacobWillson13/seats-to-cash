-- The SQL daily allocation reproduces Orb's own daily line revenue to the cent.
select coalesce(a.line_id, b.line_id) as line_id, coalesce(a.revenue_date, b.revenue_date) as day
from {{ ref('int_line_revenue_daily') }} as a
full outer join {{ ref('stg_orb__daily_line_item_revenue') }} as b
    on b.line_id = a.line_id and b.revenue_date = a.revenue_date
where a.revenue_usd is distinct from b.recognized_usd
