-- Each invoice line's amount spread evenly over its inclusive service days, rounded half away
-- from zero to the cent, with the residual on the last day (BILLING_DESIGN). A proration line
-- covers only its remaining days, so its daily rate follows from its own amount and span.
with lines as (
    select
        line_id,
        tailnet_id,
        is_internal,
        line_class,
        service_start,
        service_end,
        amount_usd,
        cast(amount_usd * 100 as bigint) as amount_cents,
        {{ dbt.datediff('service_start', 'service_end', 'day') }} + 1 as service_days
    from {{ ref('int_invoice_lines') }}
),

regular as (
    select
        *,
        {{ div_round_cents("amount_cents", "service_days") }}
            as regular_cents
    from lines
)

select
    r.line_id,
    r.tailnet_id,
    r.is_internal,
    r.line_class,
    cast({{ dbt.dateadd('day', 'k.n', 'r.service_start') }} as date) as revenue_date,
    {{ cents_to_usd(
        "case when k.n < r.service_days - 1 then r.regular_cents"
        ~ " else r.amount_cents - r.regular_cents * (r.service_days - 1) end"
    ) }} as revenue_usd
from regular as r
inner join {{ numbers_10k() }} as k on k.n < r.service_days
