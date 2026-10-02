-- Deferred revenue rollforward on gross line amounts: opening + billings - revenue = closing.
-- Billings use the service-period start month (ADR-005), so an arrears invoice issued after
-- month end still bills in its service month; a negative balance is unbilled revenue.
-- closing_check is computed independently from each line's unrecognized remainder.
with lines as (
    select * from {{ ref('int_invoice_lines') }} where not is_internal
),

daily as (
    select * from {{ ref('int_line_revenue_daily') }} where not is_internal
),

monthly as (
    select
        m.month_start as month,
        m.month_end,
        coalesce((select sum(l.amount_usd) from lines as l where l.service_month = m.month_start), 0)
            as billings_usd,
        coalesce((
            select sum(d.revenue_usd) from daily as d
            where d.revenue_date between m.month_start and m.month_end
        ), 0) as revenue_usd
    from {{ ref('int_months') }} as m
),

rolled as (
    select
        *,
        sum(billings_usd - revenue_usd) over (order by month rows unbounded preceding)
            as closing_usd
    from monthly
)

select
    r.month,
    cast(coalesce(lag(r.closing_usd) over (order by r.month), 0) as numeric(18, 2))
        as opening_usd,
    cast(r.billings_usd as numeric(18, 2)) as billings_usd,
    cast(r.revenue_usd as numeric(18, 2)) as revenue_usd,
    cast(r.closing_usd as numeric(18, 2)) as closing_usd,
    cast(
        coalesce((select sum(l.amount_usd) from lines as l where l.service_start <= r.month_end), 0)
        - coalesce((select sum(d.revenue_usd) from daily as d where d.revenue_date <= r.month_end), 0)
        as numeric(18, 2)
    ) as closing_check_usd
from rolled as r
