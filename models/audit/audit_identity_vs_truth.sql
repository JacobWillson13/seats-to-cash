-- int_identity against the answer key: one canonical Stripe customer and Salesforce account
-- per tailnet.
select
    t.tailnet_id,
    i.stripe_customer_id,
    t.stripe_customer_id as truth_stripe_customer_id,
    i.salesforce_account_id,
    t.salesforce_account_id as truth_salesforce_account_id,
    coalesce(i.stripe_customer_id = t.stripe_customer_id,
             i.stripe_customer_id is null and t.stripe_customer_id is null)
    and coalesce(i.salesforce_account_id = t.salesforce_account_id,
                 i.salesforce_account_id is null and t.salesforce_account_id is null) as is_match
from {{ source('truth', 'truth_identity') }} as t
left join {{ ref('int_identity') }} as i on i.tailnet_id = t.tailnet_id
