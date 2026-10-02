select tailnet_id, activity_date, active_users, user_devices, tagged_resources, ephemeral_minutes,
       _fivetran_synced
from {{ source('app', 'tailnet_activity_daily') }}
where not _fivetran_deleted
