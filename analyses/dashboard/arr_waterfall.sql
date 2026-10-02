-- ARR waterfall by movement type: one row per month and movement, with opening and closing
-- ARR, for a stacked waterfall chart. Repricing is the legacy-to-seat price effect (ADR-007).
with w as (
    select * from {{ ref('fct_arr_waterfall') }}
    where month >= cast('{{ var("reporting_start_date") }}' as date)
),

movements as (
    select month, 1 as sort_order, 'opening' as step, opening_arr_usd as arr_usd from w
    union all select month, 2, 'new', new_usd from w
    union all select month, 3, 'expansion', expansion_usd from w
    union all select month, 4, 'repricing', repricing_usd from w
    union all select month, 5, 'reactivation', reactivation_usd from w
    union all select month, 6, 'contraction', contraction_usd from w
    union all select month, 7, 'churn', churn_usd from w
    union all select month, 8, 'closing', closing_arr_usd from w
)

select month, step, arr_usd
from movements
order by month, sort_order
