select tailnet_id, activity_date, feature, attempts, gated_blocked, _fivetran_synced
from {{ source('app', 'feature_usage_daily') }}
where not _fivetran_deleted and {{ as_of('_fivetran_synced') }}
