-- Current version of each tailnet (Fivetran history mode). Internal Wirefern tailnets (D03)
-- are flagged here and excluded downstream in finance marts.
select
    id as tailnet_id,
    name as tailnet_name,
    created_at,
    {{ local_date('created_at') }} as created_date,
    creator_user_id,
    signup_domain,
    plan_code,
    price_version,
    trial_started_at,
    trial_ended_at,
    currency,
    is_nonprofit,
    deleted_at,
    signup_domain = '{{ var("internal_domain") }}' as is_internal,
    _fivetran_start
from {{ source('app', 'tailnets') }}
where not _fivetran_deleted
qualify row_number() over (partition by id order by _fivetran_start desc) = 1
