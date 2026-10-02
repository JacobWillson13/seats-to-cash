-- Billings, revenue, and cash by month. Billings by service-period start, revenue by
-- recognition, cash by settlement (balance-transaction available_on), per ADR-005 and ADR-017.
with billings as (
    select service_month as month, sum(amount_usd) as billings_usd
    from {{ ref('int_invoice_lines') }} where not is_internal group by 1
),

invoiced as (
    select cast({{ dbt.date_trunc('month', 'i.invoice_date') }} as date) as month,
           sum(i.total_usd) as invoiced_usd
    from {{ ref('stg_orb__invoices') }} as i
    inner join {{ ref('int_identity') }} as id on id.orb_customer_id = i.orb_customer_id
    where not id.is_internal
    group by 1
),

revenue as (
    select month, sum(recognized_usd) as recognized_usd, sum(refunds_usd) as refunds_usd,
           sum(credit_notes_usd) as credit_notes_usd, sum(revenue_usd) as revenue_usd
    from {{ ref('fct_revenue_monthly') }} group by 1
),

cash as (
    select
        cast({{ dbt.date_trunc('month', 'available_on') }} as date) as month,
        sum(case when type = 'charge' then amount_usd else 0 end) as collected_usd,
        sum(case when type = 'refund' then -amount_usd else 0 end) as refunds_paid_usd,
        sum(fee_usd) as fees_usd,
        sum(net_usd) as net_cash_usd
    from {{ ref('stg_stripe__balance_transactions') }}
    group by 1
)

select
    m.month_start as month,
    cast(coalesce(b.billings_usd, 0) as numeric(18, 2)) as billings_usd,
    cast(coalesce(i.invoiced_usd, 0) as numeric(18, 2)) as invoiced_usd,
    cast(coalesce(r.recognized_usd, 0) as numeric(18, 2)) as recognized_revenue_usd,
    cast(coalesce(r.refunds_usd, 0) as numeric(18, 2)) as refunds_usd,
    cast(coalesce(r.credit_notes_usd, 0) as numeric(18, 2)) as credit_notes_usd,
    cast(coalesce(r.revenue_usd, 0) as numeric(18, 2)) as revenue_usd,
    cast(coalesce(c.collected_usd, 0) as numeric(18, 2)) as cash_collected_usd,
    cast(coalesce(c.refunds_paid_usd, 0) as numeric(18, 2)) as refunds_paid_usd,
    cast(coalesce(c.fees_usd, 0) as numeric(18, 2)) as fees_usd,
    cast(coalesce(c.net_cash_usd, 0) as numeric(18, 2)) as net_cash_usd
from {{ ref('int_months') }} as m
left join billings as b on b.month = m.month_start
left join invoiced as i on i.month = m.month_start
left join revenue as r on r.month = m.month_start
left join cash as c on c.month = m.month_start
