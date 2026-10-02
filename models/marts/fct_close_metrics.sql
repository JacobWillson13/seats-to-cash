-- The close metrics for every reporting month, one row per period and metric. A close
-- (scripts/close.py) builds this model as of the close date and appends the period's rows to
-- the ledger; fct_restatements compares the ledger with this model's current values.
with w as (
    select * from {{ ref('fct_arr_waterfall') }}
),

b as (
    select * from {{ ref('fct_billings_revenue_cash') }}
),

d as (
    select * from {{ ref('fct_deferred_revenue_rollforward') }}
),

metrics as (
    select month, 'closing_arr_usd' as metric, closing_arr_usd as value_usd from w
    union all select month, 'new_arr_usd', new_usd from w
    union all select month, 'expansion_arr_usd', expansion_usd from w
    union all select month, 'repricing_arr_usd', repricing_usd from w
    union all select month, 'contraction_arr_usd', contraction_usd from w
    union all select month, 'churn_arr_usd', churn_usd from w
    union all select month, 'reactivation_arr_usd', reactivation_usd from w
    union all select month, 'billings_usd', billings_usd from b
    union all select month, 'recognized_revenue_usd', recognized_revenue_usd from b
    union all select month, 'refunds_usd', refunds_usd from b
    union all select month, 'credit_notes_usd', credit_notes_usd from b
    union all select month, 'revenue_usd', revenue_usd from b
    union all select month, 'net_cash_usd', net_cash_usd from b
    union all select month, 'deferred_revenue_usd', closing_usd from d
)

select
    {{ period_of('month') }} as period,
    metric,
    cast(value_usd as numeric(18, 2)) as value_usd
from metrics
where month >= cast('{{ var("reporting_start_date") }}' as date)
