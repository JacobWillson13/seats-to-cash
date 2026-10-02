-- Current version of each user (Fivetran history mode).
select
    id as user_id,
    tailnet_id,
    email,
    role,
    invited_at,
    approved_at,
    first_login_at,
    removed_at,
    _fivetran_start
from {{ source('app', 'users') }}
where not _fivetran_deleted and {{ as_of('_fivetran_start') }}
qualify row_number() over (partition by id order by _fivetran_start desc) = 1
