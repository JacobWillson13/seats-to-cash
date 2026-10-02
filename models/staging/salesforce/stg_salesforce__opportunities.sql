-- Latest version of each opportunity. Soft-deleted copies (D09) are dropped.
select
    id as opportunity_id,
    account_id as salesforce_account_id,
    name as opportunity_name,
    type as opportunity_type,
    stage_name,
    is_closed,
    is_won,
    amount as amount_usd,
    close_date,
    created_date,
    probability,
    lead_source,
    case when lead_source = 'Product Qualified Lead' then 'plg' else 'direct' end
        as enterprise_source,
    contract_term_months__c as contract_term_months,
    contract_start_date__c as contract_start_date,
    recurring_arr__c as recurring_arr_usd
from {{ source('salesforce', 'opportunity') }}
qualify row_number() over (partition by id order by _fivetran_synced desc) = 1
    and not is_deleted
