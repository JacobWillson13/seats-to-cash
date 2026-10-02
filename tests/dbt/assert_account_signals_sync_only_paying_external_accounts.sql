-- Hightouch syncs only eligible rows: a Salesforce account linked to a paying, non-internal
-- tailnet. Utilization stays within [0, 1].
select s.*
from {{ ref('fct_account_signals') }} as s
left join {{ ref('int_identity') }} as i on i.tailnet_id = s.tailnet_id
where (s.sync_eligible and (s.arr_usd <= 0 or coalesce(i.is_internal, false)))
    or (not s.sync_eligible and s.arr_usd > 0 and not coalesce(i.is_internal, false))
    or s.seat_utilization < 0 or s.seat_utilization > 1
