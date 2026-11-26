{#- Portable surrogate key: md5 of the pipe-joined, null-safe column values (Redshift + DuckDB). -#}
{% macro surrogate_key(cols) -%}
    md5(
    {%- for c in cols -%}
        coalesce(cast({{ c }} as {{ dbt.type_string() }}), '~null~'){% if not loop.last %} || '|' || {% endif %}
    {%- endfor -%}
    )
{%- endmacro %}
