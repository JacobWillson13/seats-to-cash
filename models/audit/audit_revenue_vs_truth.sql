-- fct_revenue_monthly against the answer key, tailnet by month (internal tailnets excluded).
with truth as (
    select * from {{ source('truth', 'truth_revenue_monthly') }} where not is_internal
)

select
    coalesce(f.month, t.month) as month,
    coalesce(f.tailnet_id, t.tailnet_id) as tailnet_id,
    f.revenue_usd,
    t.revenue_usd as truth_revenue_usd,
    case
        when t.tailnet_id is null then 'extra_in_mart'
        when f.tailnet_id is null then 'missing_in_mart'
        when f.revenue_usd = t.revenue_usd then 'match'
        else 'mismatch'
    end as status
from {{ ref('fct_revenue_monthly') }} as f
full outer join truth as t on t.tailnet_id = f.tailnet_id and t.month = f.month
