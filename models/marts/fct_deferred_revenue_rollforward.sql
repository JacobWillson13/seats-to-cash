-- Deferred revenue rollforward on gross line amounts: opening + billings - revenue = closing.
-- Billings use the service-period start month (ADR-005), so an arrears invoice issued after
-- month end still bills in its service month; a negative balance is unbilled revenue.
-- closing_check is computed independently from each line's unrecognized remainder.
with lines as (
    select line_id, service_start, service_month, amount_usd
    from {{ ref('int_invoice_lines') }} where not is_internal
),

daily as (
    select line_id, revenue_date, revenue_usd
    from {{ ref('int_line_revenue_daily') }} where not is_internal
),

billings as (
    select service_month as month, sum(amount_usd) as billings_usd from lines group by 1
),

revenue as (
    select cast({{ dbt.date_trunc('month', 'revenue_date') }} as date) as month,
           sum(revenue_usd) as revenue_usd
    from daily group by 1
),

monthly as (
    select
        m.month_start as month,
        m.month_end,
        coalesce(b.billings_usd, 0) as billings_usd,
        coalesce(r.revenue_usd, 0) as revenue_usd
    from {{ ref('int_months') }} as m
    left join billings as b on b.month = m.month_start
    left join revenue as r on r.month = m.month_start
),

rolled as (
    select
        *,
        sum(billings_usd - revenue_usd) over (
            order by month rows between unbounded preceding and current row
        ) as closing_usd
    from monthly
),

-- Independent check: for each month end, billed lines started by then less what those lines
-- have recognized by then.
billed_to_date as (
    select m.month_start as month, sum(l.amount_usd) as billed_usd
    from {{ ref('int_months') }} as m
    inner join lines as l on l.service_start <= m.month_end
    group by 1
),

recognized_to_date as (
    select m.month_start as month, sum(d.revenue_usd) as recognized_usd
    from {{ ref('int_months') }} as m
    inner join daily as d on d.revenue_date <= m.month_end
    group by 1
)

select
    r.month,
    cast(coalesce(lag(r.closing_usd) over (order by r.month), 0) as numeric(18, 2))
        as opening_usd,
    cast(r.billings_usd as numeric(18, 2)) as billings_usd,
    cast(r.revenue_usd as numeric(18, 2)) as revenue_usd,
    cast(r.closing_usd as numeric(18, 2)) as closing_usd,
    cast(coalesce(b.billed_usd, 0) - coalesce(c.recognized_usd, 0) as numeric(18, 2))
        as closing_check_usd
from rolled as r
left join billed_to_date as b on b.month = r.month
left join recognized_to_date as c on c.month = r.month
