-- Every Orb invoice synced to Stripe matches exactly one deduplicated, live Stripe invoice with
-- the same total, and the totals agree in aggregate.
with orb as (
    select orb_invoice_id, stripe_invoice_id, total_usd
    from {{ ref('stg_orb__invoices') }}
    where stripe_invoice_id is not null
),

stripe as (
    select orb_invoice_id, stripe_invoice_id, total_usd
    from {{ ref('stg_stripe__invoices') }}
),

per_invoice as (
    select o.orb_invoice_id
    from orb as o
    full outer join stripe as s on s.orb_invoice_id = o.orb_invoice_id
    where o.orb_invoice_id is null or s.orb_invoice_id is null
        or o.stripe_invoice_id <> s.stripe_invoice_id or o.total_usd <> s.total_usd
),

totals as (
    select 'aggregate' as orb_invoice_id
    where (select sum(total_usd) from orb) <> (select sum(total_usd) from stripe)
)

select * from per_invoice
union all
select * from totals
