select
    id as plan_change_id,
    tailnet_id,
    changed_at,
    {{ local_date('changed_at') }} as changed_date,
    from_plan_code,
    to_plan_code,
    from_price_version,
    to_price_version,
    change_source,
    _fivetran_synced
from {{ source('app', 'plan_changes') }}
where not _fivetran_deleted and {{ as_of('_fivetran_synced') }}
