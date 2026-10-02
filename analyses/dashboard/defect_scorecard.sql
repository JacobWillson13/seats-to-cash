-- Defect scorecard: each planted defect with its injected, detected, and handled record counts,
-- plus the answer-key match rates for MRR, revenue, and identity.
with checks as (
    select 'MRR tailnet-months matching truth' as check_name,
           count(*) as checked,
           sum(case when status = 'match' then 1 else 0 end) as passed
    from {{ ref('audit_mrr_vs_truth') }}
    union all
    select 'Revenue tailnet-months matching truth', count(*),
           sum(case when status = 'match' then 1 else 0 end)
    from {{ ref('audit_revenue_vs_truth') }}
    union all
    select 'Tailnets with the true Stripe and Salesforce IDs', count(*),
           sum(case when is_match then 1 else 0 end)
    from {{ ref('audit_identity_vs_truth') }}
)

select
    'defect' as kind,
    defect_code || ' ' || description as item,
    injected_records as checked,
    handled_records as passed,
    detected_records,
    fully_handled
from {{ ref('audit_defect_scorecard') }}
union all
select 'answer key', check_name, checked, passed, null, checked = passed
from checks
order by kind desc, item
