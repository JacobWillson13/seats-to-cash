-- Every posted close: the period's metrics as of its close date, from the append-only ledger.
select
    period,
    metric,
    value_usd as closed_value_usd,
    as_of_ts,
    close_date
from {{ source('finance_close', 'close_ledger') }}
