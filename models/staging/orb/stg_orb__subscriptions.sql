-- Latest exported version of each subscription term.
select
    s.id as subscription_id,
    s.customer_id as orb_customer_id,
    s.plan_id as orb_plan_id,
    p.plan_code,
    p.price_version,
    s.status,
    s.start_date,
    s.end_date,
    s.net_terms,
    s.invoicing_channel,
    cast(s.discount_pct as numeric(5, 4)) as discount_pct,
    s.ended_reason,
    s.created_at,
    s._exported_at
from {{ source('orb', 'subscriptions') }} as s
left join {{ ref('stg_orb__plans') }} as p on p.orb_plan_id = s.plan_id
where {{ as_of('s._exported_at') }}
qualify row_number() over (partition by s.id order by s._exported_at desc) = 1
