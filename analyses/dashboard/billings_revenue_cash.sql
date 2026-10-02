-- Billings vs. revenue vs. cash by month: billings by service-period start, revenue by
-- recognition net of refunds and credit notes, cash by Stripe settlement net of fees.
select
    month,
    billings_usd,
    invoiced_usd,
    revenue_usd,
    recognized_revenue_usd,
    refunds_usd,
    credit_notes_usd,
    cash_collected_usd,
    fees_usd,
    net_cash_usd,
    billings_usd - revenue_usd as billings_less_revenue_usd,
    net_cash_usd - revenue_usd as cash_less_revenue_usd
from {{ ref('fct_billings_revenue_cash') }}
where month >= cast('{{ var("reporting_start_date") }}' as date)
order by month
