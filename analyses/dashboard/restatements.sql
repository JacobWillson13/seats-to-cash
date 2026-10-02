-- Restatements: closed figures that changed after the close, with the late refunds and credit
-- notes that explain them. Snowflake syntax.
select
    period,
    close_date,
    metric,
    closed_value_usd,
    current_value_usd,
    restatement_usd,
    late_refunds,
    late_credit_notes,
    reason
from {{ ref('fct_restatements') }}
order by period, metric
