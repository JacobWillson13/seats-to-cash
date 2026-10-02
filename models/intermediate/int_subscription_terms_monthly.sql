-- Each subscription active on a month's last day, with its retained price-book terms.
select
    m.month_start as month,
    m.month_end,
    s.subscription_id,
    c.tailnet_id,
    s.plan_code,
    s.price_version,
    pb.billing_basis,
    pb.unit_amount_usd,
    coalesce(pb.free_units, 0) as free_units,
    s.discount_pct,
    coalesce(t.is_internal, false) as is_internal
from {{ ref('int_months') }} as m
inner join {{ ref('stg_orb__subscriptions') }} as s
    on s.start_date <= m.month_end and (s.end_date is null or s.end_date >= m.month_end)
inner join {{ ref('stg_orb__customers') }} as c on c.orb_customer_id = s.orb_customer_id
left join {{ ref('price_book') }} as pb
    on pb.plan_code = s.plan_code and pb.price_version = s.price_version
left join {{ ref('stg_app__tailnets') }} as t on t.tailnet_id = c.tailnet_id
