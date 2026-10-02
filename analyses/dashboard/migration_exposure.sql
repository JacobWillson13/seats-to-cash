-- Migration exposure: legacy (v3) MRR and projected v4 MRR by risk tier, with the largest
-- exposed accounts. Snowflake syntax.
with tiers as (
    select
        migration_risk_tier,
        count(*) as tailnets,
        sum(legacy_mrr_usd) * 12 as legacy_arr_usd,
        sum(projected_v4_mrr_usd) * 12 as projected_v4_arr_usd,
        sum(arr_delta_usd) as arr_delta_usd
    from {{ ref('fct_migration_exposure') }}
    group by migration_risk_tier
)

select
    migration_risk_tier,
    tailnets,
    legacy_arr_usd,
    projected_v4_arr_usd,
    arr_delta_usd,
    case when legacy_arr_usd > 0 then arr_delta_usd / legacy_arr_usd end as uplift_pct
from tiers
order by case migration_risk_tier when 'high' then 1 when 'medium' then 2 else 3 end
