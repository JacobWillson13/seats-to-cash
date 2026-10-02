-- ARR movements between consecutive month ends, one row per tailnet, month, and movement type
-- with a non-zero amount (ADR-007).
--   new / reactivation: no subscription last month; reactivation if one existed earlier.
--   churn:              a subscription last month and none this month.
--   expansion / contraction and repricing: when the plan, price version, or discount changes
--   (or, for a contract, its per-seat value), the quantity change is valued at last month's
--   per-unit ARR and the remainder is repricing, so the split always closes exactly.
--   Otherwise the whole change is expansion or contraction.
with mrr as (
    select
        *,
        min(month) over (partition by tailnet_id) as first_month
    from {{ ref('fct_mrr_monthly') }}
),

pairs as (
    select
        coalesce(c.month, cast({{ dbt.dateadd('month', 1, 'p.month') }} as date)) as month,
        coalesce(c.tailnet_id, p.tailnet_id) as tailnet_id,
        coalesce(c.first_month, p.first_month) as first_month,
        p.arr_usd as prior_arr,
        p.quantity as prior_quantity,
        c.arr_usd as current_arr,
        c.quantity as current_quantity,
        p.tailnet_id is not null and c.tailnet_id is not null
        and (
            p.plan_code <> c.plan_code
            or p.price_version <> c.price_version
            or p.discount_pct <> c.discount_pct
            or (
                c.billing_basis = 'contract' and p.quantity > 0 and c.quantity > 0
                and p.arr_usd * c.quantity <> c.arr_usd * p.quantity
            )
        ) as price_changed
    from mrr as c
    full outer join mrr as p
        on p.tailnet_id = c.tailnet_id
        and c.month = cast({{ dbt.dateadd('month', 1, 'p.month') }} as date)
),

split as (
    select
        month,
        tailnet_id,
        case
            when prior_arr is null and month = first_month then current_arr else 0
        end as new_arr,
        case
            when prior_arr is null and month > first_month then current_arr else 0
        end as reactivation_arr,
        case when current_arr is null then -prior_arr else 0 end as churn_arr,
        case
            when prior_arr is null or current_arr is null then 0
            when not price_changed then current_arr - prior_arr
            when prior_quantity > 0
                then round((current_quantity - prior_quantity) * prior_arr / prior_quantity, 2)
            else 0
        end as quantity_arr,
        case
            when prior_arr is null or current_arr is null or not price_changed then 0
            when prior_quantity > 0
                then current_arr - prior_arr
                    - round((current_quantity - prior_quantity) * prior_arr / prior_quantity, 2)
            else current_arr - prior_arr
        end as repricing_arr
    from pairs
    where month <= cast('{{ var("end_date") }}' as date)
),

movements as (
    select month, tailnet_id, 'new' as movement_type, new_arr as arr_delta_usd from split
    union all
    select month, tailnet_id, 'reactivation', reactivation_arr from split
    union all
    select month, tailnet_id, 'churn', churn_arr from split
    union all
    select month, tailnet_id, case when quantity_arr > 0 then 'expansion' else 'contraction' end,
        quantity_arr
    from split
    union all
    select month, tailnet_id, 'repricing', repricing_arr from split
)

select month, tailnet_id, movement_type, cast(arr_delta_usd as numeric(18, 2)) as arr_delta_usd
from movements
where arr_delta_usd <> 0
