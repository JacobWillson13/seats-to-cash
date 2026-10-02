-- fct_mrr_monthly against the answer key, tailnet by month: ARR to the cent, MRR rounded to
-- cents, and quantity. Internal tailnets (D03) are out of both sides. Any status other than
-- 'match' is a modeling error.
with truth as (
    select * from {{ source('truth', 'truth_mrr_monthly') }} where not is_internal
)

select
    coalesce(f.month, t.month) as month,
    coalesce(f.tailnet_id, t.tailnet_id) as tailnet_id,
    coalesce(f.billing_basis, t.billing_basis) as billing_basis,
    f.quantity,
    t.quantity as truth_quantity,
    f.mrr_usd,
    t.mrr_runrate_usd as truth_mrr_usd,
    f.arr_usd,
    t.arr_runrate_usd as truth_arr_usd,
    case
        when t.tailnet_id is null then 'extra_in_mart'
        when f.tailnet_id is null then 'missing_in_mart'
        -- ARR must match exactly; MRR (full precision in the mart) matches at cents.
        when f.arr_usd = t.arr_runrate_usd
            and round(f.mrr_usd, 2) = t.mrr_runrate_usd
            and f.quantity = t.quantity then 'match'
        else 'mismatch'
    end as status
from {{ ref('fct_mrr_monthly') }} as f
full outer join truth as t on t.tailnet_id = f.tailnet_id and t.month = f.month
