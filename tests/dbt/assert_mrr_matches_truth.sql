select * from {{ ref('audit_mrr_vs_truth') }} where status <> 'match'
