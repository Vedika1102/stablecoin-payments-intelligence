{% macro safe_divide(num, den) -%}
    case when ({{ den }}) = 0 or ({{ den }}) is null then null else cast({{ num }} as {{ dbt.type_float() }}) / ({{ den }}) end
{%- endmacro %}
