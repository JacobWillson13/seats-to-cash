-- Month-end MRR for every paid subscription active on the month's last day (SPEC §4).
-- Internal Wirefern tailnets (D03) are excluded. ARR is 12 x MRR.
--   v3 (mau):      the month's usage line plus its linked discount line, as Orb billed it.
--   v4 (seat):     seats held at month end x retained unit price, less the discount.
--   Enterprise:    latest won opportunity's recurring ARR / 12 (ADR-016).
with terms as (
    select * from {{ ref('int_subscription_terms_monthly') }}
    where not is_internal
),

usage as (
    select
        u.subscription_id,
        u.service_month as month,
        u.quantity,
        u.amount_usd + coalesce(sum(d.amount_usd), 0) as mrr_usd
    from {{ ref('int_invoice_lines') }} as u
    left join {{ ref('int_invoice_lines') }} as d
        on d.applies_to_line_id = u.line_id and d.line_type = 'discount'
    where u.line_type = 'usage'
    group by u.subscription_id, u.service_month, u.quantity, u.amount_usd, u.line_id
),

contract_arr as (
    select
        m.month_start as month,
        a.tailnet_id,
        o.recurring_arr_usd
    from {{ ref('int_months') }} as m
    inner join {{ ref('stg_salesforce__opportunities') }} as o
        on o.is_won and o.close_date <= m.month_end
    inner join {{ ref('stg_salesforce__accounts') }} as a
        on a.salesforce_account_id = o.salesforce_account_id and a.tailnet_id is not null
    qualify row_number() over (
        partition by m.month_start, a.tailnet_id order by o.close_date desc, o.created_date desc
    ) = 1
),

contract_seats as (
    select
        m.month_start as month,
        q.subscription_id,
        q.quantity
    from {{ ref('int_months') }} as m
    inner join {{ ref('stg_orb__subscription_quantity_changes') }} as q
        on q.source = 'sales' and q.effective_date <= m.month_end
    qualify row_number() over (
        partition by m.month_start, q.subscription_id order by q.effective_date desc, q.recorded_at desc
    ) = 1
),

priced as (
    select
        t.month,
        t.tailnet_id,
        t.subscription_id,
        t.plan_code,
        t.price_version,
        t.billing_basis,
        t.discount_pct,
        case t.billing_basis
            when 'mau' then coalesce(u.quantity, 0)
            when 'seat' then coalesce(s.seats_held, 0)
            when 'contract' then coalesce(q.quantity, 0)
        end as quantity,
        round(t.unit_amount_usd * coalesce(s.seats_held, 0), 2) as seat_amount_usd,
        u.mrr_usd as usage_mrr_usd,
        {{ cents_to_usd(div_round_cents('cast(c.recurring_arr_usd * 100 as bigint)', 12)) }}
            as contract_mrr_usd
    from terms as t
    left join usage as u on u.subscription_id = t.subscription_id and u.month = t.month
    left join {{ ref('int_seats_month_end') }} as s on s.tailnet_id = t.tailnet_id and s.month = t.month
    left join contract_arr as c on c.tailnet_id = t.tailnet_id and c.month = t.month
    left join contract_seats as q on q.subscription_id = t.subscription_id and q.month = t.month
)

select
    month,
    tailnet_id,
    subscription_id,
    plan_code,
    price_version,
    billing_basis,
    discount_pct,
    quantity,
    cast(
        case billing_basis
            when 'mau' then coalesce(usage_mrr_usd, 0)
            when 'seat' then seat_amount_usd - round(seat_amount_usd * discount_pct, 2)
            when 'contract' then coalesce(contract_mrr_usd, 0)
        end as numeric(18, 2)
    ) as mrr_usd,
    cast(
        12 * case billing_basis
            when 'mau' then coalesce(usage_mrr_usd, 0)
            when 'seat' then seat_amount_usd - round(seat_amount_usd * discount_pct, 2)
            when 'contract' then coalesce(contract_mrr_usd, 0)
        end as numeric(18, 2)
    ) as arr_usd
from priced
