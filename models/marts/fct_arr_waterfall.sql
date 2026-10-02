-- Monthly ARR waterfall: opening + movements = closing (the reconciliation test checks it).
with arr as (
    select month, sum(arr_usd) as arr_usd from {{ ref('fct_mrr_monthly') }} group by month
),

moves as (
    select
        month,
        sum(case when movement_type = 'new' then arr_delta_usd else 0 end) as new_usd,
        sum(case when movement_type = 'expansion' then arr_delta_usd else 0 end) as expansion_usd,
        sum(case when movement_type = 'repricing' then arr_delta_usd else 0 end) as repricing_usd,
        sum(case when movement_type = 'contraction' then arr_delta_usd else 0 end)
            as contraction_usd,
        sum(case when movement_type = 'churn' then arr_delta_usd else 0 end) as churn_usd,
        sum(case when movement_type = 'reactivation' then arr_delta_usd else 0 end)
            as reactivation_usd
    from {{ ref('fct_arr_movements') }}
    group by month
)

select
    m.month_start as month,
    coalesce(o.arr_usd, 0) as opening_arr_usd,
    coalesce(v.new_usd, 0) as new_usd,
    coalesce(v.expansion_usd, 0) as expansion_usd,
    coalesce(v.repricing_usd, 0) as repricing_usd,
    coalesce(v.contraction_usd, 0) as contraction_usd,
    coalesce(v.churn_usd, 0) as churn_usd,
    coalesce(v.reactivation_usd, 0) as reactivation_usd,
    coalesce(c.arr_usd, 0) as closing_arr_usd
from {{ ref('int_months') }} as m
left join arr as c on c.month = m.month_start
left join arr as o on o.month = cast({{ dbt.dateadd('month', -1, 'm.month_start') }} as date)
left join moves as v on v.month = m.month_start
