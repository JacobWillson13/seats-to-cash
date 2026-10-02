select
    id as device_registration_id,
    tailnet_id,
    user_id,
    machine_key_hash,
    os,
    is_tagged,
    registered_at,
    removed_at,
    _fivetran_synced
from {{ source('app', 'device_registrations') }}
where not _fivetran_deleted
