select id as salesforce_user_id, name, email, user_role_name, is_active
from {{ source('salesforce', 'user') }}
where not is_deleted
