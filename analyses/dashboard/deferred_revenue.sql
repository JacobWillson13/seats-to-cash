-- Deferred revenue rollforward by month: opening + billings - revenue = closing. A negative
-- balance is revenue recognized before its arrears invoice (unbilled).
select
    month,
    opening_usd,
    billings_usd,
    revenue_usd,
    closing_usd,
    closing_usd = closing_check_usd as ties_out
from {{ ref('fct_deferred_revenue_rollforward') }}
where month >= cast('{{ var("reporting_start_date") }}' as date)
order by month
