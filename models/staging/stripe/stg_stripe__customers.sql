-- Live, undeleted Stripe customers. Test-mode rows (D13) and deleted rows are dropped.
select
    id as stripe_customer_id,
    created,
    email,
    lower(email) as email_normalized,
    name,
    currency,
    delinquent,
    {{ json_string('metadata', 'tailnet_id') }} as metadata_tailnet_id,
    {{ json_string('metadata', 'orb_customer_id') }} as metadata_orb_customer_id
from {{ source('stripe', 'customer') }}
where livemode and not _fivetran_deleted and not is_deleted
