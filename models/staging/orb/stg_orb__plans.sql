select id as orb_plan_id, external_plan_id as plan_code, name as plan_name, price_version, currency,
       created_at, _exported_at
from {{ source('orb', 'plans') }}
