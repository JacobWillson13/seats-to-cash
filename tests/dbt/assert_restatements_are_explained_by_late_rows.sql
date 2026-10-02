-- Every restated figure is explained by refunds or credit notes loaded after the close.
select * from {{ ref('fct_restatements') }} where reason = 'unexplained'
