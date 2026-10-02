{# Cross-database helpers: DuckDB locally, Snowflake in the cloud (ADR-004). #}

{# The reporting-time-zone date of a UTC timestamp (ADR-014). #}
{% macro local_date(column) -%}
    {%- if target.type == 'snowflake' -%}
        cast(convert_timezone('UTC', '{{ var("reporting_tz") }}', {{ column }}) as date)
    {%- else -%}
        cast(timezone('{{ var("reporting_tz") }}', timezone('UTC', {{ column }})) as date)
    {%- endif -%}
{%- endmacro %}

{# A string value from a JSON object stored as text. #}
{% macro json_string(column, key) -%}
    {%- if target.type == 'snowflake' -%}
        parse_json({{ column }}):{{ key }}::varchar
    {%- else -%}
        json_extract_string({{ column }}, '$.{{ key }}')
    {%- endif -%}
{%- endmacro %}

{# Stripe integer cents to USD. #}
{% macro cents_to_usd(column) -%}
    cast({{ column }} / 100.0 as numeric(18, 2))
{%- endmacro %}

{# Orb decimal strings to USD. #}
{% macro to_usd(column) -%}
    cast({{ column }} as numeric(18, 2))
{%- endmacro %}

{# Integers 0 .. 9999, portable across warehouses. #}
{% macro numbers_10k() -%}
    (
        select d0.n + 10 * d1.n + 100 * d2.n + 1000 * d3.n as n
        from {{ digits() }} as d0
        cross join {{ digits() }} as d1
        cross join {{ digits() }} as d2
        cross join {{ digits() }} as d3
    )
{%- endmacro %}

{% macro digits() -%}
    (select 0 as n union all select 1 union all select 2 union all select 3 union all select 4
     union all select 5 union all select 6 union all select 7 union all select 8 union all select 9)
{%- endmacro %}

{# The first day of the month after a date. #}
{% macro next_month(column) -%}
    {{ dbt.dateadd('month', 1, dbt.date_trunc('month', column)) }}
{%- endmacro %}

{# A raw column whose name is an SQL keyword. Snowflake raw tables are loaded with upper-case
   names (scripts/snowflake_load.py), so the quoted form must be upper case there. #}
{% macro quoted(name) -%}
    {%- if target.type == 'snowflake' -%}"{{ name | upper }}"{%- else -%}"{{ name }}"{%- endif -%}
{%- endmacro %}

{# Integer cents divided by a positive integer, rounded half away from zero (as Python's
   Decimal ROUND_HALF_UP). Exact for any realistic amount. #}
{% macro div_round_cents(cents, divisor) -%}
    (sign({{ cents }}) * floor((abs({{ cents }}) * 2 + {{ divisor }}) / (2.0 * {{ divisor }})))
{%- endmacro %}
