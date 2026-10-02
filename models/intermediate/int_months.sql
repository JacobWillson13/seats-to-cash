-- One row per calendar month of the simulation, sim start through end_date.
with numbered as (
    select n from {{ numbers_10k() }} as k where n < 120
),

months as (
    select cast({{ dbt.dateadd('month', 'n', "cast('" ~ var('sim_start_date') ~ "' as date)") }} as date)
        as month_start
    from numbered
)

select
    month_start,
    cast({{ dbt.dateadd('day', -1, dbt.dateadd('month', 1, 'month_start')) }} as date) as month_end
from months
where month_start <= cast('{{ var("end_date") }}' as date)
