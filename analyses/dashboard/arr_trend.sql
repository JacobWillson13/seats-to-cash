-- ARR trend: month-end ARR and paying tailnets by billing basis, from the reporting start.
-- Snowflake syntax; compiled by dbt (`dbt compile`), so refs resolve to the MARTS schema.
select
    month,
    sum(arr_usd) as arr_usd,
    sum(case when billing_basis = 'mau' then arr_usd else 0 end) as v3_active_user_arr_usd,
    sum(case when billing_basis = 'seat' then arr_usd else 0 end) as v4_seat_arr_usd,
    sum(case when billing_basis = 'contract' then arr_usd else 0 end) as enterprise_arr_usd,
    count(distinct case when arr_usd > 0 then tailnet_id end) as paying_tailnets
from {{ ref('fct_mrr_monthly') }}
where month >= cast('{{ var("reporting_start_date") }}' as date)
group by month
order by month
