-- Latest exported version of each Orb customer.
select
    id as orb_customer_id,
    external_customer_id as tailnet_id,
    name,
    email,
    currency,
    payment_provider,
    payment_provider_id,
    billing_country,
    created_at,
    _exported_at
from {{ source('orb', 'customers') }}
where {{ as_of('_exported_at') }}
qualify row_number() over (partition by id order by _exported_at desc) = 1
