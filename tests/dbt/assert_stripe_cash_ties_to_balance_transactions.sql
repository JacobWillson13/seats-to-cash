-- Successful charges - refunds - fees = balance-transaction net, overall and by month of
-- settlement, and every successful charge and refund has its balance transaction.
with charges as (
    select c.amount_usd, b.available_on, b.fee_usd
    from {{ ref('stg_stripe__charges') }} as c
    left join {{ ref('stg_stripe__balance_transactions') }} as b
        on b.balance_transaction_id = c.balance_transaction_id
    where c.status = 'succeeded'
),

refunds as (
    select r.amount_usd, b.available_on
    from {{ ref('stg_stripe__refunds') }} as r
    left join {{ ref('stg_stripe__balance_transactions') }} as b
        on b.balance_transaction_id = r.balance_transaction_id
),

expected as (
    select cast({{ dbt.date_trunc('month', 'available_on') }} as date) as month,
           sum(amount_usd) - sum(fee_usd) as net_usd
    from charges group by 1
    union all
    select cast({{ dbt.date_trunc('month', 'available_on') }} as date), -sum(amount_usd)
    from refunds group by 1
),

expected_by_month as (
    select month, sum(net_usd) as net_usd from expected group by 1
),

actual_by_month as (
    select cast({{ dbt.date_trunc('month', 'available_on') }} as date) as month,
           sum(net_usd) as net_usd
    from {{ ref('stg_stripe__balance_transactions') }} group by 1
)

select coalesce(e.month, a.month) as month, e.net_usd as expected_usd, a.net_usd as actual_usd
from expected_by_month as e
full outer join actual_by_month as a on a.month = e.month
where e.net_usd is distinct from a.net_usd
union all
select null, null, null from charges where available_on is null
union all
select null, null, null from refunds where available_on is null
