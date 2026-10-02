-- Closed figures that differ in the current build, with the late rows that explain them:
-- refunds and credit notes dated in the period but loaded after its close (D05, ADR-023).
with ledger as (
    select * from {{ ref('fct_close_ledger') }}
),

current_values as (
    select * from {{ ref('fct_close_metrics') }}
),

late_refunds as (
    select
        l.period,
        count(*) as late_refunds,
        sum(r.amount_usd) as late_refunds_usd
    from (select distinct period, as_of_ts from ledger) as l
    inner join {{ ref('stg_stripe__refunds') }} as r
        on {{ period_of('r.created_date') }} = l.period and r.loaded_at > l.as_of_ts
    group by l.period
),

late_credit_notes as (
    select
        l.period,
        count(*) as late_credit_notes,
        sum(c.total_usd) as late_credit_notes_usd
    from (select distinct period, as_of_ts from ledger) as l
    inner join {{ ref('stg_orb__credit_notes') }} as c
        on {{ period_of('c.effective_date') }} = l.period and c._exported_at > l.as_of_ts
    group by l.period
)

select
    l.period,
    l.metric,
    l.close_date,
    l.as_of_ts,
    l.closed_value_usd,
    c.value_usd as current_value_usd,
    c.value_usd - l.closed_value_usd as restatement_usd,
    coalesce(r.late_refunds, 0) as late_refunds,
    coalesce(r.late_refunds_usd, 0) as late_refunds_usd,
    coalesce(n.late_credit_notes, 0) as late_credit_notes,
    coalesce(n.late_credit_notes_usd, 0) as late_credit_notes_usd,
    case
        when coalesce(r.late_refunds, 0) + coalesce(n.late_credit_notes, 0) = 0 then 'unexplained'
        when coalesce(n.late_credit_notes, 0) = 0 then 'late refunds loaded after close'
        when coalesce(r.late_refunds, 0) = 0 then 'late credit notes loaded after close'
        else 'late refunds and credit notes loaded after close'
    end as reason
from ledger as l
inner join current_values as c on c.period = l.period and c.metric = l.metric
left join late_refunds as r on r.period = l.period
left join late_credit_notes as n on n.period = l.period
where c.value_usd <> l.closed_value_usd
