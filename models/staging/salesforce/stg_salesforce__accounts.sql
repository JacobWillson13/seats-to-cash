-- Latest version of each undeleted account.
select
    id as salesforce_account_id,
    name as account_name,
    website,
    type as account_type,
    number_of_employees,
    billing_country,
    owner_id,
    created_date,
    last_modified_date,
    tailnet_id__c as tailnet_id,
    customer_tier__c as customer_tier
from {{ source('salesforce', 'account') }}
where {{ as_of('_fivetran_synced') }}
qualify row_number() over (partition by id order by _fivetran_synced desc) = 1
    and not is_deleted
