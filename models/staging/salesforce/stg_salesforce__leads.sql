select id as lead_id, account_id as salesforce_account_id, lead_source, status, created_date
from {{ source('salesforce', 'lead') }}
where not is_deleted
