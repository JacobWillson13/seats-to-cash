{# Custom schemas are used as-is (staging, marts, ...) rather than prefixed with the target
   schema. An as-of close build (var as_of_ts) writes to asof_<schema> instead, so it never
   replaces the current build (ADR-023). #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set base = target.schema if custom_schema_name is none else custom_schema_name | trim -%}
    {%- if var('as_of_ts', none) -%}asof_{{ base }}{%- else -%}{{ base }}{%- endif -%}
{%- endmacro %}
