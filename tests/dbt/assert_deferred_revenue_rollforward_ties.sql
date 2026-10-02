-- opening + billings - revenue = closing, and closing equals the independently computed
-- unrecognized remainder of every billed line.
select *
from {{ ref('fct_deferred_revenue_rollforward') }}
where opening_usd + billings_usd - revenue_usd <> closing_usd
    or closing_usd <> closing_check_usd
