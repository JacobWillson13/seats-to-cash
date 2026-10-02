-- Orb invoice lines with their tailnet, price-book plan, and a finance classification.
select
    l.line_id,
    l.orb_invoice_id,
    i.invoice_date,
    i.stripe_invoice_id,
    l.subscription_id,
    c.tailnet_id,
    coalesce(t.is_internal, false) as is_internal,
    l.line_type,
    pr.price_id,
    pb.plan_code,
    pb.price_version,
    pb.billing_basis,
    case
        when l.line_type = 'usage' then 'recurring_usage'
        when l.line_type = 'fixed' and pb.billing_basis = 'contract' then 'contract'
        when l.line_type = 'fixed' then 'recurring_seat'
        when l.line_type = 'proration' then 'proration'
        when l.line_type = 'discount' then 'discount'
        else 'other'
    end as line_class,
    l.applies_to_line_id,
    l.start_date as service_start,
    l.end_date as service_end,
    cast({{ dbt.date_trunc('month', 'l.start_date') }} as date) as service_month,
    l.quantity,
    l.unit_amount_usd,
    l.amount_usd
from {{ ref('stg_orb__invoice_line_items') }} as l
inner join {{ ref('stg_orb__invoices') }} as i on i.orb_invoice_id = l.orb_invoice_id
inner join {{ ref('stg_orb__customers') }} as c on c.orb_customer_id = i.orb_customer_id
left join {{ ref('stg_orb__prices') }} as pr on pr.orb_price_id = l.orb_price_id
left join {{ ref('price_book') }} as pb on pb.price_id = pr.price_id
left join {{ ref('stg_app__tailnets') }} as t on t.tailnet_id = c.tailnet_id
