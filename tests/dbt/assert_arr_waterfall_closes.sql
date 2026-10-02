-- Every month: opening ARR + movements = closing ARR, and opening = last month's closing.
with w as (
    select
        *,
        lag(closing_arr_usd) over (order by month) as prior_closing_usd
    from {{ ref('fct_arr_waterfall') }}
)

select *
from w
where opening_arr_usd + new_usd + expansion_usd + repricing_usd + contraction_usd + churn_usd
    + reactivation_usd <> closing_arr_usd
    or opening_arr_usd <> coalesce(prior_closing_usd, 0)
