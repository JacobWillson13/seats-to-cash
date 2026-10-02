select * from {{ ref('audit_revenue_vs_truth') }} where status <> 'match'
