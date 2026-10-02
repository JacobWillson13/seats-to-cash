select tailnet_id, activity_month, active_users, user_devices, _fivetran_synced
from {{ source('app', 'tailnet_activity_monthly') }}
where not _fivetran_deleted
